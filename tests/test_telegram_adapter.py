from datetime import date
from pathlib import Path

from pulsekeeper.agent_runtime import MessageContext, ToolCall
from pulsekeeper.domain import HealthEntry
from pulsekeeper.storage import JsonlHealthLog
from pulsekeeper.telegram_adapter import MODEL_REQUIRED_TEXT, handle_telegram_text


class FakeModelRuntime:
    def __init__(self, calls_by_message: dict[str, list[ToolCall]]) -> None:
        self.calls_by_message = calls_by_message

    def complete_with_tools(self, message: str, context: MessageContext) -> list[ToolCall]:
        return self.calls_by_message[message]


def log_call(kind: str, note: str, value: float | None = None, unit: str | None = None) -> ToolCall:
    args: dict[str, object] = {"kind": kind, "note": note}
    if value is not None:
        args["value"] = value
    if unit is not None:
        args["unit"] = unit
    return ToolCall(name="log_health_entry", arguments=args)


def test_telegram_adapter_requires_model_for_natural_language_without_parser(tmp_path):
    log_path = tmp_path / "health.jsonl"

    response = handle_telegram_text("вес 84.2 кг", log_path=log_path)

    assert response == MODEL_REQUIRED_TEXT
    assert JsonlHealthLog(log_path).read_all() == []


def test_telegram_adapter_logs_health_text_through_agent_tool_call(tmp_path):
    log_path = tmp_path / "health.jsonl"
    model = FakeModelRuntime(
        {"вес 84.2 кг": [log_call("weight", "вес 84.2 кг", value=84.2, unit="kg")]}
    )

    response = handle_telegram_text("вес 84.2 кг", log_path=log_path, model_runtime=model)

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

    assert "Напиши обычным текстом" in response
    assert "/summary" in response


def test_telegram_adapter_unknown_command_returns_help():
    response = handle_telegram_text("/unknown", log_path=Path("unused.jsonl"))

    assert "Не понял команду" in response
    assert "/summary" in response


def test_telegram_adapter_routes_each_user_to_own_jsonl_log_via_agent_tools(tmp_path):
    storage_dir = tmp_path / "pulsekeeper"
    model = FakeModelRuntime(
        {
            "вес 84.2 кг": [log_call("weight", "вес 84.2 кг", value=84.2, unit="kg")],
            "завтрак: омлет": [log_call("food", "завтрак: омлет")],
        }
    )

    first_response = handle_telegram_text(
        "вес 84.2 кг",
        storage_dir=storage_dir,
        telegram_user_id="111",
        model_runtime=model,
    )
    second_response = handle_telegram_text(
        "завтрак: омлет",
        storage_dir=storage_dir,
        telegram_user_id="222",
        model_runtime=model,
    )

    assert first_response == "Записал: weight — вес 84.2 кг"
    assert second_response == "Записал: food — завтрак: омлет"
    first_log = JsonlHealthLog(storage_dir / "users" / "111" / "health.jsonl")
    second_log = JsonlHealthLog(storage_dir / "users" / "222" / "health.jsonl")
    assert first_log.read_all()[0].kind == "weight"
    assert second_log.read_all()[0].kind == "food"


def test_telegram_adapter_user_summary_reads_only_that_users_log(tmp_path):
    storage_dir = tmp_path / "pulsekeeper"
    model = FakeModelRuntime(
        {
            "завтрак: омлет": [log_call("food", "завтрак: омлет")],
            "зал 45 минут": [log_call("workout", "зал 45 минут")],
        }
    )
    handle_telegram_text(
        "завтрак: омлет",
        storage_dir=storage_dir,
        telegram_user_id="111",
        model_runtime=model,
    )
    handle_telegram_text(
        "зал 45 минут",
        storage_dir=storage_dir,
        telegram_user_id="222",
        model_runtime=model,
    )

    response = handle_telegram_text("/summary", storage_dir=storage_dir, telegram_user_id="111")

    assert "- Entries: 1" in response
    assert "завтрак: омлет" in response
    assert "зал 45 минут" not in response
