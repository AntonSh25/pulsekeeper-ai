from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

import typer

from pulsekeeper.domain import parse_health_log
from pulsekeeper.storage import JsonlHealthLog
from pulsekeeper.summary import summarize_entries
from pulsekeeper.telegram_adapter import handle_telegram_text

app = typer.Typer(help="PulseKeeper CLI")
DEFAULT_LOG_PATH = Path.home() / ".pulsekeeper" / "health.jsonl"


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
    file: Annotated[Path, typer.Option("--file", "-f")] = DEFAULT_LOG_PATH,
) -> None:
    """Simulate handling one Telegram message locally."""
    typer.echo(handle_telegram_text(text, log_path=file))
