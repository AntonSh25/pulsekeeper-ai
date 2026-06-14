from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from pulsekeeper.storage.sqlite import Database


def run(coro):
    return asyncio.run(coro)


async def create_telegram_user(
    db: Database,
    *,
    external_user_id: str = "111",
    chat_id: str = "222",
) -> int:
    from pulsekeeper.storage.users import UserStore

    return await UserStore(db).resolve_gateway_user(
        gateway="telegram",
        external_user_id=external_user_id,
        external_chat_id=chat_id,
    )


def test_scheduler_sends_due_daily_reminder_and_advances_to_next_local_day(tmp_path):
    async def scenario() -> None:
        from pulsekeeper.reminder_scheduler import TelegramReminderScheduler
        from pulsekeeper.storage.reminders import ReminderStore

        sent: list[tuple[int, str]] = []
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_telegram_user(db)
            store = ReminderStore(db)
            reminder = await store.create(
                user_id=user_id,
                type="weight",
                schedule={"kind": "daily", "time": "09:00"},
                timezone="Europe/Moscow",
                next_due_at=datetime(2026, 6, 14, 6, 0, tzinfo=UTC),
            )

            scheduler = TelegramReminderScheduler(
                db=db,
                send_message=lambda chat_id, text: sent.append((chat_id, text)),
            )
            await scheduler.process_due(now=datetime(2026, 6, 14, 6, 0, tzinfo=UTC))

            updated = await store.get(reminder.id)
            assert sent == [(222, "Reminder: weight")]
            assert updated is not None
            assert updated.last_sent_at == datetime(2026, 6, 14, 6, 0, tzinfo=UTC)
            assert updated.next_due_at == datetime(2026, 6, 15, 6, 0, tzinfo=UTC)
        finally:
            await db.close()

    run(scenario())


def test_scheduler_after_downtime_sends_once_and_skips_missed_daily_occurrences(tmp_path):
    async def scenario() -> None:
        from pulsekeeper.reminder_scheduler import TelegramReminderScheduler
        from pulsekeeper.storage.reminders import ReminderStore

        sent: list[tuple[int, str]] = []
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_telegram_user(db)
            store = ReminderStore(db)
            reminder = await store.create(
                user_id=user_id,
                type="journal",
                schedule={"kind": "daily", "time": "21:30"},
                timezone="Europe/Moscow",
                next_due_at=datetime(2026, 6, 10, 18, 30, tzinfo=UTC),
            )

            scheduler = TelegramReminderScheduler(
                db=db,
                send_message=lambda chat_id, text: sent.append((chat_id, text)),
            )
            await scheduler.process_due(now=datetime(2026, 6, 14, 20, 0, tzinfo=UTC))

            updated = await store.get(reminder.id)
            assert sent == [(222, "Reminder: journal")]
            assert updated is not None
            assert updated.next_due_at == datetime(2026, 6, 15, 18, 30, tzinfo=UTC)
        finally:
            await db.close()

    run(scenario())


def test_scheduler_loop_runs_bounded_iterations_and_sleeps_between_checks():
    async def scenario() -> None:
        from pulsekeeper.reminder_scheduler import run_scheduler_loop

        processed_at: list[datetime] = []
        sleeps: list[float] = []

        async def process_due(*, now: datetime) -> int:
            processed_at.append(now)
            return 0

        await run_scheduler_loop(
            process_due=process_due,
            now=lambda: datetime(2026, 6, 14, 6, 0, tzinfo=UTC),
            max_iterations=2,
            interval_seconds=30,
            sleep=lambda seconds: sleeps.append(seconds),
        )

        assert processed_at == [
            datetime(2026, 6, 14, 6, 0, tzinfo=UTC),
            datetime(2026, 6, 14, 6, 0, tzinfo=UTC),
        ]
        assert sleeps == [30]

    run(scenario())
