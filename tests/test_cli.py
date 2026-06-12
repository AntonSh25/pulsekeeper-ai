import json
from datetime import date

from typer.testing import CliRunner

from pulsekeeper.cli import app
from pulsekeeper.domain import HealthEntry
from pulsekeeper.storage import JsonlHealthLog

runner = CliRunner()


def test_log_command_appends_parsed_entry_to_jsonl(tmp_path):
    log_path = tmp_path / "health.jsonl"

    result = runner.invoke(app, ["log", "вес 84.2 кг", "--file", str(log_path)])

    assert result.exit_code == 0
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["kind"] == "weight"
    assert "Logged weight" in result.stdout


def test_summary_command_reads_jsonl_and_prints_daily_markdown(tmp_path):
    log_path = tmp_path / "health.jsonl"
    log = JsonlHealthLog(log_path)
    log.append(HealthEntry(kind="food", note="завтрак: омлет", logged_at=date(2026, 6, 12)))
    log.append(HealthEntry(kind="workout", note="зал 45 минут", logged_at=date(2026, 6, 12)))
    log.append(HealthEntry(kind="sleep", note="сон 8 часов", logged_at=date(2026, 6, 11)))

    result = runner.invoke(
        app,
        ["summary", "--file", str(log_path), "--date", "2026-06-12"],
    )

    assert result.exit_code == 0
    assert "## PulseKeeper summary: 2026-06-12" in result.stdout
    assert "- Entries: 2" in result.stdout
    assert "завтрак: омлет" in result.stdout
    assert "сон 8 часов" not in result.stdout


def test_weekly_summary_uses_7_day_window_ending_on_requested_date(tmp_path):
    log_path = tmp_path / "health.jsonl"
    log = JsonlHealthLog(log_path)
    log.append(HealthEntry(kind="food", note="in range", logged_at=date(2026, 6, 6)))
    log.append(HealthEntry(kind="food", note="also in range", logged_at=date(2026, 6, 12)))
    log.append(HealthEntry(kind="food", note="out of range", logged_at=date(2026, 6, 5)))

    result = runner.invoke(
        app,
        ["summary", "--file", str(log_path), "--date", "2026-06-12", "--period", "week"],
    )

    assert result.exit_code == 0
    assert "## PulseKeeper summary: 2026-06-06..2026-06-12" in result.stdout
    assert "- Entries: 2" in result.stdout
    assert "in range" in result.stdout
    assert "also in range" in result.stdout
    assert "out of range" not in result.stdout


def test_telegram_handle_command_routes_message_through_adapter(tmp_path):
    log_path = tmp_path / "health.jsonl"

    result = runner.invoke(
        app,
        ["telegram-handle", "вес 84.2 кг", "--file", str(log_path)],
    )

    assert result.exit_code == 0
    assert "Записал: weight" in result.stdout
    assert JsonlHealthLog(log_path).read_all()[0].kind == "weight"
