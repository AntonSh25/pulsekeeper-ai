import json
from datetime import date
from urllib.error import URLError

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


def test_config_command_prints_redacted_setup_summary(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[storage]
dir = "./data"

[telegram]
enabled = true
bot_token = "123456:telegram-secret-token"

[llm]
auth_mode = "api_key"
base_url = "https://api.openai.com/v1"
model = "gpt-test"
api_key = "***"
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Config:" in result.stdout
    assert "storage.dir:" in result.stdout
    assert "llm.model: gpt-test" in result.stdout
    assert "telegram.enabled: true" in result.stdout
    assert "telegram-secret-token" not in result.stdout
    assert "***" in result.stdout


def test_doctor_reports_actionable_redacted_diagnostics(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[storage]
dir = "./data"

[telegram]
enabled = true
bot_token_env = "MISSING_TELEGRAM_TOKEN"

[llm]
auth_mode = "api_key"
base_url = "https://api.openai.com/v1"
model = "gpt-test"
api_key = "***"
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["doctor", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "OK storage writable" in result.stdout
    assert "OK DB migrations" in result.stdout
    assert "FAIL Telegram token" in result.stdout
    assert "Set MISSING_TELEGRAM_TOKEN" in result.stdout
    assert "OK provider configured" in result.stdout
    assert "WARN provider reachable" in result.stdout
    assert "***" not in result.stdout


def test_doctor_warns_about_inline_secrets_without_leaking_them(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[storage]
dir = "./data"

[telegram]
enabled = true
bot_token = "123456:telegram-secret-token"

[llm]
auth_mode = "api_key"
base_url = "https://api.openai.com/v1"
model = "gpt-test"
api_key = "***"
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["doctor", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "WARN unsafe config" in result.stdout
    assert "Move inline secrets to .env" in result.stdout
    assert "telegram-secret-token" not in result.stdout
    assert "***" not in result.stdout


def test_doctor_checks_provider_reachability_with_redacted_request(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[storage]
dir = "./data"

[llm]
auth_mode = "api_key"
base_url = "https://llm.example.test/v1/"
model = "gpt-test"
api_key = "sk-secret-provider-key"
""".strip(),
        encoding="utf-8",
    )
    requested = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"data": []}'

    def fake_urlopen(request, timeout):
        requested["url"] = request.full_url
        requested["auth"] = request.headers.get("Authorization")
        requested["timeout"] = timeout
        return Response()

    monkeypatch.setattr("pulsekeeper.cli.urlopen", fake_urlopen)

    result = runner.invoke(
        app,
        ["doctor", "--config", str(config_path), "--check-provider-network"],
    )

    assert result.exit_code == 0
    assert requested == {
        "url": "https://llm.example.test/v1/models",
        "auth": "Bearer sk-secret-provider-key",
        "timeout": 60,
    }
    assert "OK provider reachable" in result.stdout
    assert "sk-secret-provider-key" not in result.stdout


def test_doctor_reports_unreachable_provider_without_leaking_secret(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[storage]
dir = "./data"

[llm]
auth_mode = "api_key"
base_url = "https://llm.example.test/v1"
model = "gpt-test"
api_key = "sk-secret-provider-key"
""".strip(),
        encoding="utf-8",
    )

    def fake_urlopen(request, timeout):
        raise URLError("provider rejected sk-secret-provider-key")

    monkeypatch.setattr("pulsekeeper.cli.urlopen", fake_urlopen)

    result = runner.invoke(
        app,
        ["doctor", "--config", str(config_path), "--check-provider-network"],
    )

    assert result.exit_code == 1
    assert "FAIL provider reachable" in result.stdout
    assert "provider rejected" in result.stdout
    assert "sk-sec...-key" not in result.stdout


def test_telegram_run_requires_configured_token(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[storage]
dir = "./data"

[telegram]
enabled = true
bot_token_env = "MISSING_TELEGRAM_TOKEN"

[llm]
auth_mode = "subscription"
base_url = "https://llm.example.test/v1"
model = "gpt-test"
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["telegram-run", "--config", str(config_path), "--max-iterations", "0"],
    )

    assert result.exit_code == 1
    assert "Set MISSING_TELEGRAM_TOKEN" in result.stdout


def test_telegram_run_initializes_state_without_printing_token(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[storage]
dir = "./data"

[telegram]
enabled = true
bot_token = "123456:telegram-secret-token"

[llm]
auth_mode = "subscription"
base_url = "https://llm.example.test/v1"
model = "gpt-test"
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["telegram-run", "--config", str(config_path), "--max-iterations", "0"],
    )

    assert result.exit_code == 0
    assert "Telegram polling stopped" in result.stdout
    assert "telegram-secret-token" not in result.stdout
