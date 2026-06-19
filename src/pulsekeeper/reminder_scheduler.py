from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from inspect import isawaitable
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pulsekeeper.storage.reminders import Reminder, ReminderStore
from pulsekeeper.storage.sqlite import Database

SendMessage = Callable[[int, str], None]
ProcessDue = Callable[..., Awaitable[int]]
Sleep = Callable[[float], Any]


class TelegramReminderScheduler:
    def __init__(self, *, db: Database, send_message: SendMessage) -> None:
        self.db = db
        self.reminders = ReminderStore(db)
        self.send_message = send_message

    async def process_due(self, *, now: datetime) -> int:
        now = _ensure_aware_datetime(now).astimezone(UTC)
        sent_count = 0
        for reminder in await self.reminders.due(now=now):
            chat_id = await self._telegram_chat_id(reminder.user_id)
            next_due_at = next_due_after(reminder, now=now)
            if chat_id is None:
                await self.reminders.mark_sent(reminder.id, sent_at=now, next_due_at=next_due_at)
                continue
            self.send_message(chat_id, reminder_text(reminder))
            await self.reminders.mark_sent(reminder.id, sent_at=now, next_due_at=next_due_at)
            sent_count += 1
        return sent_count

    async def _telegram_chat_id(self, user_id: int) -> int | None:
        row = await self.db.fetchone(
            """
            SELECT external_chat_id
            FROM gateway_accounts
            WHERE user_id = ? AND gateway = 'telegram'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (user_id,),
        )
        if row is None or row["external_chat_id"] is None:
            return None
        return int(row["external_chat_id"])


def reminder_text(reminder: Reminder) -> str:
    labels = {
        "weight": "вес",
        "sleep": "сон",
        "training": "тренировку",
        "workout": "тренировку",
        "symptom": "самочувствие",
        "medication": "лекарство",
        "journal": "самочувствие",
        "food": "еду",
    }
    label = labels.get(reminder.type.lower(), reminder.type)
    return f"Короткое напоминание: можно записать {label} одной фразой."


def next_due_after(reminder: Reminder, *, now: datetime) -> datetime | None:
    if reminder.schedule.get("kind") != "daily":
        return None
    reminder_time = _parse_time(str(reminder.schedule.get("time", "")))
    if reminder_time is None:
        return None
    try:
        timezone = ZoneInfo(reminder.timezone)
    except ZoneInfoNotFoundError:
        timezone = UTC
    local_now = _ensure_aware_datetime(now).astimezone(timezone)
    candidate = datetime.combine(local_now.date(), reminder_time, tzinfo=timezone)
    while candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def _parse_time(value: str) -> time | None:
    try:
        hour_text, minute_text = value.split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return None
    if hour not in range(24) or minute not in range(60):
        return None
    return time(hour=hour, minute=minute)


def _ensure_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


async def run_scheduler_loop(
    *,
    process_due: ProcessDue,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    max_iterations: int | None = None,
    interval_seconds: float = 60.0,
    sleep: Sleep = asyncio.sleep,
) -> None:
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        await process_due(now=now())
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        if interval_seconds:
            maybe_awaitable = sleep(interval_seconds)
            if isawaitable(maybe_awaitable):
                await maybe_awaitable


__all__ = [
    "TelegramReminderScheduler",
    "next_due_after",
    "reminder_text",
    "run_scheduler_loop",
]
