from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class MediaAttachment:
    kind: str
    provider: str
    path: Path
    content_type: str
    file_id: str
    file_unique_id: str
    created_at: datetime
    width: int | None = None
    height: int | None = None
    file_size: int | None = None


class LocalMediaStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def save_telegram_photo(
        self,
        *,
        user_id: int,
        file_unique_id: str,
        file_id: str,
        content: bytes,
        content_type: str,
        now: datetime | None = None,
        width: int | None = None,
        height: int | None = None,
        file_size: int | None = None,
    ) -> MediaAttachment:
        if not _SAFE_ID.fullmatch(file_unique_id):
            raise ValueError("unsafe Telegram file_unique_id")
        created_at = now or datetime.now(UTC)
        extension = _EXTENSION_BY_CONTENT_TYPE.get(content_type, ".bin")
        target_dir = self.root / f"user-{user_id}" / created_at.date().isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{file_unique_id}{extension}"
        path.write_bytes(content)
        return MediaAttachment(
            kind="photo",
            provider="telegram",
            path=path,
            content_type=content_type,
            file_id=file_id,
            file_unique_id=file_unique_id,
            created_at=created_at,
            width=width,
            height=height,
            file_size=file_size,
        )


__all__ = ["LocalMediaStore", "MediaAttachment"]
