from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pulsekeeper.agent_runtime import ModelRuntime
from pulsekeeper.telegram_transport import handle_telegram_update


class TelegramHttpClient(Protocol):
    def get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]: ...

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class TelegramBotApiClient:
    def __init__(self, *, token: str, http_client: TelegramHttpClient) -> None:
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._http_client = http_client

    def get_updates(self, *, offset: int | None = None, timeout: int = 30) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        response = self._http_client.get_json(f"{self._base_url}/getUpdates", params)
        return response["result"]

    def send_message(self, *, chat_id: int, text: str) -> None:
        self._http_client.post_json(
            f"{self._base_url}/sendMessage",
            {"chat_id": chat_id, "text": text},
        )


def poll_once(
    client: TelegramBotApiClient,
    *,
    storage_dir: Path,
    offset: int | None = None,
    timeout: int = 30,
    model_runtime: ModelRuntime | None = None,
) -> int | None:
    updates = client.get_updates(offset=offset, timeout=timeout)
    next_offset = offset
    for update in updates:
        outbound = handle_telegram_update(
            update,
            storage_dir=storage_dir,
            model_runtime=model_runtime,
        )
        if outbound is not None:
            client.send_message(chat_id=outbound.chat_id, text=outbound.text)
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            next_offset = update_id + 1
    return next_offset
