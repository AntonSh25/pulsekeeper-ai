from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pulsekeeper.telegram_adapter import handle_telegram_text


class TelegramOutboundMessage(BaseModel):
    chat_id: int
    text: str


def handle_telegram_update(
    update: dict[str, Any],
    *,
    storage_dir: Path,
) -> TelegramOutboundMessage | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None

    text = message.get("text")
    chat = message.get("chat")
    sender = message.get("from")
    if not isinstance(text, str) or not isinstance(chat, dict) or not isinstance(sender, dict):
        return None

    chat_id = chat.get("id")
    sender_id = sender.get("id")
    if not isinstance(chat_id, int) or not isinstance(sender_id, int):
        return None

    response_text = handle_telegram_text(
        text,
        storage_dir=storage_dir,
        telegram_user_id=str(sender_id),
    )
    return TelegramOutboundMessage(chat_id=chat_id, text=response_text)
