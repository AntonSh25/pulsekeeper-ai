from datetime import date
from pathlib import Path

from pulsekeeper.domain import HealthEntry
from pulsekeeper.storage import JsonlHealthLog
from pulsekeeper.telegram_adapter import handle_telegram_text


def test_telegram_adapter_logs_health_text_and_returns_short_confirmation(tmp_path):
    log_path = tmp_path / "health.jsonl"

    response = handle_telegram_text("вес 84.2 кг", log_path=log_path)

    assert response == "Записал: weight — вес 84.2 кг"
    assert JsonlHealthLog(log_path).read_all()[0].kind == "weight"


def test_telegram_adapter_daily_summary_command(tmp_path):
    log_path = tmp_path / "health.jsonl"
    JsonlHealthLog(log_path).append(
        HealthEntry(kind="food", note="завтрак: омлет", logged_at=date.today())
    )

    response = handle_telegram_text("/summary", log_path=log_path)

    assert "## PulseKeeper summary:" in response
    assert "- Entries: 1" in response
    assert "завтрак: омлет" in response


def test_telegram_adapter_weekly_summary_command(tmp_path):
    response = handle_telegram_text("/summary week", log_path=tmp_path / "health.jsonl")

    assert "PulseKeeper summary" in response


def test_telegram_adapter_help_command():
    response = handle_telegram_text("/help", log_path=Path("unused.jsonl"))

    assert "Напиши вес, еду, тренировку или сон" in response
    assert "/summary" in response


def test_telegram_adapter_unknown_command_returns_help():
    response = handle_telegram_text("/unknown", log_path=Path("unused.jsonl"))

    assert "Не понял команду" in response
    assert "/summary" in response


def test_telegram_adapter_routes_each_user_to_own_jsonl_log(tmp_path):
    storage_dir = tmp_path / "pulsekeeper"

    first_response = handle_telegram_text(
        "вес 84.2 кг",
        storage_dir=storage_dir,
        telegram_user_id="111",
    )
    second_response = handle_telegram_text(
        "завтрак: омлет",
        storage_dir=storage_dir,
        telegram_user_id="222",
    )

    assert first_response == "Записал: weight — вес 84.2 кг"
    assert second_response == "Записал: food — завтрак: омлет"
    first_log = JsonlHealthLog(storage_dir / "users" / "111" / "health.jsonl")
    second_log = JsonlHealthLog(storage_dir / "users" / "222" / "health.jsonl")
    assert first_log.read_all()[0].kind == "weight"
    assert second_log.read_all()[0].kind == "food"


def test_telegram_adapter_user_summary_reads_only_that_users_log(tmp_path):
    storage_dir = tmp_path / "pulsekeeper"
    handle_telegram_text("завтрак: омлет", storage_dir=storage_dir, telegram_user_id="111")
    handle_telegram_text("зал 45 минут", storage_dir=storage_dir, telegram_user_id="222")

    response = handle_telegram_text("/summary", storage_dir=storage_dir, telegram_user_id="111")

    assert "- Entries: 1" in response
    assert "завтрак: омлет" in response
    assert "зал 45 минут" not in response
