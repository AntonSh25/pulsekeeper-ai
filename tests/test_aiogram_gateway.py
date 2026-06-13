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
