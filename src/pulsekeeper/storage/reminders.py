from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pulsekeeper.storage.sqlite import Database


@dataclass(frozen=True)
class Reminder:
    id: int
    user_id: int
    type: str
    schedule: dict[str, Any]
    timezone: str
    enabled: bool
    last_sent_at: datetime | None
    next_due_at: datetime | None


class ReminderStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(
        self,
        *,
        user_id: int,
        type: str,
        schedule: dict[str, Any],
        timezone: str,
        next_due_at: datetime | None = None,
    ) -> Reminder:
        cursor = await self.db.execute(
            """
            INSERT INTO reminders (user_id, type, schedule_json, timezone, next_due_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                type,
                _json_dumps(schedule),
                timezone,
                _datetime_to_storage(next_due_at),
            ),
        )
        reminder_id = cursor.lastrowid
        if reminder_id is None:  # pragma: no cover - sqlite always returns it
            raise RuntimeError("created reminder row did not return an id")
        reminder = await self.get(int(reminder_id))
        if reminder is None:  # pragma: no cover - inserted row must exist
            raise RuntimeError("created reminder row could not be loaded")
        return reminder

    async def get(self, reminder_id: int) -> Reminder | None:
        row = await self.db.fetchone("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        if row is None:
            return None
        return _row_to_reminder(row)

    async def list(self, user_id: int) -> list[Reminder]:
        rows = await self.db.fetchall(
            """
            SELECT * FROM reminders
            WHERE user_id = ?
            ORDER BY enabled DESC, next_due_at ASC, id ASC
            """,
            (user_id,),
        )
        return [_row_to_reminder(row) for row in rows]

    async def due(self, *, now: datetime) -> list[Reminder]:
        rows = await self.db.fetchall(
            """
            SELECT * FROM reminders
            WHERE enabled = 1
              AND next_due_at IS NOT NULL
              AND next_due_at <= ?
            ORDER BY next_due_at ASC, id ASC
            """,
            (_datetime_to_storage(now),),
        )
        return [_row_to_reminder(row) for row in rows]

    async def mark_sent(
        self,
        reminder_id: int,
        *,
        sent_at: datetime,
        next_due_at: datetime | None,
    ) -> None:
        await self.db.execute(
            """
            UPDATE reminders
            SET last_sent_at = ?, next_due_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (_datetime_to_storage(sent_at), _datetime_to_storage(next_due_at), reminder_id),
        )

    async def disable(self, reminder_id: int) -> None:
        await self.db.execute(
            """
            UPDATE reminders
            SET enabled = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (reminder_id,),
        )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str) -> Any:
    return json.loads(value)


def _ensure_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


def _datetime_to_storage(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_aware_datetime(value).astimezone(UTC).isoformat()


def _datetime_from_storage(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _ensure_aware_datetime(parsed)


def _row_to_reminder(row: Any) -> Reminder:
    return Reminder(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        type=str(row["type"]),
        schedule=_json_loads(row["schedule_json"]),
        timezone=str(row["timezone"]),
        enabled=bool(row["enabled"]),
        last_sent_at=_datetime_from_storage(row["last_sent_at"]),
        next_due_at=_datetime_from_storage(row["next_due_at"]),
    )


__all__ = ["Reminder", "ReminderStore"]
