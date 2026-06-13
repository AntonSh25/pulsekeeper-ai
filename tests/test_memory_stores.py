from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

from pulsekeeper.domain import SummaryMemoryDraft
from pulsekeeper.storage.memory import (
    ConversationStateStore,
    PreferenceStore,
    ProfileStore,
    SummaryMemoryStore,
)
from pulsekeeper.storage.sqlite import Database


def run(coro):
    return asyncio.run(coro)


async def create_user(db: Database) -> int:
    cursor = await db.execute("INSERT INTO users DEFAULT VALUES")
    user_id = cursor.lastrowid
    assert user_id is not None
    return user_id


def test_profile_store_upserts_json_facts_and_timezone_is_user_scoped(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            other_user_id = await create_user(db)
            store = ProfileStore(db)

            await store.set_fact(user_id, "timezone", "Europe/Moscow", source="telegram")
            await store.set_fact(
                user_id,
                "goal",
                {"goal_type": "lose", "flags": ["clinical_supervision"]},
                source="onboarding",
            )
            await store.set_fact(other_user_id, "timezone", "UTC", source="telegram")
            await store.set_fact(user_id, "timezone", "Asia/Tbilisi", source="correction")

            assert await store.get_fact(user_id, "timezone") == "Asia/Tbilisi"
            assert await store.get_timezone(user_id) == "Asia/Tbilisi"
            assert await store.get_timezone(other_user_id) == "UTC"
            assert await store.get_fact(user_id, "goal") == {
                "flags": ["clinical_supervision"],
                "goal_type": "lose",
            }
            assert await store.get_fact(user_id, "missing") is None

            rows = await db.fetchall(
                """
                SELECT key, value_json, source, confidence FROM user_profile_facts
                WHERE user_id = ?
                """,
                (user_id,),
            )
            assert len(rows) == 2
            timezone_row = next(row for row in rows if row["key"] == "timezone")
            assert timezone_row["value_json"] == '"Asia/Tbilisi"'
            assert timezone_row["source"] == "correction"
            assert timezone_row["confidence"] == 1.0
        finally:
            await db.close()

    run(scenario())


def test_preference_store_round_trips_values_and_lists_user_preferences(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            other_user_id = await create_user(db)
            store = PreferenceStore(db)

            await store.set(user_id, "language", "ru")
            await store.set(user_id, "summary", {"style": "concise", "sections": ["sleep", "food"]})
            await store.set(user_id, "notifications", False)
            await store.set(other_user_id, "language", "en")
            await store.set(user_id, "language", "en")

            assert await store.get(user_id, "language") == "en"
            assert await store.get(user_id, "summary") == {
                "sections": ["sleep", "food"],
                "style": "concise",
            }
            assert await store.get(user_id, "notifications") is False
            assert await store.get(user_id, "missing") is None
            assert await store.list(user_id) == {
                "language": "en",
                "notifications": False,
                "summary": {"sections": ["sleep", "food"], "style": "concise"},
            }
        finally:
            await db.close()

    run(scenario())


def test_conversation_state_store_expires_state_with_injectable_clock_and_is_scoped(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)

        def now_factory() -> datetime:
            return now

        try:
            user_id = await create_user(db)
            other_user_id = await create_user(db)
            store = ConversationStateStore(db, now_factory=now_factory)

            await store.put(
                user_id,
                "correction",
                {"entry_id": 10, "fields": ["value"]},
                ttl_seconds=60,
            )
            await store.put(other_user_id, "correction", {"entry_id": 99}, ttl_seconds=60)
            assert await store.get(user_id, "correction") == {"entry_id": 10, "fields": ["value"]}
            assert await store.get(other_user_id, "correction") == {"entry_id": 99}

            now = datetime(2026, 6, 13, 12, 1, 1, tzinfo=UTC)
            assert await store.get(user_id, "correction") is None
            assert await store.get(other_user_id, "correction") is None

            now = datetime(2026, 6, 13, 12, 2, tzinfo=UTC)
            await store.put(user_id, "clarification", {"question": "when?"}, ttl_seconds=0)
            assert await store.get(user_id, "clarification") is None
        finally:
            await db.close()

    run(scenario())


def test_summary_memory_store_writes_and_searches_fts_user_scoped_with_safe_queries(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            other_user_id = await create_user(db)
            store = SummaryMemoryStore(db)

            await store.write(
                user_id,
                SummaryMemoryDraft(
                    period_start=date(2026, 6, 1),
                    period_end=date(2026, 6, 7),
                    kind="weekly",
                    text="Weight trend decreased about 0.3 kg while running stayed consistent.",
                    metadata={"confidence": "medium", "tags": ["weight", "running"]},
                ),
            )
            await store.write(
                user_id,
                SummaryMemoryDraft(
                    period_start=date(2026, 6, 8),
                    period_end=date(2026, 6, 14),
                    kind="weekly",
                    text="Sleep improved after earlier dinners.",
                    metadata=None,
                ),
            )
            await store.write(
                other_user_id,
                SummaryMemoryDraft(
                    period_start=date(2026, 6, 1),
                    period_end=date(2026, 6, 7),
                    kind="weekly",
                    text="Weight trend for another user.",
                ),
            )

            results = await store.search(user_id, "weight trend", limit=10)
            assert len(results) == 1
            assert results[0].user_id == user_id
            assert results[0].period_start == date(2026, 6, 1)
            assert results[0].period_end == date(2026, 6, 7)
            assert results[0].kind == "weekly"
            assert "Weight trend" in results[0].text
            assert results[0].metadata == {"confidence": "medium", "tags": ["weight", "running"]}
            assert results[0].created_at is not None
            assert results[0].updated_at is not None

            safe_results = await store.search(user_id, 'weight OR trend " broken', limit=1)
            assert len(safe_results) == 1
            assert await store.search(user_id, " ? - ") == []
            assert await store.search(user_id, "sleep", limit=0) == []
        finally:
            await db.close()

    run(scenario())
