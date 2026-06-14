from __future__ import annotations

from datetime import UTC, datetime


def test_local_media_store_saves_telegram_photo_under_user_directory(tmp_path):
    from pulsekeeper.storage.media import LocalMediaStore

    store = LocalMediaStore(tmp_path / "media")
    saved = store.save_telegram_photo(
        user_id=42,
        file_unique_id="abc-123",
        file_id="telegram-file-id",
        content=b"fake image bytes",
        content_type="image/jpeg",
        now=datetime(2026, 6, 14, 8, 30, tzinfo=UTC),
    )

    assert saved.kind == "photo"
    assert saved.provider == "telegram"
    assert saved.content_type == "image/jpeg"
    assert saved.file_id == "telegram-file-id"
    assert saved.file_unique_id == "abc-123"
    assert saved.path == tmp_path / "media" / "user-42" / "2026-06-14" / "abc-123.jpg"
    assert saved.path.read_bytes() == b"fake image bytes"


def test_local_media_store_rejects_path_like_unique_ids(tmp_path):
    from pulsekeeper.storage.media import LocalMediaStore

    store = LocalMediaStore(tmp_path / "media")
    try:
        store.save_telegram_photo(
            user_id=42,
            file_unique_id="../secret",
            file_id="telegram-file-id",
            content=b"fake image bytes",
            content_type="image/jpeg",
            now=datetime(2026, 6, 14, 8, 30, tzinfo=UTC),
        )
    except ValueError as exc:
        assert "unsafe" in str(exc).lower()
    else:  # pragma: no cover - assertion helper
        raise AssertionError("unsafe unique ID should be rejected")
