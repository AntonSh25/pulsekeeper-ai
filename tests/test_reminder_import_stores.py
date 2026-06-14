from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from pulsekeeper.storage.sqlite import Database


def run(coro):
    return asyncio.run(coro)


async def create_user(db: Database) -> int:
    cursor = await db.execute("INSERT INTO users DEFAULT VALUES")
    user_id = cursor.lastrowid
    assert user_id is not None
    return user_id


def test_reminder_store_can_create_list_disable_and_find_due(tmp_path):
    async def scenario() -> None:
        from pulsekeeper.storage.reminders import ReminderStore

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            store = ReminderStore(db)
            due_at = datetime(2026, 6, 14, 6, 0, tzinfo=UTC)

            reminder = await store.create(
                user_id=user_id,
                type="weight",
                schedule={"kind": "daily", "time": "09:00"},
                timezone="Europe/Moscow",
                next_due_at=due_at,
            )
            assert reminder.id is not None
            assert reminder.enabled is True

            listed = await store.list(user_id)
            assert [item.id for item in listed] == [reminder.id]
            assert listed[0].schedule == {"kind": "daily", "time": "09:00"}

            due = await store.due(now=due_at)
            assert [item.id for item in due] == [reminder.id]

            await store.disable(reminder.id)
            assert await store.due(now=due_at) == []
        finally:
            await db.close()

    run(scenario())


def test_import_store_tracks_import_items_idempotently(tmp_path):
    async def scenario() -> None:
        from pulsekeeper.storage.imports import ImportStore

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            store = ImportStore(db)

            import_run = await store.start(
                user_id=user_id,
                source="apple_health",
                metadata={"file": "export.xml"},
            )
            await store.upsert_item(
                import_id=import_run.id,
                external_id="apple-weight-1",
                status="imported",
                metadata={"kind": "weight"},
            )
            await store.upsert_item(
                import_id=import_run.id,
                external_id="apple-weight-1",
                status="skipped",
                metadata={"reason": "duplicate"},
            )

            items = await store.list_items(import_run.id)
            assert len(items) == 1
            assert items[0].external_id == "apple-weight-1"
            assert items[0].status == "skipped"
            assert items[0].metadata == {"reason": "duplicate"}

            await store.finish(import_run.id)
            finished = await store.get(import_run.id)
            assert finished is not None
            assert finished.finished_at is not None
        finally:
            await db.close()

    run(scenario())
