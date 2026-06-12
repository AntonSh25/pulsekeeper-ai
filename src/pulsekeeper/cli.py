from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from pulsekeeper.domain import parse_health_log
from pulsekeeper.storage import JsonlHealthLog
from pulsekeeper.summary import summarize_entries
from pulsekeeper.telegram_adapter import handle_telegram_text
from pulsekeeper.telegram_polling import TelegramBotApiClient, poll_once
from pulsekeeper.telegram_transport import handle_telegram_update

app = typer.Typer(help="PulseKeeper CLI")
DEFAULT_LOG_PATH = Path.home() / ".pulsekeeper" / "health.jsonl"
DEFAULT_STORAGE_DIR = Path.home() / ".pulsekeeper"


@app.command()
def parse(text: str) -> None:
    """Parse a free-text health log and print structured JSON."""
    typer.echo(parse_health_log(text).model_dump_json())


@app.command()
def log(
    text: str,
    file: Annotated[Path, typer.Option("--file", "-f")] = DEFAULT_LOG_PATH,
) -> None:
    """Parse a free-text health log and append it to a JSONL file."""
    entry = parse_health_log(text)
    JsonlHealthLog(file).append(entry)
    typer.echo(f"Logged {entry.kind}: {entry.note}")


@app.command()
def summary(
    file: Annotated[Path, typer.Option("--file", "-f")] = DEFAULT_LOG_PATH,
    target_date: Annotated[
        str | None,
        typer.Option("--date", help="Period end date in YYYY-MM-DD format."),
    ] = None,
    period: Annotated[str, typer.Option("--period", help="day or week")] = "day",
) -> None:
    """Read a JSONL health log and print a daily or weekly summary."""
    if period not in {"day", "week"}:
        raise typer.BadParameter("period must be 'day' or 'week'")

    end = date.today() if target_date is None else date.fromisoformat(target_date)
    start = end if period == "day" else end - timedelta(days=6)
    entries = JsonlHealthLog(file).read_all()
    typer.echo(summarize_entries(entries, start=start, end=end).to_markdown())


@app.command("telegram-handle")
def telegram_handle(
    text: str,
    file: Annotated[Path | None, typer.Option("--file", "-f")] = None,
    storage_dir: Annotated[Path, typer.Option("--storage-dir")] = DEFAULT_STORAGE_DIR,
    user_id: Annotated[str | None, typer.Option("--user-id")] = None,
) -> None:
    """Simulate handling one Telegram message locally."""
    if user_id is None:
        typer.echo(handle_telegram_text(text, log_path=file or DEFAULT_LOG_PATH))
        return
    typer.echo(handle_telegram_text(text, storage_dir=storage_dir, telegram_user_id=user_id))


@app.command("telegram-update")
def telegram_update(
    update_json: str,
    storage_dir: Annotated[Path, typer.Option("--storage-dir")] = DEFAULT_STORAGE_DIR,
) -> None:
    """Simulate handling one Telegram Bot API update JSON locally."""
    outbound = handle_telegram_update(json.loads(update_json), storage_dir=storage_dir)
    if outbound is not None:
        typer.echo(outbound.text)


class FixtureTelegramHttpClient:
    def __init__(self, fixture: Path) -> None:
        self.fixture = fixture

    def get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        return json.loads(self.fixture.read_text(encoding="utf-8"))

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        typer.echo(f"sendMessage chat_id={payload['chat_id']} text={payload['text']}")
        return {"ok": True, "result": True}


@app.command("telegram-poll-once")
def telegram_poll_once(
    fixture: Annotated[Path, typer.Option("--fixture")],
    storage_dir: Annotated[Path, typer.Option("--storage-dir")] = DEFAULT_STORAGE_DIR,
    offset: Annotated[int | None, typer.Option("--offset")] = None,
) -> None:
    """Run one Telegram polling iteration from a fixture, without live network calls."""
    client = TelegramBotApiClient(
        token="fixture-token",
        http_client=FixtureTelegramHttpClient(fixture),
    )
    next_offset = poll_once(client, storage_dir=storage_dir, offset=offset, timeout=0)
    typer.echo(f"next_offset={next_offset}")
