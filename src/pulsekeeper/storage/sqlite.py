from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from sqlite3 import Row
from typing import Any

import aiosqlite


class Database:
    """Async SQLite database handle with explicit, idempotent migrations."""

    def __init__(self, path: str | Path, *, migrations_path: str | Path | None = None) -> None:
        self.path = Path(path)
        self.migrations_path = (
            Path(migrations_path) if migrations_path else self.default_migrations_path()
        )
        self._conn: aiosqlite.Connection | None = None
        self._transaction_lock = asyncio.Lock()
        self._transaction_active = False

    @classmethod
    def default_migrations_path(cls) -> Path:
        return Path(__file__).resolve().parent.parent / "migrations"

    async def initialize(self) -> None:
        await self.connect()
        await self._enable_wal()
        await self.apply_migrations()

    async def connect(self) -> aiosqlite.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(self.path)
            conn.row_factory = Row
            await conn.execute("PRAGMA foreign_keys = ON")
            self._conn = conn
        return self._conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, parameters: Sequence[Any] = ()) -> aiosqlite.Cursor:
        if self._transaction_active:
            raise RuntimeError(
                "execute() cannot be used while an active transaction is in progress; "
                "use the transaction connection instead"
            )
        conn = await self.connect()
        cursor = await conn.execute(sql, parameters)
        await conn.commit()
        return cursor

    async def fetchall(self, sql: str, parameters: Sequence[Any] = ()) -> list[Row]:
        conn = await self.connect()
        async with conn.execute(sql, parameters) as cursor:
            return await cursor.fetchall()

    async def fetchone(self, sql: str, parameters: Sequence[Any] = ()) -> Row | None:
        conn = await self.connect()
        async with conn.execute(sql, parameters) as cursor:
            return await cursor.fetchone()

    async def fetchval(self, sql: str, parameters: Sequence[Any] = ()) -> Any:
        row = await self.fetchone(sql, parameters)
        if row is None:
            return None
        return row[0]

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._transaction_lock:
            conn = await self.connect()
            await conn.execute("BEGIN")
            self._transaction_active = True
            try:
                yield conn
            except Exception:
                await conn.rollback()
                raise
            else:
                await conn.commit()
            finally:
                self._transaction_active = False

    async def apply_migrations(self) -> None:
        await self._ensure_schema_migrations_table()
        for migration_file in sorted(self.migrations_path.glob("*.sql")):
            version = migration_file.stem
            if await self._migration_applied(version):
                continue
            sql = migration_file.read_text(encoding="utf-8")
            async with self.transaction() as conn:
                for statement in self._split_sql_statements(sql):
                    await conn.execute(statement)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)",
                    (version,),
                )

    async def _migration_applied(self, version: str) -> bool:
        conn = await self.connect()
        schema_table_exists = await self.fetchval(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        )
        if schema_table_exists is None:
            return False
        async with conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?",
            (version,),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def _ensure_schema_migrations_table(self) -> None:
        conn = await self.connect()
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.commit()

    @staticmethod
    def _split_sql_statements(sql: str) -> list[str]:
        statements: list[str] = []
        pending: list[str] = []
        for line in sql.splitlines():
            pending.append(line)
            candidate = "\n".join(pending).strip()
            if not candidate:
                pending.clear()
                continue
            if sqlite3.complete_statement(candidate):
                statements.append(candidate)
                pending.clear()

        remainder = "\n".join(pending).strip()
        if remainder:
            statements.append(remainder)
        return statements

    async def _enable_wal(self) -> None:
        conn = await self.connect()
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA synchronous = NORMAL")
        await conn.commit()


__all__ = ["Database"]
