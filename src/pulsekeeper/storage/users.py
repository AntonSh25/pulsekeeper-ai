from __future__ import annotations

from typing import Literal

from pulsekeeper.storage.sqlite import Database

GatewayName = Literal["telegram"]


class UserStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def resolve_gateway_user(
        self,
        *,
        gateway: GatewayName,
        external_user_id: str,
        external_chat_id: str | None = None,
    ) -> int:
        async with self.db.transaction() as conn:
            async with conn.execute(
                """
                SELECT user_id
                FROM gateway_accounts
                WHERE gateway = ? AND external_user_id = ?
                """,
                (gateway, external_user_id),
            ) as existing_cursor:
                existing = await existing_cursor.fetchone()

            if existing is not None:
                await conn.execute(
                    """
                    UPDATE gateway_accounts
                    SET external_chat_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE gateway = ? AND external_user_id = ?
                    """,
                    (external_chat_id, gateway, external_user_id),
                )
                return int(existing["user_id"])

            async with conn.execute("INSERT INTO users DEFAULT VALUES") as cursor:
                user_id = cursor.lastrowid
            if user_id is None:  # pragma: no cover - sqlite always returns this
                raise RuntimeError("created user row did not return an id")

            await conn.execute(
                """
                INSERT INTO gateway_accounts (
                    user_id, gateway, external_user_id, external_chat_id
                )
                VALUES (?, ?, ?, ?)
                """,
                (user_id, gateway, external_user_id, external_chat_id),
            )
            return int(user_id)


class GatewayStateStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_telegram_offset(self, bot_profile: str) -> int | None:
        row = await self.db.fetchone(
            """
            SELECT offset
            FROM telegram_offsets
            WHERE bot_profile = ?
            """,
            (bot_profile,),
        )
        if row is None:
            return None
        return int(row["offset"])

    async def set_telegram_offset(self, bot_profile: str, offset: int) -> None:
        await self.db.execute(
            """
            INSERT INTO telegram_offsets (bot_profile, offset, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(bot_profile) DO UPDATE SET
                offset = excluded.offset,
                updated_at = excluded.updated_at
            """,
            (bot_profile, offset),
        )


__all__ = ["GatewayName", "GatewayStateStore", "UserStore"]
