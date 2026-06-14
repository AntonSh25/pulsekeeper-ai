from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pulsekeeper.storage.sqlite import Database


@dataclass(frozen=True)
class ImportRun:
    id: int
    user_id: int
    source: str
    started_at: datetime | None
    finished_at: datetime | None
    metadata: dict[str, Any] | None


@dataclass(frozen=True)
class ImportItem:
    id: int
    import_id: int
    external_id: str
    status: str
    metadata: dict[str, Any] | None


class ImportStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def start(
        self,
        *,
        user_id: int,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> ImportRun:
        cursor = await self.db.execute(
            """
            INSERT INTO imports (user_id, source, metadata_json)
            VALUES (?, ?, ?)
            """,
            (user_id, source, _optional_json_dumps(metadata)),
        )
        import_id = cursor.lastrowid
        if import_id is None:  # pragma: no cover - sqlite always returns it
            raise RuntimeError("created import row did not return an id")
        import_run = await self.get(int(import_id))
        if import_run is None:  # pragma: no cover - inserted row must exist
            raise RuntimeError("created import row could not be loaded")
        return import_run

    async def get(self, import_id: int) -> ImportRun | None:
        row = await self.db.fetchone("SELECT * FROM imports WHERE id = ?", (import_id,))
        if row is None:
            return None
        return _row_to_import(row)

    async def finish(self, import_id: int, *, finished_at: datetime | None = None) -> None:
        await self.db.execute(
            """
            UPDATE imports
            SET finished_at = ?
            WHERE id = ?
            """,
            (_datetime_to_storage(finished_at or datetime.now(UTC)), import_id),
        )

    async def upsert_item(
        self,
        *,
        import_id: int,
        external_id: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> ImportItem:
        await self.db.execute(
            """
            INSERT INTO import_items (import_id, external_id, status, metadata_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(import_id, external_id) DO UPDATE SET
                status = excluded.status,
                metadata_json = excluded.metadata_json
            """,
            (import_id, external_id, status, _optional_json_dumps(metadata)),
        )
        row = await self.db.fetchone(
            """
            SELECT * FROM import_items
            WHERE import_id = ? AND external_id = ?
            """,
            (import_id, external_id),
        )
        if row is None:  # pragma: no cover - upserted row must exist
            raise RuntimeError("upserted import item could not be loaded")
        return _row_to_item(row)

    async def list_items(self, import_id: int) -> list[ImportItem]:
        rows = await self.db.fetchall(
            """
            SELECT * FROM import_items
            WHERE import_id = ?
            ORDER BY id ASC
            """,
            (import_id,),
        )
        return [_row_to_item(row) for row in rows]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _optional_json_dumps(value: Any | None) -> str | None:
    if value is None:
        return None
    return _json_dumps(value)


def _json_loads(value: str | None) -> Any | None:
    if value is None:
        return None
    return json.loads(value)


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


def _metadata_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict) or value is None:
        return value
    return {"value": value}


def _row_to_import(row: Any) -> ImportRun:
    metadata = _json_loads(row["metadata_json"])
    return ImportRun(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        source=str(row["source"]),
        started_at=_datetime_from_storage(row["started_at"]),
        finished_at=_datetime_from_storage(row["finished_at"]),
        metadata=_metadata_dict(metadata),
    )


def _row_to_item(row: Any) -> ImportItem:
    metadata = _json_loads(row["metadata_json"])
    return ImportItem(
        id=int(row["id"]),
        import_id=int(row["import_id"]),
        external_id=str(row["external_id"]),
        status=str(row["status"]),
        metadata=_metadata_dict(metadata),
    )


__all__ = ["ImportItem", "ImportRun", "ImportStore"]
