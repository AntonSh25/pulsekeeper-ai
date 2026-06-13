from __future__ import annotations

import asyncio
import sqlite3

from pulsekeeper.storage import Database as ExportedDatabase
from pulsekeeper.storage import JsonlHealthLog
from pulsekeeper.storage.sqlite import Database


def run(coro):
    return asyncio.run(coro)


async def table_names(db: Database) -> set[str]:
    rows = await db.fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row["name"] for row in rows}


def test_storage_package_preserves_legacy_jsonl_health_log_import():
    assert JsonlHealthLog.__name__ == "JsonlHealthLog"


def test_storage_package_exports_database():
    assert ExportedDatabase is Database


def test_database_initializes_wal_and_initial_schema(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            journal_mode = await db.fetchval("PRAGMA journal_mode")
            assert journal_mode == "wal"

            expected_tables = {
                "users",
                "gateway_accounts",
                "health_entries",
                "health_entries_fts",
                "user_profile_facts",
                "preferences",
                "conversation_state",
                "summary_memory",
                "summary_memory_fts",
                "reminders",
                "imports",
                "import_items",
                "schema_migrations",
            }
            tables = await table_names(db)
            assert expected_tables <= tables
            assert "telegram_offsets" not in tables

            version = await db.fetchval(
                "SELECT version FROM schema_migrations WHERE version = ?",
                ("001_initial_schema",),
            )
            assert version == "001_initial_schema"
        finally:
            await db.close()

    run(scenario())


def test_database_migrations_are_idempotent(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        await db.close()

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            applied_count = await db.fetchval(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
                ("001_initial_schema",),
            )
            assert applied_count == 1
        finally:
            await db.close()

    run(scenario())


def test_database_transaction_rolls_back_on_error(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            try:
                async with db.transaction() as conn:
                    await conn.execute("INSERT INTO users DEFAULT VALUES")
                    raise RuntimeError("boom")
            except RuntimeError:
                pass

            assert await db.fetchval("SELECT COUNT(*) FROM users") == 0
        finally:
            await db.close()

    run(scenario())


def test_database_transaction_commits_on_success(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            async with db.transaction() as conn:
                await conn.execute("INSERT INTO users DEFAULT VALUES")

            assert await db.fetchval("SELECT COUNT(*) FROM users") == 1
        finally:
            await db.close()

    run(scenario())


def test_public_execute_is_guarded_during_active_transaction(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            async with db.transaction() as conn:
                await conn.execute("INSERT INTO users DEFAULT VALUES")
                assert await db.fetchval("SELECT COUNT(*) FROM users") == 1
                try:
                    await db.execute("INSERT INTO users DEFAULT VALUES")
                except RuntimeError as exc:
                    assert "active transaction" in str(exc)
                else:  # pragma: no cover - assertion path
                    raise AssertionError("execute() must be rejected during a transaction")

            assert await db.fetchval("SELECT COUNT(*) FROM users") == 1
        finally:
            await db.close()

    run(scenario())


def test_concurrent_transactions_are_serialized(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        order: list[str] = []
        try:
            async def first() -> None:
                async with db.transaction() as conn:
                    order.append("first-start")
                    await conn.execute("INSERT INTO users DEFAULT VALUES")
                    await asyncio.sleep(0.05)
                    order.append("first-end")

            async def second() -> None:
                await asyncio.sleep(0.01)
                async with db.transaction() as conn:
                    order.append("second-start")
                    await conn.execute("INSERT INTO users DEFAULT VALUES")
                    order.append("second-end")

            await asyncio.gather(first(), second())

            assert order == ["first-start", "first-end", "second-start", "second-end"]
            assert await db.fetchval("SELECT COUNT(*) FROM users") == 2
        finally:
            await db.close()

    run(scenario())


def test_foreign_keys_are_enforced(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            try:
                await db.execute(
                    """
                    INSERT INTO gateway_accounts (user_id, gateway, external_user_id)
                    VALUES (?, 'telegram', ?)
                    """,
                    (999, "missing-user"),
                )
            except sqlite3.IntegrityError:
                pass
            else:  # pragma: no cover - assertion path
                raise AssertionError("foreign key violation should fail")
        finally:
            await db.close()

    run(scenario())


def test_migration_runner_creates_schema_migrations_before_user_migrations(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_create_widget.sql").write_text(
        "CREATE TABLE IF NOT EXISTS widget (id INTEGER PRIMARY KEY);",
        encoding="utf-8",
    )

    async def scenario() -> None:
        db = Database(tmp_path / "state.db", migrations_path=migrations)
        await db.initialize()
        try:
            assert "schema_migrations" in await table_names(db)
            assert "widget" in await table_names(db)
            assert await db.fetchval(
                "SELECT version FROM schema_migrations WHERE version = ?",
                ("001_create_widget",),
            ) == "001_create_widget"
        finally:
            await db.close()

    run(scenario())


def test_failed_migration_rolls_back_schema_and_is_not_recorded(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_broken.sql").write_text(
        """
        CREATE TABLE IF NOT EXISTS should_not_persist (id INTEGER PRIMARY KEY);
        INSERT INTO definitely_missing_table (id) VALUES (1);
        """,
        encoding="utf-8",
    )

    async def scenario() -> None:
        db = Database(tmp_path / "state.db", migrations_path=migrations)
        try:
            try:
                await db.initialize()
            except sqlite3.OperationalError:
                pass
            else:  # pragma: no cover - assertion path
                raise AssertionError("broken migration should fail")

            assert "should_not_persist" not in await table_names(db)
            assert await db.fetchval(
                "SELECT version FROM schema_migrations WHERE version = ?",
                ("001_broken",),
            ) is None
        finally:
            await db.close()

    run(scenario())


def test_fts_tables_are_maintained_by_triggers(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = (await db.execute("INSERT INTO users DEFAULT VALUES")).lastrowid
            await db.execute(
                """
                INSERT INTO health_entries (
                    user_id, kind, note, logged_at, source, metadata_json
                )
                VALUES (?, 'food', ?, '2026-01-01T00:00:00Z', 'manual', ?)
                """,
                (user_id, "oatmeal breakfast", '{"meal":"breakfast"}'),
            )
            await db.execute(
                """
                INSERT INTO summary_memory (user_id, period_start, period_end, kind, text)
                VALUES (?, '2026-01-01', '2026-01-02', 'daily', 'ate oatmeal')
                """,
                (user_id,),
            )

            assert await db.fetchval(
                "SELECT COUNT(*) FROM health_entries_fts WHERE health_entries_fts MATCH 'oatmeal'"
            ) == 1
            assert await db.fetchval(
                "SELECT COUNT(*) FROM summary_memory_fts WHERE summary_memory_fts MATCH 'oatmeal'"
            ) == 1
        finally:
            await db.close()

    run(scenario())


def test_migration_file_has_no_non_idempotent_plain_create_table():
    migration_sql = sqlite3.connect(":memory:")
    migration_sql.close()
    text = (Database.default_migrations_path() / "001_initial_schema.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE " not in text.replace("CREATE TABLE IF NOT EXISTS", "")
