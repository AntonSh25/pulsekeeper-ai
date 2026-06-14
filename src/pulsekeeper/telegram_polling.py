from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pulsekeeper.agent_runtime import ModelRuntime
from pulsekeeper.telegram_transport import handle_telegram_update


class TelegramHttpClient(Protocol):
    def get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]: ...

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class TelegramOffsetStore(Protocol):
    async def get_telegram_offset(self, bot_profile: str) -> int | None: ...

    async def set_telegram_offset(self, bot_profile: str, offset: int) -> None: ...


class UrlLibTelegramHttpClient:
    def get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode(params)
        request_url = f"{url}?{query}" if query else url
        with urlopen(request_url) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))


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


async def run_polling_loop(
    client: TelegramBotApiClient,
    *,
    storage_dir: Path,
    gateway_state: TelegramOffsetStore,
    bot_profile: str = "default",
    timeout: int = 30,
    model_runtime: ModelRuntime | None = None,
    max_iterations: int | None = None,
    idle_sleep_seconds: float = 0.0,
    error_backoff_seconds: float = 5.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Run Telegram long polling, persisting offsets after handled updates."""
    offset = await gateway_state.get_telegram_offset(bot_profile)
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        try:
            next_offset = poll_once(
                client,
                storage_dir=storage_dir,
                offset=offset,
                timeout=timeout,
                model_runtime=model_runtime,
            )
        except Exception:
            iterations += 1
            if error_backoff_seconds:
                await sleep(error_backoff_seconds)
            continue
        if next_offset != offset and next_offset is not None:
            await gateway_state.set_telegram_offset(bot_profile, next_offset)
            offset = next_offset
        iterations += 1
        if idle_sleep_seconds:
            await sleep(idle_sleep_seconds)
