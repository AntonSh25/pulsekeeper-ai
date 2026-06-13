from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from sqlite3 import Row
from typing import Any

from pulsekeeper.domain import SummaryMemory, SummaryMemoryDraft
from pulsekeeper.storage.sqlite import Database


class ProfileStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_fact(self, user_id: int, key: str) -> Any | None:
        row = await self.db.fetchone(
            """
            SELECT value_json FROM user_profile_facts
            WHERE user_id = ? AND key = ?
            """,
            (user_id, key),
        )
        if row is None:
            return None
        return _json_loads(row["value_json"])

    async def set_fact(self, user_id: int, key: str, value: Any, *, source: str) -> None:
        value_json = _json_dumps(value)
        updated_at = _datetime_to_storage(datetime.now(UTC))
        async with self.db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO user_profile_facts (
                    user_id, key, value_json, confidence, source, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value_json = excluded.value_json,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (user_id, key, value_json, 1.0, source, updated_at),
            )

    async def get_timezone(self, user_id: int) -> str | None:
        value = await self.get_fact(user_id, "timezone")
        if isinstance(value, str):
            return value
        return None


class PreferenceStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get(self, user_id: int, key: str) -> Any | None:
        row = await self.db.fetchone(
            """
            SELECT value_json FROM preferences
            WHERE user_id = ? AND key = ?
            """,
            (user_id, key),
        )
        if row is None:
            return None
        return _json_loads(row["value_json"])

    async def set(self, user_id: int, key: str, value: Any) -> None:
        value_json = _json_dumps(value)
        updated_at = _datetime_to_storage(datetime.now(UTC))
        async with self.db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO preferences (user_id, key, value_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, key, value_json, updated_at),
            )

    async def list(self, user_id: int) -> dict[str, Any]:
        rows = await self.db.fetchall(
            """
            SELECT key, value_json FROM preferences
            WHERE user_id = ?
            ORDER BY key ASC
            """,
            (user_id,),
        )
        return {row["key"]: _json_loads(row["value_json"]) for row in rows}


class ConversationStateStore:
    def __init__(self, db: Database, *, now_factory: Callable[[], datetime] | None = None) -> None:
        self.db = db
        self.now_factory = now_factory or (lambda: datetime.now(UTC))

    async def put(
        self,
        user_id: int,
        state_type: str,
        payload: dict[str, Any],
        *,
        ttl_seconds: int,
    ) -> None:
        now = _ensure_aware_datetime(self.now_factory())
        expires_at = now + timedelta(seconds=ttl_seconds)
        payload_json = _json_dumps(payload)
        updated_at = _datetime_to_storage(now)
        async with self.db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO conversation_state (
                    user_id, state_type, payload_json, expires_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, state_type) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (user_id, state_type, payload_json, _datetime_to_storage(expires_at), updated_at),
            )

    async def get(self, user_id: int, state_type: str) -> dict[str, Any] | None:
        row = await self.db.fetchone(
            """
            SELECT payload_json, expires_at FROM conversation_state
            WHERE user_id = ? AND state_type = ?
            """,
            (user_id, state_type),
        )
        if row is None:
            return None

        expires_at = _datetime_from_storage(row["expires_at"])
        if expires_at is not None and expires_at <= _ensure_aware_datetime(self.now_factory()):
            return None

        payload = _json_loads(row["payload_json"])
        if not isinstance(payload, dict):
            raise ValueError("conversation state payload_json must decode to an object")
        return payload


class SummaryMemoryStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def write(self, user_id: int, item: SummaryMemoryDraft) -> None:
        async with self.db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO summary_memory (
                    user_id, period_start, period_end, kind, text, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    _date_to_storage(item.period_start),
                    _date_to_storage(item.period_end),
                    item.kind,
                    item.text,
                    _optional_json_dumps(item.metadata),
                ),
            )

    async def search(self, user_id: int, query: str, *, limit: int = 10) -> list[SummaryMemory]:
        fts_query = _to_safe_fts_query(query)
        if fts_query is None or limit <= 0:
            return []

        rows = await self.db.fetchall(
            """
            SELECT m.*
            FROM summary_memory_fts
            JOIN summary_memory AS m ON m.id = summary_memory_fts.rowid
            WHERE summary_memory_fts MATCH ?
              AND m.user_id = ?
            ORDER BY bm25(summary_memory_fts), m.period_end DESC, m.id DESC
            LIMIT ?
            """,
            (fts_query, user_id, limit),
        )
        return [_row_to_summary_memory(row) for row in rows]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _optional_json_dumps(value: Any | None) -> str | None:
    if value is None:
        return None
    return _json_dumps(value)


def _json_loads(value: str) -> Any:
    return json.loads(value)


_FTS_TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_FTS_OPERATORS = {"AND", "OR", "NOT", "NEAR"}


def _to_safe_fts_query(query: str) -> str | None:
    tokens = [
        token
        for token in _FTS_TOKEN_PATTERN.findall(query)
        if token.upper() not in _FTS_OPERATORS
    ]
    if not tokens:
        return None
    quoted_tokens = [f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens]
    return " OR ".join(quoted_tokens)


def _ensure_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


def _datetime_to_storage(value: datetime) -> str:
    return _ensure_aware_datetime(value).astimezone(UTC).isoformat()


def _datetime_from_storage(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _ensure_aware_datetime(parsed)


def _date_to_storage(value: date) -> str:
    return value.isoformat()


def _date_from_storage(value: str) -> date:
    return date.fromisoformat(value)


def _row_to_summary_memory(row: Row) -> SummaryMemory:
    metadata_json = row["metadata_json"]
    metadata = None if metadata_json is None else _json_loads(metadata_json)
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("summary memory metadata_json must decode to an object")
    return SummaryMemory(
        id=row["id"],
        user_id=row["user_id"],
        period_start=_date_from_storage(row["period_start"]),
        period_end=_date_from_storage(row["period_end"]),
        kind=row["kind"],
        text=row["text"],
        metadata=metadata,
        created_at=_datetime_from_storage(row["created_at"]),
        updated_at=_datetime_from_storage(row["updated_at"]),
    )


__all__ = [
    "ConversationStateStore",
    "PreferenceStore",
    "ProfileStore",
    "SummaryMemoryStore",
]
