from __future__ import annotations

import asyncio
import json
import tomllib
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import typer

from pulsekeeper.config import ConfigError, load_config, redact_secret
from pulsekeeper.domain import parse_health_log
from pulsekeeper.importers.apple_health import import_apple_health_xml
from pulsekeeper.llm.agent import LLMConfig
from pulsekeeper.reminder_scheduler import TelegramReminderScheduler, run_scheduler_loop
from pulsekeeper.storage import JsonlHealthLog
from pulsekeeper.storage.sqlite import Database
from pulsekeeper.storage.users import GatewayStateStore
from pulsekeeper.summary import summarize_entries
from pulsekeeper.telegram_adapter import handle_telegram_text
from pulsekeeper.telegram_polling import (
    TelegramBotApiClient,
    UrlLibTelegramHttpClient,
    poll_once,
    run_polling_loop,
)
from pulsekeeper.telegram_transport import handle_telegram_update

app = typer.Typer(help="PulseKeeper CLI")
DEFAULT_LOG_PATH = Path.home() / ".pulsekeeper" / "health.jsonl"
DEFAULT_STORAGE_DIR = Path.home() / ".pulsekeeper"
DEFAULT_CONFIG_PATH = Path.home() / ".pulsekeeper" / "config.toml"


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


@app.command("import-apple-health")
def import_apple_health_command(
    export_xml: Path,
    storage_dir: Annotated[Path, typer.Option("--storage-dir")] = DEFAULT_STORAGE_DIR,
    user_id: Annotated[int, typer.Option("--user-id")] = 1,
) -> None:
    """Import supported Apple Health XML export records into SQLite."""
    result = asyncio.run(
        _import_apple_health_async(export_xml, storage_dir=storage_dir, user_id=user_id)
    )
    typer.echo(
        "Apple Health import complete: "
        f"imported={result.imported} skipped={result.skipped} unsupported={result.unsupported}"
    )


async def _import_apple_health_async(export_xml: Path, *, storage_dir: Path, user_id: int):
    storage_dir.mkdir(parents=True, exist_ok=True)
    database = Database(storage_dir / "state.db")
    try:
        await database.initialize()
        await database.execute("INSERT OR IGNORE INTO users(id) VALUES (?)", (user_id,))
        return await import_apple_health_xml(database, user_id=user_id, path=export_xml)
    finally:
        await database.close()


@app.command("config")
def config_command(
    config_path: Annotated[
        Path,
        typer.Option("--config", help="Path to config.toml."),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """Print a redacted PulseKeeper configuration summary."""
    try:
        loaded = load_config(config_path)
    except ConfigError as exc:
        typer.echo(f"Config error: {exc}")
        raise typer.Exit(1) from exc

    typer.echo(f"Config: {config_path}")
    typer.echo(f"storage.dir: {loaded.storage.dir}")
    typer.echo(f"storage.database: {loaded.storage.database_path}")
    typer.echo(f"telegram.enabled: {str(loaded.telegram.enabled).lower()}")
    typer.echo(f"telegram.bot_token: {_configured_text(loaded.telegram.bot_token)}")
    typer.echo(f"llm.auth_mode: {loaded.llm.auth_mode}")
    typer.echo(f"llm.base_url: {loaded.llm.base_url}")
    typer.echo(f"llm.model: {loaded.llm.model}")
    typer.echo(f"llm.api_key: {_configured_text(loaded.llm.api_key)}")
    typer.echo(f"vision.enabled: {str(loaded.vision.enabled).lower()}")
    if loaded.vision.enabled:
        typer.echo(f"vision.base_url: {loaded.vision.base_url}")
        typer.echo(f"vision.model: {loaded.vision.model}")
        typer.echo(f"vision.api_key: {_configured_text(loaded.vision.api_key)}")


@app.command("doctor")
def doctor_command(
    config_path: Annotated[
        Path,
        typer.Option("--config", help="Path to config.toml."),
    ] = DEFAULT_CONFIG_PATH,
    check_provider_network: Annotated[
        bool,
        typer.Option(
            "--check-provider-network",
            help="Attempt a live provider reachability check.",
        ),
    ] = False,
) -> None:
    """Run redacted self-host setup diagnostics."""
    failures = 0
    try:
        loaded = load_config(config_path)
    except ConfigError as exc:
        typer.echo(f"FAIL config: {exc}")
        raise typer.Exit(1) from exc

    try:
        loaded.storage.dir.mkdir(parents=True, exist_ok=True)
        probe = loaded.storage.dir / ".pulsekeeper-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        typer.echo(f"OK storage writable: {loaded.storage.dir}")
    except OSError as exc:
        failures += 1
        typer.echo(f"FAIL storage writable: {exc}")

    try:
        asyncio.run(_check_db_migrations(loaded.storage.database_path))
        typer.echo(f"OK DB migrations: {loaded.storage.database_path}")
    except Exception as exc:
        failures += 1
        typer.echo(f"FAIL DB migrations: {exc}")

    if loaded.telegram.enabled and not loaded.telegram.bot_token:
        failures += 1
        typer.echo(f"FAIL Telegram token: Set {loaded.telegram.bot_token_env} in .env")
    elif loaded.telegram.enabled:
        typer.echo("OK Telegram token: configured")
    else:
        typer.echo("OK Telegram token: not required because telegram.enabled=false")

    typer.echo(f"OK provider configured: {loaded.llm.auth_mode} {loaded.llm.model}")
    if loaded.vision.enabled:
        typer.echo(f"OK vision provider configured: {loaded.vision.model}")
    else:
        typer.echo("OK vision provider: disabled")
    unsafe_messages = _unsafe_config_messages(config_path)
    if unsafe_messages:
        unsafe_list = ", ".join(unsafe_messages)
        typer.echo(f"WARN unsafe config: Move inline secrets to .env ({unsafe_list})")
    else:
        typer.echo("OK unsafe config: no inline secrets found")
    if check_provider_network:
        try:
            _check_provider_reachable(loaded.llm)
            typer.echo("OK provider reachable: /models responded")
        except Exception as exc:
            failures += 1
            message = redact_secret(str(exc), secrets=(loaded.llm.api_key or "",))
            typer.echo(f"FAIL provider reachable: {message}")
    else:
        typer.echo("WARN provider reachable: skipped (use --check-provider-network)")

    if failures:
        raise typer.Exit(1)


async def _check_db_migrations(path: Path) -> None:
    database = Database(path)
    try:
        await database.initialize()
    finally:
        await database.close()


def _check_provider_reachable(config: LLMConfig) -> None:
    if config.base_url is None:
        raise RuntimeError("provider base_url is not configured")
    base_url = config.base_url.rstrip("/") + "/"
    request = Request(urljoin(base_url, "models"), method="GET")
    if config.api_key:
        request.add_header("Authorization", f"Bearer {config.api_key}")
    try:
        with urlopen(request, timeout=config.timeout) as response:
            if getattr(response, "status", 200) >= 400:
                raise RuntimeError(f"provider returned HTTP {response.status}")
            response.read()
    except HTTPError as exc:
        raise RuntimeError(f"provider returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"provider request failed: {exc.reason}") from exc


def _unsafe_config_messages(config_path: Path) -> list[str]:
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    messages: list[str] = []
    llm = raw.get("llm", {})
    if isinstance(llm, dict) and llm.get("api_key"):
        messages.append("llm.api_key")
    telegram = raw.get("telegram", {})
    if isinstance(telegram, dict) and telegram.get("bot_token"):
        messages.append("telegram.bot_token")
    vision = raw.get("vision", {})
    if isinstance(vision, dict) and vision.get("api_key"):
        messages.append("vision.api_key")
    return messages


def _configured_text(value: str | None) -> str:
    return "***" if value else "not configured"


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


@app.command("telegram-run")
def telegram_run(
    config_path: Annotated[
        Path,
        typer.Option("--config", help="Path to config.toml."),
    ] = DEFAULT_CONFIG_PATH,
    bot_profile: Annotated[str, typer.Option("--bot-profile")] = "default",
    timeout: Annotated[int, typer.Option("--timeout")] = 30,
    max_iterations: Annotated[int | None, typer.Option("--max-iterations", hidden=True)] = None,
) -> None:
    """Run the live Telegram long-polling loop."""
    try:
        loaded = load_config(config_path)
    except ConfigError as exc:
        typer.echo(f"Config error: {exc}")
        raise typer.Exit(1) from exc

    if not loaded.telegram.bot_token:
        typer.echo(f"FAIL Telegram token: Set {loaded.telegram.bot_token_env} in .env")
        raise typer.Exit(1)

    try:
        asyncio.run(
            _telegram_run_async(
                loaded.storage.database_path,
                loaded.storage.dir,
                token=loaded.telegram.bot_token,
                bot_profile=bot_profile,
                timeout=timeout,
                max_iterations=max_iterations,
                log=typer.echo,
            )
        )
    except KeyboardInterrupt:
        pass
    typer.echo("Telegram polling stopped")


async def _telegram_run_async(
    database_path: Path,
    storage_dir: Path,
    *,
    token: str,
    bot_profile: str,
    timeout: int,
    max_iterations: int | None,
    log: Callable[[str], None] | None = None,
) -> None:
    database = Database(database_path)
    try:
        await database.initialize()
        state = GatewayStateStore(database)
        client = TelegramBotApiClient(token=token, http_client=UrlLibTelegramHttpClient())
        await run_polling_loop(
            client,
            storage_dir=storage_dir,
            gateway_state=state,
            bot_profile=bot_profile,
            timeout=timeout,
            max_iterations=max_iterations,
            log=log,
            secrets=(token,),
        )
    finally:
        await database.close()


@app.command("reminders-run")
def reminders_run(
    config_path: Annotated[
        Path,
        typer.Option("--config", help="Path to config.toml."),
    ] = DEFAULT_CONFIG_PATH,
    interval_seconds: Annotated[float, typer.Option("--interval-seconds")] = 60.0,
    max_iterations: Annotated[int | None, typer.Option("--max-iterations", hidden=True)] = None,
) -> None:
    """Run the Telegram reminder scheduler loop."""
    try:
        loaded = load_config(config_path)
    except ConfigError as exc:
        typer.echo(f"Config error: {exc}")
        raise typer.Exit(1) from exc

    if not loaded.telegram.bot_token:
        typer.echo(f"FAIL Telegram token: Set {loaded.telegram.bot_token_env} in .env")
        raise typer.Exit(1)

    try:
        asyncio.run(
            _reminders_run_async(
                loaded.storage.database_path,
                token=loaded.telegram.bot_token,
                interval_seconds=interval_seconds,
                max_iterations=max_iterations,
            )
        )
    except KeyboardInterrupt:
        pass
    typer.echo("Reminder scheduler stopped")


async def _reminders_run_async(
    database_path: Path,
    *,
    token: str,
    interval_seconds: float,
    max_iterations: int | None,
) -> None:
    database = Database(database_path)
    try:
        await database.initialize()
        client = TelegramBotApiClient(token=token, http_client=UrlLibTelegramHttpClient())
        scheduler = TelegramReminderScheduler(
            db=database,
            send_message=lambda chat_id, text: client.send_message(chat_id=chat_id, text=text),
        )
        await run_scheduler_loop(
            process_due=scheduler.process_due,
            max_iterations=max_iterations,
            interval_seconds=interval_seconds,
        )
    finally:
        await database.close()
