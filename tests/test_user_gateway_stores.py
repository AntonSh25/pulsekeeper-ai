from __future__ import annotations

import asyncio

from pulsekeeper.storage.sqlite import Database
from pulsekeeper.storage.users import GatewayStateStore, UserStore


def run(coro):
    return asyncio.run(coro)


def test_user_store_resolves_same_gateway_account_and_updates_chat_id(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            users = UserStore(db)

            first_user_id = await users.resolve_gateway_user(
                gateway="telegram",
                external_user_id="111",
                external_chat_id="222",
            )
            second_user_id = await users.resolve_gateway_user(
                gateway="telegram",
                external_user_id="111",
                external_chat_id="333",
            )

            assert second_user_id == first_user_id
            assert await db.fetchval("SELECT COUNT(*) FROM users") == 1
            row = await db.fetchone(
                "SELECT * FROM gateway_accounts WHERE user_id = ?",
                (first_user_id,),
            )
            assert row is not None
            assert row["gateway"] == "telegram"
            assert row["external_user_id"] == "111"
            assert row["external_chat_id"] == "333"
        finally:
            await db.close()

    run(scenario())


def test_user_store_creates_distinct_users_for_distinct_gateway_accounts(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            users = UserStore(db)

            first_user_id = await users.resolve_gateway_user(
                gateway="telegram",
                external_user_id="111",
                external_chat_id="222",
            )
            second_user_id = await users.resolve_gateway_user(
                gateway="telegram",
                external_user_id="999",
                external_chat_id="888",
            )

            assert second_user_id != first_user_id
            assert await db.fetchval("SELECT COUNT(*) FROM users") == 2
            assert await db.fetchval("SELECT COUNT(*) FROM gateway_accounts") == 2
        finally:
            await db.close()

    run(scenario())


def test_gateway_state_store_persists_offsets_per_bot_profile(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            state = GatewayStateStore(db)

            assert await state.get_telegram_offset("default") is None

            await state.set_telegram_offset("default", 10)
            await state.set_telegram_offset("staging", 100)
            await state.set_telegram_offset("default", 12)

            assert await state.get_telegram_offset("default") == 12
            assert await state.get_telegram_offset("staging") == 100
            assert await db.fetchval("SELECT COUNT(*) FROM telegram_offsets") == 2
        finally:
            await db.close()

    run(scenario())
