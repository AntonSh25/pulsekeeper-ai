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


def test_telegram_handle_command_requires_agent_model_for_natural_language(tmp_path):
    log_path = tmp_path / "health.jsonl"

    result = runner.invoke(
        app,
        ["telegram-handle", "вес 84.2 кг", "--file", str(log_path)],
    )

    assert result.exit_code == 0
    assert "Нужен BYOK LLM provider" in result.stdout
    assert JsonlHealthLog(log_path).read_all() == []


def test_telegram_handle_command_does_not_parse_by_user_id_without_agent_model(tmp_path):
    storage_dir = tmp_path / "pulsekeeper"

    first = runner.invoke(
        app,
        [
            "telegram-handle",
            "вес 84.2 кг",
            "--storage-dir",
            str(storage_dir),
            "--user-id",
            "111",
        ],
    )
    second = runner.invoke(
        app,
        [
            "telegram-handle",
            "зал 45 минут",
            "--storage-dir",
            str(storage_dir),
            "--user-id",
            "222",
        ],
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "Нужен BYOK LLM provider" in first.stdout
    assert "Нужен BYOK LLM provider" in second.stdout
    first_log = JsonlHealthLog(storage_dir / "users" / "111" / "health.jsonl")
    second_log = JsonlHealthLog(storage_dir / "users" / "222" / "health.jsonl")
    assert first_log.read_all() == []
    assert second_log.read_all() == []


def test_telegram_update_command_requires_agent_model_for_natural_language(tmp_path):
    storage_dir = tmp_path / "pulsekeeper"
    update_json = (
        '{"message":{"chat":{"id":555},"from":{"id":111},"text":"вес 84.2 кг"}}'
    )

    result = runner.invoke(
        app,
        ["telegram-update", update_json, "--storage-dir", str(storage_dir)],
    )

    assert result.exit_code == 0
    assert "Нужен BYOK LLM provider" in result.stdout
    log = JsonlHealthLog(storage_dir / "users" / "111" / "health.jsonl")
    assert log.read_all() == []


def test_telegram_poll_once_command_uses_fixture_without_token_or_parser(tmp_path):
    storage_dir = tmp_path / "pulsekeeper"
    fixture_path = tmp_path / "updates.json"
    fixture_path.write_text(
        '{"ok": true, "result": [{"update_id": 42, "message": {'
        '"chat": {"id": 555}, "from": {"id": 111}, "text": "вес 84.2 кг"}}]}',
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "telegram-poll-once",
            "--fixture",
            str(fixture_path),
            "--storage-dir",
            str(storage_dir),
            "--offset",
            "41",
        ],
    )

    assert result.exit_code == 0
    assert "next_offset=43" in result.stdout
    assert "sendMessage chat_id=555" in result.stdout
    assert "Нужен BYOK LLM provider" in result.stdout
    log = JsonlHealthLog(storage_dir / "users" / "111" / "health.jsonl")
    assert log.read_all() == []
