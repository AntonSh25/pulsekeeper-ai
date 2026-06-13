from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from sqlite3 import Row
from typing import Any

from pulsekeeper.domain import HealthEntry, HealthEntryDraft, HealthEntryKind, HealthEntryPatch
from pulsekeeper.storage.sqlite import Database


class HealthEntryStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def append(self, user_id: int, entry: HealthEntryDraft) -> HealthEntry:
        metadata_json = _metadata_to_json(entry.metadata)
        async with self.db.transaction() as conn:
            async with conn.execute(
                """
                INSERT INTO health_entries (
                    user_id, kind, note, value, unit, logged_at, source,
                    metadata_json, schema_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    entry.kind,
                    entry.note,
                    entry.value,
                    entry.unit,
                    _datetime_to_storage(entry.logged_at),
                    entry.source,
                    metadata_json,
                    entry.schema_version,
                ),
            ) as cursor:
                row_id = cursor.lastrowid
            async with conn.execute(
                "SELECT * FROM health_entries WHERE id = ?",
                (row_id,),
            ) as select_cursor:
                row = await select_cursor.fetchone()
        if row is None:  # pragma: no cover - defensive guard
            raise RuntimeError("inserted health entry could not be loaded")
        return _row_to_health_entry(row)

    async def list(
        self,
        user_id: int,
        *,
        start: datetime,
        end: datetime,
        kinds: list[HealthEntryKind] | None = None,
    ) -> list[HealthEntry]:
        parameters: list[Any] = [
            user_id,
            _datetime_to_storage(start),
            _datetime_to_storage(end),
        ]
        where = [
            "user_id = ?",
            "deleted_at IS NULL",
            "logged_at >= ?",
            "logged_at < ?",
        ]
        if kinds:
            placeholders = ", ".join("?" for _ in kinds)
            where.append(f"kind IN ({placeholders})")
            parameters.extend(kinds)

        rows = await self.db.fetchall(
            f"""
            SELECT * FROM health_entries
            WHERE {" AND ".join(where)}
            ORDER BY logged_at ASC, id ASC
            """,
            parameters,
        )
        return [_row_to_health_entry(row) for row in rows]

    async def get_last(
        self,
        user_id: int,
        *,
        kind: HealthEntryKind | None = None,
    ) -> HealthEntry | None:
        where = ["user_id = ?", "deleted_at IS NULL"]
        parameters: list[Any] = [user_id]
        if kind is not None:
            where.append("kind = ?")
            parameters.append(kind)

        row = await self.db.fetchone(
            f"""
            SELECT * FROM health_entries
            WHERE {" AND ".join(where)}
            ORDER BY logged_at DESC, id DESC
            LIMIT 1
            """,
            parameters,
        )
        if row is None:
            return None
        return _row_to_health_entry(row)

    async def update(self, entry_id: int, patch: HealthEntryPatch) -> HealthEntry:
        explicit_fields = _explicit_patch_fields(patch)
        assignments: list[str] = []
        parameters: list[Any] = []
        for field_name in explicit_fields:
            column_name = _PATCH_FIELD_COLUMNS[field_name]
            value = getattr(patch, field_name)
            if field_name == "logged_at" and value is not None:
                value = _datetime_to_storage(value)
            elif field_name == "metadata":
                value = _metadata_to_json(value)
            assignments.append(f"{column_name} = ?")
            parameters.append(value)

        updated_at = _datetime_to_storage(datetime.now(UTC))
        assignments.append("updated_at = ?")
        parameters.extend([updated_at, entry_id])

        async with self.db.transaction() as conn:
            async with conn.execute(
                "SELECT * FROM health_entries WHERE id = ? AND deleted_at IS NULL",
                (entry_id,),
            ) as select_cursor:
                existing = await select_cursor.fetchone()
            if existing is None:
                raise LookupError(f"health entry {entry_id} does not exist or was deleted")

            await conn.execute(
                f"""
                UPDATE health_entries
                SET {", ".join(assignments)}
                WHERE id = ?
                """,
                parameters,
            )
            async with conn.execute(
                "SELECT * FROM health_entries WHERE id = ?",
                (entry_id,),
            ) as updated_cursor:
                row = await updated_cursor.fetchone()

        if row is None:  # pragma: no cover - defensive guard
            raise RuntimeError("updated health entry could not be loaded")
        return _row_to_health_entry(row)

    async def soft_delete(self, entry_id: int) -> None:
        deleted_at = _datetime_to_storage(datetime.now(UTC))
        async with self.db.transaction() as conn:
            async with conn.execute(
                "SELECT deleted_at FROM health_entries WHERE id = ?",
                (entry_id,),
            ) as select_cursor:
                row = await select_cursor.fetchone()
            if row is None:
                raise LookupError(f"health entry {entry_id} does not exist")
            if row["deleted_at"] is not None:
                return

            await conn.execute(
                """
                UPDATE health_entries
                SET deleted_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (deleted_at, deleted_at, entry_id),
            )

    async def search(self, user_id: int, query: str, *, limit: int = 20) -> list[HealthEntry]:
        fts_query = _to_safe_fts_query(query)
        if fts_query is None or limit <= 0:
            return []

        rows = await self.db.fetchall(
            """
            SELECT e.*
            FROM health_entries_fts
            JOIN health_entries AS e ON e.id = health_entries_fts.rowid
            WHERE health_entries_fts MATCH ?
              AND e.user_id = ?
              AND e.deleted_at IS NULL
            ORDER BY bm25(health_entries_fts), e.logged_at DESC, e.id DESC
            LIMIT ?
            """,
            (fts_query, user_id, limit),
        )
        return [_row_to_health_entry(row) for row in rows]


def _metadata_to_json(metadata: dict[str, Any] | None) -> str | None:
    if metadata is None:
        return None
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _metadata_from_json(metadata_json: str | None) -> dict[str, Any] | None:
    if metadata_json is None:
        return None
    loaded = json.loads(metadata_json)
    if not isinstance(loaded, dict):
        raise ValueError("health entry metadata_json must decode to an object")
    return loaded


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


_PATCH_FIELD_COLUMNS = {
    "kind": "kind",
    "note": "note",
    "logged_at": "logged_at",
    "value": "value",
    "unit": "unit",
    "source": "source",
    "metadata": "metadata_json",
    "schema_version": "schema_version",
}


def _explicit_patch_fields(patch: HealthEntryPatch) -> list[str]:
    fields_set = patch.model_fields_set
    return [field_name for field_name in _PATCH_FIELD_COLUMNS if field_name in fields_set]


def _datetime_to_storage(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _datetime_from_storage(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _row_to_health_entry(row: Row) -> HealthEntry:
    logged_at = _datetime_from_storage(row["logged_at"])
    if logged_at is None:  # pragma: no cover - schema enforces NOT NULL
        raise ValueError("health entry logged_at is required")
    return HealthEntry(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        note=row["note"],
        value=row["value"],
        unit=row["unit"],
        logged_at=logged_at,
        source=row["source"],
        metadata=_metadata_from_json(row["metadata_json"]),
        schema_version=row["schema_version"],
        created_at=_datetime_from_storage(row["created_at"]),
        updated_at=_datetime_from_storage(row["updated_at"]),
        deleted_at=_datetime_from_storage(row["deleted_at"]),
    )


__all__ = ["HealthEntryStore"]
