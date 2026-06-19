from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pulsekeeper.llm.agent import AgentDeps, MessageContext, PulseKeeperAgent, run_turn
from pulsekeeper.storage.health_entries import HealthEntryStore
from pulsekeeper.storage.media import LocalMediaStore, MediaAttachment
from pulsekeeper.storage.memory import ProfileStore
from pulsekeeper.storage.reminders import ReminderStore
from pulsekeeper.storage.sqlite import Database
from pulsekeeper.storage.users import UserStore

Bot: Any = None
Dispatcher: Any = None
Router: Any = None
CommandStart: Any = None

START_TEXT = (
    "Привет. Я PulseKeeper — личный health-дневник в Telegram.\n\n"
    "Можно писать обычным текстом:\n"
    "• вес 82.4\n"
    "• завтрак омлет и кофе\n"
    "• тренировка 45 минут\n"
    "• болела голова вечером\n"
    "• напомни взвешиваться утром\n"
    "• дай сводку за неделю\n\n"
    "Данные хранятся в твоей локальной базе. Текст сообщений может отправляться "
    "выбранному тобой LLM-провайдеру (BYO-LLM: твой API-ключ или подписка).\n\n"
    "Я не врач и не ставлю диагнозы, но помогу аккуратно вести журнал и замечать паттерны.\n\n"
    "Для начала: в каком часовом поясе вести дневник?"
)
HELP_TEXT = (
    "PulseKeeper commands:\n"
    "/start - show the welcome message\n"
    "/help - show this help\n"
    "/summary - summarize this week's health entries\n"
    "/today - summarize today's health entries\n"
    "/week - summarize this week's health entries\n"
    "/undo - delete the latest health entry\n"
    "/profile - show known profile facts\n"
    "/remind <type> daily HH:MM - schedule a daily reminder\n"
    "/reminders - list active reminders\n"
    "/reminder off - turn off the next active reminder"
)
DENIED_TEXT = "You are not authorized to use this PulseKeeper bot."
PRIVATE_CHAT_ONLY_TEXT = "PulseKeeper only replies with health data in a private chat."
UNKNOWN_COMMAND_TEXT = "Unknown command. Use /help to see supported commands."


@dataclass(frozen=True)
class TelegramGatewayConfig:
    bot_token: str
    owner_telegram_user_id: int
    default_timezone: str = "UTC"

    def __repr__(self) -> str:
        return (
            "TelegramGatewayConfig("
            "bot_token='***', "
            f"owner_telegram_user_id={self.owner_telegram_user_id!r}, "
            f"default_timezone={self.default_timezone!r}"
            ")"
        )


@dataclass(frozen=True)
class TelegramPhoto:
    file_id: str
    file_unique_id: str
    width: int
    height: int
    file_size: int | None = None


class TelegramGateway:
    def __init__(
        self,
        *,
        config: TelegramGatewayConfig,
        db: Database,
        health_entries: HealthEntryStore,
        agent: PulseKeeperAgent | Any,
        users: UserStore | None = None,
        media_store: LocalMediaStore | None = None,
    ) -> None:
        self.config = config
        self.db = db
        self.health_entries = health_entries
        self.agent = agent
        self.users = users or UserStore(db)
        self.media_store = media_store
        self.profile = ProfileStore(db)
        self.reminders = ReminderStore(db)

    async def resolve_user(self, *, telegram_user_id: int, chat_id: int) -> int:
        if telegram_user_id != self.config.owner_telegram_user_id:
            raise PermissionError("telegram user is not in the owner allowlist")

        return await self.users.resolve_gateway_user(
            gateway="telegram",
            external_user_id=str(telegram_user_id),
            external_chat_id=str(chat_id),
        )

    async def handle_text(
        self,
        text: str,
        *,
        telegram_user_id: int,
        chat_id: int,
        chat_type: str = "private",
        message_id: int | None = None,
        now: datetime | None = None,
    ) -> str:
        if chat_type != "private":
            return PRIVATE_CHAT_ONLY_TEXT

        try:
            user_id = await self.resolve_user(telegram_user_id=telegram_user_id, chat_id=chat_id)
        except PermissionError:
            return DENIED_TEXT

        received_at = now or datetime.now(UTC)
        normalized_text = text.strip()
        command = _command_name(normalized_text)
        if command is not None:
            if command in {"start", "help"}:
                return START_TEXT if command == "start" else HELP_TEXT
            if command == "summary":
                return await self._summary_text(user_id=user_id, period="week", now=received_at)
            if command == "today":
                return await self._summary_text(user_id=user_id, period="today", now=received_at)
            if command == "week":
                return await self._summary_text(user_id=user_id, period="week", now=received_at)
            if command == "undo":
                return await self._undo_text(user_id=user_id)
            if command == "profile":
                return await self._profile_text(user_id=user_id)
            if command == "set":
                return await self._set_text(user_id=user_id, text=normalized_text)
            if command == "remind":
                return await self._remind_text(
                    user_id=user_id,
                    text=normalized_text,
                    now=received_at,
                )
            if command == "reminder":
                return await self._reminder_text(user_id=user_id, text=normalized_text)
            if command == "reminders":
                return await self._reminders_text(user_id=user_id)
            return UNKNOWN_COMMAND_TEXT

        context = MessageContext(
            user_id=user_id,
            chat_id=chat_id,
            text=text,
            attachments=[],
            now=received_at,
            timezone=self.config.default_timezone,
            message_id=message_id,
            source="telegram",
        )
        deps = AgentDeps(
            user_id=user_id,
            health_entries=self.health_entries,
            now=received_at,
            timezone=self.config.default_timezone,
            source="telegram",
        )
        reply = await run_turn(self.agent, context, deps)
        return _telegram_safe(reply.text)

    async def handle_photo(
        self,
        *,
        photos: list[TelegramPhoto],
        photo_bytes: bytes | None,
        caption: str | None,
        telegram_user_id: int,
        chat_id: int,
        chat_type: str = "private",
        message_id: int | None = None,
        now: datetime | None = None,
        content_type: str = "image/jpeg",
    ) -> str:
        if chat_type != "private":
            return PRIVATE_CHAT_ONLY_TEXT

        try:
            user_id = await self.resolve_user(telegram_user_id=telegram_user_id, chat_id=chat_id)
        except PermissionError:
            return DENIED_TEXT

        received_at = now or datetime.now(UTC)
        photo = max(photos, key=lambda item: item.width * item.height)
        attachments: list[MediaAttachment | TelegramPhoto]
        if self.media_store is not None and photo_bytes is not None:
            attachments = [
                self.media_store.save_telegram_photo(
                    user_id=user_id,
                    file_unique_id=photo.file_unique_id,
                    file_id=photo.file_id,
                    content=photo_bytes,
                    content_type=content_type,
                    now=received_at,
                    width=photo.width,
                    height=photo.height,
                    file_size=photo.file_size,
                )
            ]
        else:
            attachments = [photo]

        text = caption or "Please help me log this food photo. Do not estimate precise calories."
        context = MessageContext(
            user_id=user_id,
            chat_id=chat_id,
            text=text.strip(),
            attachments=attachments,
            now=received_at,
            timezone=self.config.default_timezone,
            message_id=message_id,
            source="telegram",
        )
        deps = AgentDeps(
            user_id=user_id,
            health_entries=self.health_entries,
            now=received_at,
            timezone=self.config.default_timezone,
            source="telegram",
        )
        reply = await run_turn(self.agent, context, deps)
        return _telegram_safe(reply.text)

    async def _summary_text(self, *, user_id: int, period: str, now: datetime) -> str:
        start, end = _summary_bounds(period, now=now, timezone=self.config.default_timezone)
        entries = await self.health_entries.list(user_id, start=start, end=end)
        counts = Counter(entry.kind for entry in entries)
        lines = [
            f"{period.capitalize()} summary",
            f"Found {len(entries)} health entries.",
            f"Range: {start.date().isoformat()} to {end.date().isoformat()}",
        ]
        if counts:
            lines.append("Counts by kind:")
            lines.extend(f"- {kind}: {count}" for kind, count in sorted(counts.items()))
        else:
            lines.append("No entries found for this period.")
        return "\n".join(lines)

    async def _undo_text(self, *, user_id: int) -> str:
        entry = await self.health_entries.get_last(user_id)
        if entry is None or entry.id is None:
            return "No health entries to undo."
        await self.health_entries.soft_delete(entry.id)
        details = entry.kind
        if entry.value is not None:
            details += f" {entry.value:g}"
            if entry.unit:
                details += f" {entry.unit}"
        elif entry.note:
            details += f": {entry.note}"
        return f"Deleted last entry: {details}."

    async def _set_text(self, *, user_id: int, text: str) -> str:
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            return "Usage: /set timezone <IANA timezone> or /set goal <goal>."

        field = parts[1].lower()
        value = parts[2].strip()
        if not value:
            return "Usage: /set timezone <IANA timezone> or /set goal <goal>."

        if field == "timezone":
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError:
                return f"Unknown timezone: {value}. Use an IANA timezone like Europe/Moscow."
            await self.profile.set_fact(user_id, "timezone", value, source="telegram_command")
            return f"Saved timezone: {value}."

        if field == "goal":
            await self.profile.set_fact(user_id, "goal", value, source="telegram_command")
            return f"Saved goal: {value}."

        return "Usage: /set timezone <IANA timezone> or /set goal <goal>."

    async def _profile_text(self, *, user_id: int) -> str:
        facts = await self.profile.list_facts(user_id)
        if not facts:
            return "Profile\nNo profile facts saved yet."
        lines = ["Profile"]
        for key, value in facts.items():
            lines.append(f"- {key}: {_format_profile_value(value)}")
        return "\n".join(lines)

    async def _remind_text(self, *, user_id: int, text: str, now: datetime) -> str:
        parts = text.split()
        if len(parts) != 4 or parts[2].lower() != "daily":
            return "Usage: /remind <type> daily HH:MM."

        reminder_type = parts[1].lower()
        reminder_time = parts[3]
        parsed_time = _parse_reminder_time(reminder_time)
        if parsed_time is None:
            return "Usage: /remind <type> daily HH:MM."

        timezone = await self._user_timezone(user_id)
        next_due_at = _next_daily_due_at(now=now, reminder_time=parsed_time, timezone=timezone)
        await self.reminders.create(
            user_id=user_id,
            type=reminder_type,
            schedule={"kind": "daily", "time": reminder_time},
            timezone=timezone,
            next_due_at=next_due_at,
        )
        return f"Scheduled daily {reminder_type} reminder at {reminder_time} {timezone}."

    async def _reminders_text(self, *, user_id: int) -> str:
        reminders = await self._active_reminders(user_id)
        if not reminders:
            return "Reminders\nNo active reminders."
        lines = ["Reminders"]
        for reminder in reminders:
            schedule_kind = reminder.schedule.get("kind", "custom")
            schedule_time = reminder.schedule.get("time", "unscheduled")
            lines.append(
                f"- #{reminder.id} {reminder.type} {schedule_kind} "
                f"at {schedule_time} {reminder.timezone}"
            )
        return "\n".join(lines)

    async def _reminder_text(self, *, user_id: int, text: str) -> str:
        parts = text.split()
        if len(parts) != 2 or parts[1].lower() != "off":
            return "Usage: /reminder off."
        reminders = await self._active_reminders(user_id)
        if not reminders:
            return "No active reminders to turn off."
        reminder = reminders[0]
        await self.reminders.disable(reminder.id)
        return f"Turned off reminder #{reminder.id}."

    async def _active_reminders(self, user_id: int):
        return [reminder for reminder in await self.reminders.list(user_id) if reminder.enabled]

    async def _user_timezone(self, user_id: int) -> str:
        value = await self.profile.get_fact(user_id, "timezone")
        if isinstance(value, str):
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError:
                pass
            else:
                return value
        return self.config.default_timezone


def build_dispatcher(gateway: TelegramGateway) -> Any:
    global CommandStart, Dispatcher, Router
    if Dispatcher is None or Router is None or CommandStart is None:
        from aiogram import Dispatcher as AiogramDispatcher
        from aiogram import Router as AiogramRouter
        from aiogram.filters import CommandStart as AiogramCommandStart

        Dispatcher = AiogramDispatcher
        Router = AiogramRouter
        CommandStart = AiogramCommandStart

    router = Router()

    @router.message(CommandStart())
    async def handle_start(message: Any) -> None:
        await _answer_message(gateway, message)

    @router.message()
    async def handle_message(message: Any) -> None:
        await _answer_message(gateway, message)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def _answer_message(gateway: TelegramGateway, message: Any) -> None:
    if message.from_user is None:
        return
    if message.text is not None:
        reply = await gateway.handle_text(
            message.text,
            telegram_user_id=message.from_user.id,
            chat_id=message.chat.id,
            chat_type=str(message.chat.type),
            message_id=message.message_id,
        )
        await message.answer(reply)
        return
    photos = getattr(message, "photo", None)
    if photos:
        reply = await gateway.handle_photo(
            photos=[
                TelegramPhoto(
                    file_id=photo.file_id,
                    file_unique_id=photo.file_unique_id,
                    width=photo.width,
                    height=photo.height,
                    file_size=getattr(photo, "file_size", None),
                )
                for photo in photos
            ],
            photo_bytes=None,
            caption=getattr(message, "caption", None),
            telegram_user_id=message.from_user.id,
            chat_id=message.chat.id,
            chat_type=str(message.chat.type),
            message_id=message.message_id,
        )
        await message.answer(reply)


async def run_polling(gateway: TelegramGateway) -> None:
    global Bot
    if Bot is None:
        from aiogram import Bot as AiogramBot

        Bot = AiogramBot

    bot = Bot(token=gateway.config.bot_token)
    dispatcher = build_dispatcher(gateway)
    await dispatcher.start_polling(bot)


def _command_name(text: str) -> str | None:
    if not text.startswith("/"):
        return None
    raw = text.split(maxsplit=1)[0][1:]
    command = raw.split("@", maxsplit=1)[0].lower()
    return command or None


def _format_profile_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _summary_bounds(
    period: str,
    *,
    now: datetime,
    timezone: str = "UTC",
) -> tuple[datetime, datetime]:
    if now.tzinfo is None or now.utcoffset() is None:
        now = now.replace(tzinfo=UTC)

    try:
        local_tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        local_tz = UTC
    local_now = now.astimezone(local_tz)

    if period == "today":
        start_date = local_now.date()
        end_date = start_date + timedelta(days=1)
    elif period == "week":
        start_date = local_now.date() - timedelta(days=local_now.weekday())
        end_date = start_date + timedelta(days=7)
    else:  # pragma: no cover - callers constrain periods
        raise ValueError(f"unsupported summary period: {period}")
    return (
        datetime.combine(start_date, time.min, tzinfo=local_tz).astimezone(UTC),
        datetime.combine(end_date, time.min, tzinfo=local_tz).astimezone(UTC),
    )


def _parse_reminder_time(value: str) -> time | None:
    try:
        hour_text, minute_text = value.split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
        return time(hour=hour, minute=minute)
    except (TypeError, ValueError):
        return None


def _next_daily_due_at(*, now: datetime, reminder_time: time, timezone: str) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        now = now.replace(tzinfo=UTC)
    try:
        local_tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        local_tz = UTC
    local_now = now.astimezone(local_tz)
    due_date = local_now.date()
    local_due = datetime.combine(due_date, reminder_time, tzinfo=local_tz)
    if local_due <= local_now:
        local_due += timedelta(days=1)
    return local_due.astimezone(UTC)


def _telegram_safe(text: str) -> str:
    # We do not set a parse_mode in the aiogram boundary, so plain text is Telegram-safe.
    return text


__all__ = [
    "DENIED_TEXT",
    "HELP_TEXT",
    "START_TEXT",
    "TelegramGateway",
    "TelegramGatewayConfig",
    "TelegramPhoto",
    "PRIVATE_CHAT_ONLY_TEXT",
    "UNKNOWN_COMMAND_TEXT",
    "build_dispatcher",
    "run_polling",
]
