from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pulsekeeper.domain import HealthEntryDraft
from pulsekeeper.llm.agent import AgentReply, MessageContext
from pulsekeeper.storage.health_entries import HealthEntryStore
from pulsekeeper.storage.sqlite import Database


def run(coro):
    return asyncio.run(coro)


def test_authorized_owner_message_creates_account_and_routes_text_to_agent(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            store = HealthEntryStore(db)
            calls = []

            async def fake_run_turn(agent, context, deps):
                calls.append((agent, context, deps))
                return AgentReply(
                    text="agent reply",
                    tool_trace=[],
                    used_iterations=0,
                    finished_reason="completed",
                )

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=store,
                agent=object(),
            )

            reply = await gateway.handle_text(
                "logged breakfast",
                telegram_user_id=111,
                chat_id=222,
                message_id=333,
                now=datetime(2026, 6, 13, 9, 30, tzinfo=UTC),
            )

            assert reply == "agent reply"
            rows = await db.fetchall("SELECT * FROM gateway_accounts")
            assert len(rows) == 1
            assert rows[0]["gateway"] == "telegram"
            assert rows[0]["external_user_id"] == "111"
            assert rows[0]["external_chat_id"] == "222"
            assert calls
            _, context, deps = calls[0]
            assert isinstance(context, MessageContext)
            assert context.source == "telegram"
            assert context.text == "logged breakfast"
            assert context.chat_id == 222
            assert context.message_id == 333
            assert context.user_id == rows[0]["user_id"]
            assert deps.user_id == rows[0]["user_id"]
            assert deps.source == "telegram"
            assert deps.health_entries is store
        finally:
            await db.close()

    run(scenario())


def test_authorized_owner_photo_routes_caption_and_saved_attachment_to_agent(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import (
            TelegramGateway,
            TelegramGatewayConfig,
            TelegramPhoto,
        )
        from pulsekeeper.storage.media import LocalMediaStore

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            store = HealthEntryStore(db)
            calls = []

            async def fake_run_turn(agent, context, deps):
                calls.append((agent, context, deps))
                return AgentReply(
                    text=(
                        "What meal details should I log from this photo? "
                        "I will not estimate precise calories."
                    ),
                    tool_trace=[],
                    used_iterations=0,
                    finished_reason="completed",
                )

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=store,
                agent=object(),
                media_store=LocalMediaStore(tmp_path / "media"),
            )

            reply = await gateway.handle_photo(
                photos=[
                    TelegramPhoto(
                        file_id="small-file",
                        file_unique_id="small-unique",
                        width=90,
                        height=90,
                        file_size=512,
                    ),
                    TelegramPhoto(
                        file_id="large-file",
                        file_unique_id="large-unique",
                        width=1280,
                        height=720,
                        file_size=4096,
                    ),
                ],
                photo_bytes=b"fake jpeg",
                caption="lunch plate",
                telegram_user_id=111,
                chat_id=222,
                message_id=444,
                now=datetime(2026, 6, 14, 12, 0, tzinfo=UTC),
            )

            assert "precise calories" in reply
            assert calls
            _, context, deps = calls[0]
            assert context.text == "lunch plate"
            assert context.message_id == 444
            assert len(context.attachments) == 1
            attachment = context.attachments[0]
            assert attachment.kind == "photo"
            assert attachment.file_id == "large-file"
            assert attachment.file_unique_id == "large-unique"
            assert attachment.width == 1280
            assert attachment.height == 720
            assert attachment.path.read_bytes() == b"fake jpeg"
            assert deps.health_entries is store
        finally:
            await db.close()

    run(scenario())


def test_unauthorized_user_gets_denial_without_account_or_agent_call(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            calls = []

            async def fake_run_turn(agent, context, deps):
                calls.append((agent, context, deps))
                raise AssertionError("run_turn should not be called")

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=HealthEntryStore(db),
                agent=object(),
            )

            reply = await gateway.handle_text(
                "hello",
                telegram_user_id=999,
                chat_id=222,
                message_id=1,
                now=datetime(2026, 6, 13, tzinfo=UTC),
            )

            assert "not authorized" in reply.lower()
            assert calls == []
            assert await db.fetchval("SELECT COUNT(*) FROM gateway_accounts") == 0
            assert await db.fetchval("SELECT COUNT(*) FROM users") == 0
        finally:
            await db.close()

    run(scenario())


def test_start_and_help_bypass_model(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            calls = []

            async def fake_run_turn(agent, context, deps):
                calls.append((agent, context, deps))
                raise AssertionError("run_turn should not be called")

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=HealthEntryStore(db),
                agent=object(),
            )

            start = await gateway.handle_text(
                "/start",
                telegram_user_id=111,
                chat_id=222,
                message_id=1,
                now=datetime(2026, 6, 13, tzinfo=UTC),
            )
            help_text = await gateway.handle_text(
                "/help",
                telegram_user_id=111,
                chat_id=222,
                message_id=2,
                now=datetime(2026, 6, 13, tzinfo=UTC),
            )

            assert "PulseKeeper" in start
            assert "/today" in help_text
            assert "/week" in help_text
            assert "/remind" in help_text
            assert "/reminder off" in help_text
            assert calls == []
        finally:
            await db.close()

    run(scenario())


def test_week_returns_health_entry_counts_and_bypasses_model(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            store = HealthEntryStore(db)
            calls = []

            async def fake_run_turn(agent, context, deps):
                calls.append((agent, context, deps))
                raise AssertionError("run_turn should not be called")

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=store,
                agent=object(),
            )
            user_id = await gateway.resolve_user(telegram_user_id=111, chat_id=222)
            now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
            await store.append(
                user_id,
                HealthEntryDraft(
                    kind="food",
                    note="oatmeal",
                    logged_at=now - timedelta(days=1),
                    source="telegram",
                ),
            )
            await store.append(
                user_id,
                HealthEntryDraft(
                    kind="sleep",
                    note="8h",
                    logged_at=now - timedelta(days=2),
                    source="telegram",
                ),
            )
            await store.append(
                user_id,
                HealthEntryDraft(
                    kind="food",
                    note="last week",
                    logged_at=now - timedelta(days=8),
                    source="telegram",
                ),
            )

            reply = await gateway.handle_text(
                "/week",
                telegram_user_id=111,
                chat_id=222,
                message_id=5,
                now=now,
            )

            assert "Found 2 health entries" in reply
            assert "food: 1" in reply
            assert "sleep: 1" in reply
            assert "last week" not in reply
            assert calls == []
        finally:
            await db.close()

    run(scenario())


def test_config_repr_redacts_bot_token():
    from pulsekeeper.gateway.telegram import TelegramGatewayConfig

    config = TelegramGatewayConfig(bot_token="123456:super-secret", owner_telegram_user_id=111)

    rendered = repr(config)
    assert "123456:super-secret" not in rendered
    assert "***" in rendered


def test_concurrent_owner_resolution_creates_one_account(tmp_path):
    async def scenario() -> None:
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=HealthEntryStore(db),
                agent=object(),
            )

            user_ids = await asyncio.gather(
                gateway.resolve_user(telegram_user_id=111, chat_id=222),
                gateway.resolve_user(telegram_user_id=111, chat_id=222),
            )

            assert user_ids[0] == user_ids[1]
            assert await db.fetchval("SELECT COUNT(*) FROM users") == 1
            assert await db.fetchval("SELECT COUNT(*) FROM gateway_accounts") == 1
        finally:
            await db.close()

    run(scenario())


def test_owner_group_message_is_denied_without_account_or_agent_call(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            calls = []

            async def fake_run_turn(agent, context, deps):
                calls.append((agent, context, deps))
                raise AssertionError("run_turn should not be called")

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=HealthEntryStore(db),
                agent=object(),
            )

            reply = await gateway.handle_text(
                "/week",
                telegram_user_id=111,
                chat_id=-100222,
                chat_type="group",
                message_id=1,
                now=datetime(2026, 6, 13, tzinfo=UTC),
            )

            assert "private chat" in reply.lower()
            assert calls == []
            assert await db.fetchval("SELECT COUNT(*) FROM gateway_accounts") == 0
            assert await db.fetchval("SELECT COUNT(*) FROM users") == 0
        finally:
            await db.close()

    run(scenario())


def test_today_summary_uses_configured_timezone_for_local_day(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            store = HealthEntryStore(db)

            async def fake_run_turn(agent, context, deps):
                raise AssertionError("run_turn should not be called")

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(
                    bot_token="secret-token",
                    owner_telegram_user_id=111,
                    default_timezone="Europe/Moscow",
                ),
                db=db,
                health_entries=store,
                agent=object(),
            )
            user_id = await gateway.resolve_user(telegram_user_id=111, chat_id=222)
            now = datetime(2026, 6, 13, 21, 30, tzinfo=UTC)  # 2026-06-14 00:30 MSK
            await store.append(
                user_id,
                HealthEntryDraft(
                    kind="sleep",
                    note="local today",
                    logged_at=datetime(2026, 6, 13, 21, 15, tzinfo=UTC),
                    source="telegram",
                ),
            )
            await store.append(
                user_id,
                HealthEntryDraft(
                    kind="food",
                    note="previous local day",
                    logged_at=datetime(2026, 6, 13, 20, 30, tzinfo=UTC),
                    source="telegram",
                ),
            )

            reply = await gateway.handle_text(
                "/today",
                telegram_user_id=111,
                chat_id=222,
                message_id=6,
                now=now,
            )

            assert "Found 1 health entries" in reply
            assert "sleep: 1" in reply
            assert "food: 1" not in reply
        finally:
            await db.close()

    run(scenario())


def test_answer_message_routes_telegram_photo_metadata_without_live_download():
    from pulsekeeper.gateway.telegram import _answer_message

    calls = []
    replies = []

    class FakeGateway:
        async def handle_photo(self, **kwargs):
            calls.append(kwargs)
            return "photo reply"

    async def answer(text: str) -> None:
        replies.append(text)

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=111),
        chat=SimpleNamespace(id=222, type="private"),
        text=None,
        caption="dinner",
        photo=[
            SimpleNamespace(
                file_id="small",
                file_unique_id="u-small",
                width=64,
                height=64,
                file_size=100,
            ),
            SimpleNamespace(
                file_id="large",
                file_unique_id="u-large",
                width=800,
                height=600,
                file_size=2000,
            ),
        ],
        message_id=555,
        answer=answer,
    )

    run(_answer_message(FakeGateway(), message))

    assert replies == ["photo reply"]
    assert calls[0]["caption"] == "dinner"
    assert calls[0]["photo_bytes"] is None
    assert calls[0]["telegram_user_id"] == 111
    assert calls[0]["chat_id"] == 222
    assert calls[0]["message_id"] == 555
    assert calls[0]["photos"][1].file_unique_id == "u-large"


def test_run_polling_builds_aiogram_bot_without_live_network(monkeypatch):
    from pulsekeeper.gateway import telegram
    from pulsekeeper.gateway.telegram import TelegramGatewayConfig, run_polling

    events = []

    class FakeBot:
        def __init__(self, token: str) -> None:
            events.append(("bot", token))

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            events.append(("poll", bot.__class__.__name__))

    gateway = SimpleNamespace(config=TelegramGatewayConfig("secret-token", 111))
    monkeypatch.setattr(telegram, "Bot", FakeBot)
    monkeypatch.setattr(telegram, "build_dispatcher", lambda received: FakeDispatcher())

    run(run_polling(gateway))

    assert events == [("bot", "secret-token"), ("poll", "FakeBot")]


def test_summary_alias_returns_week_summary_and_bypasses_model(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            store = HealthEntryStore(db)
            calls = []

            async def fake_run_turn(agent, context, deps):
                calls.append((agent, context, deps))
                raise AssertionError("run_turn should not be called")

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=store,
                agent=object(),
            )
            user_id = await gateway.resolve_user(telegram_user_id=111, chat_id=222)
            now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
            await store.append(
                user_id,
                HealthEntryDraft(
                    kind="weight",
                    value=84.2,
                    unit="kg",
                    logged_at=now,
                    source="telegram",
                ),
            )

            reply = await gateway.handle_text(
                "/summary",
                telegram_user_id=111,
                chat_id=222,
                message_id=7,
                now=now,
            )

            assert "Week summary" in reply
            assert "Found 1 health entries" in reply
            assert "weight: 1" in reply
            assert calls == []
        finally:
            await db.close()

    run(scenario())


def test_undo_soft_deletes_last_entry_and_reports_it(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            store = HealthEntryStore(db)

            async def fake_run_turn(agent, context, deps):
                raise AssertionError("run_turn should not be called")

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=store,
                agent=object(),
            )
            user_id = await gateway.resolve_user(telegram_user_id=111, chat_id=222)
            now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
            first = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="food",
                    note="breakfast",
                    logged_at=now - timedelta(minutes=5),
                    source="telegram",
                ),
            )
            second = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="weight",
                    value=84.2,
                    unit="kg",
                    logged_at=now,
                    source="telegram",
                ),
            )

            reply = await gateway.handle_text(
                "/undo",
                telegram_user_id=111,
                chat_id=222,
                message_id=8,
                now=now,
            )

            assert "Deleted last entry" in reply
            assert "weight" in reply
            assert await store.get_last(user_id) == first
            deleted = await db.fetchone(
                "SELECT deleted_at FROM health_entries WHERE id = ?",
                (second.id,),
            )
            assert deleted is not None
            assert deleted["deleted_at"] is not None
        finally:
            await db.close()

    run(scenario())


def test_undo_without_entries_returns_clear_message(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            async def fake_run_turn(agent, context, deps):
                raise AssertionError("run_turn should not be called")

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=HealthEntryStore(db),
                agent=object(),
            )

            reply = await gateway.handle_text(
                "/undo",
                telegram_user_id=111,
                chat_id=222,
                message_id=8,
                now=datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
            )

            assert "No health entries" in reply
        finally:
            await db.close()

    run(scenario())


def test_profile_lists_known_profile_facts(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig
        from pulsekeeper.storage.memory import ProfileStore

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            async def fake_run_turn(agent, context, deps):
                raise AssertionError("run_turn should not be called")

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=HealthEntryStore(db),
                agent=object(),
            )
            user_id = await gateway.resolve_user(telegram_user_id=111, chat_id=222)
            profile = ProfileStore(db)
            await profile.set_fact(user_id, "timezone", "Europe/Moscow", source="telegram")
            await profile.set_fact(
                user_id,
                "goal",
                {"kind": "lose", "target": "slow"},
                source="telegram",
            )

            reply = await gateway.handle_text(
                "/profile",
                telegram_user_id=111,
                chat_id=222,
                message_id=9,
                now=datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
            )

            assert "Profile" in reply
            assert "timezone: Europe/Moscow" in reply
            assert "goal:" in reply
            assert "lose" in reply
        finally:
            await db.close()

    run(scenario())


def test_set_timezone_and_goal_commands_write_profile_facts(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig
        from pulsekeeper.storage.memory import ProfileStore

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            async def fake_run_turn(agent, context, deps):
                raise AssertionError("run_turn should not be called")

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=HealthEntryStore(db),
                agent=object(),
            )

            timezone_reply = await gateway.handle_text(
                "/set timezone Europe/Moscow",
                telegram_user_id=111,
                chat_id=222,
                message_id=11,
                now=datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
            )
            goal_reply = await gateway.handle_text(
                "/set goal lose weight slowly",
                telegram_user_id=111,
                chat_id=222,
                message_id=12,
                now=datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
            )

            user_id = await gateway.resolve_user(telegram_user_id=111, chat_id=222)
            profile = ProfileStore(db)
            assert "timezone" in timezone_reply.lower()
            assert await profile.get_fact(user_id, "timezone") == "Europe/Moscow"
            assert "goal" in goal_reply.lower()
            assert await profile.get_fact(user_id, "goal") == "lose weight slowly"
        finally:
            await db.close()

    run(scenario())


def test_reminder_commands_schedule_list_and_cancel_without_model_call(tmp_path, monkeypatch):
    async def scenario() -> None:
        from pulsekeeper.gateway import telegram
        from pulsekeeper.gateway.telegram import TelegramGateway, TelegramGatewayConfig
        from pulsekeeper.storage.memory import ProfileStore
        from pulsekeeper.storage.reminders import ReminderStore

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            calls = []

            async def fake_run_turn(agent, context, deps):
                calls.append((agent, context, deps))
                raise AssertionError("run_turn should not be called")

            monkeypatch.setattr(telegram, "run_turn", fake_run_turn)
            gateway = TelegramGateway(
                config=TelegramGatewayConfig(bot_token="secret-token", owner_telegram_user_id=111),
                db=db,
                health_entries=HealthEntryStore(db),
                agent=object(),
            )
            user_id = await gateway.resolve_user(telegram_user_id=111, chat_id=222)
            await ProfileStore(db).set_fact(user_id, "timezone", "Europe/Moscow", source="test")

            empty_reply = await gateway.handle_text(
                "/reminders",
                telegram_user_id=111,
                chat_id=222,
                message_id=10,
                now=datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
            )
            schedule_reply = await gateway.handle_text(
                "/remind weight daily 09:00",
                telegram_user_id=111,
                chat_id=222,
                message_id=11,
                now=datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
            )
            list_reply = await gateway.handle_text(
                "/reminders",
                telegram_user_id=111,
                chat_id=222,
                message_id=12,
                now=datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
            )
            off_reply = await gateway.handle_text(
                "/reminder off",
                telegram_user_id=111,
                chat_id=222,
                message_id=13,
                now=datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
            )

            reminders = await ReminderStore(db).list(user_id)
            assert empty_reply == "Reminders\nNo active reminders."
            assert schedule_reply == "Scheduled daily weight reminder at 09:00 Europe/Moscow."
            assert list_reply == "Reminders\n- #1 weight daily at 09:00 Europe/Moscow"
            assert off_reply == "Turned off reminder #1."
            assert len(reminders) == 1
            assert reminders[0].enabled is False
            assert reminders[0].type == "weight"
            assert reminders[0].schedule == {"kind": "daily", "time": "09:00"}
            assert reminders[0].timezone == "Europe/Moscow"
            assert reminders[0].next_due_at == datetime(2026, 6, 14, 6, 0, tzinfo=UTC)
            assert calls == []
        finally:
            await db.close()

    run(scenario())
