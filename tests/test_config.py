from __future__ import annotations

import os

import pytest

from pulsekeeper.config import ConfigError, load_config, redact_secret
from pulsekeeper.llm.agent import LLMConfig, build_agent


def test_load_llm_config_from_toml_and_env_api_key_env(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        """
[llm]
auth_mode = "api_key"
base_url = "https://api.openai.com/v1"
model = "gpt-test"
api_key_env = "PULSEKEEPER_TEST_API_KEY"
timeout = 45
max_tool_iterations = 3
""".strip(),
        encoding="utf-8",
    )
    env_path.write_text("PULSEKEEPER_TEST_API_KEY=sk-test-from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv("PULSEKEEPER_TEST_API_KEY", raising=False)

    config = load_config(config_path, env_path=env_path)

    assert config.llm == LLMConfig(
        auth_mode="api_key",
        base_url="https://api.openai.com/v1",
        model="gpt-test",
        api_key="sk-test-from-dotenv",
        timeout=45,
        max_tool_iterations=3,
    )
    assert "sk-tes...tenv" not in repr(config.llm)
    assert "***" in repr(config.llm)


def test_load_config_includes_storage_and_telegram_sections_without_leaking_token(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.toml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        """
[storage]
dir = "./pulsekeeper-data"
database = "custom-state.db"

[telegram]
enabled = true
bot_token_env = "PULSEKEEPER_TEST_TELEGRAM_TOKEN"

[llm]
auth_mode = "api_key"
base_url = "https://api.openai.com/v1"
model = "gpt-test"
api_key_env = "PULSEKEEPER_TEST_API_KEY"
""".strip(),
        encoding="utf-8",
    )
    env_path.write_text(
        "PULSEKEEPER_TEST_API_KEY=sk-tes...tenv\n"
        "PULSEKEEPER_TEST_TELEGRAM_TOKEN=123456:telegram-secret-token\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("PULSEKEEPER_TEST_API_KEY", raising=False)
    monkeypatch.delenv("PULSEKEEPER_TEST_TELEGRAM_TOKEN", raising=False)

    config = load_config(config_path, env_path=env_path)

    assert config.storage.dir == tmp_path / "pulsekeeper-data"
    assert config.storage.database_path == tmp_path / "pulsekeeper-data" / "custom-state.db"
    assert config.telegram.enabled is True
    assert config.telegram.bot_token == "123456:telegram-secret-token"
    assert "telegram-secret-token" not in repr(config.telegram)
    assert "***" in repr(config.telegram)


def test_load_config_auto_loads_dotenv_beside_config_without_mutating_environment(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[llm]
auth_mode = "api_key"
base_url = "https://llm.example.test/v1"
model = "example-model"
api_key_env = "PULSEKEEPER_AUTO_DOTENV_KEY"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "PULSEKEEPER_AUTO_DOTENV_KEY=sk-aut...dotenv\n", encoding="utf-8"
    )
    monkeypatch.delenv("PULSEKEEPER_AUTO_DOTENV_KEY", raising=False)

    config = load_config(config_path)

    assert config.llm.api_key == "sk-aut...dotenv"
    assert "PULSEKEEPER_AUTO_DOTENV_KEY" not in os.environ


def test_os_environment_overrides_dotenv_for_api_key(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        """
[llm]
auth_mode = "api_key"
base_url = "https://api.openai.com/v1"
model = "gpt-test"
api_key_env = "PULSEKEEPER_TEST_API_KEY"
""".strip(),
        encoding="utf-8",
    )
    env_path.write_text("PULSEKEEPER_TEST_API_KEY=sk-test-from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("PULSEKEEPER_TEST_API_KEY", "sk-test-from-os")

    config = load_config(config_path, env_path=env_path)

    assert config.llm.api_key == "sk-test-from-os"


def test_missing_api_key_mode_raises_clear_redacted_error(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[llm]
auth_mode = "api_key"
base_url = "https://api.openai.com/v1"
model = "gpt-test"
api_key_env = "PULSEKEEPER_MISSING_API_KEY"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delenv("PULSEKEEPER_MISSING_API_KEY", raising=False)

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_path, env_path=tmp_path / ".env")

    message = str(exc_info.value)
    assert "api_key" in message
    assert "PULSEKEEPER_MISSING_API_KEY" in message
    assert "sk-" not in message


def test_subscription_mode_defaults_to_hermes_proxy_and_needs_no_api_key(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[llm]
auth_mode = "subscription"
model = "hermes-test-model"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path, env_path=tmp_path / ".env")

    assert config.llm.auth_mode == "subscription"
    assert config.llm.base_url == "http://127.0.0.1:8645/v1"
    assert config.llm.model == "hermes-test-model"
    assert config.llm.api_key is None


def test_load_config_rejects_internal_test_auth_mode_from_toml(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[llm]
auth_mode = "test"
model = "function"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="api_key.*subscription"):
        load_config(config_path)


def test_empty_direct_api_key_raises_clear_error(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[llm]
auth_mode = "api_key"
base_url = "https://llm.example.test/v1"
model = "example-model"
api_key = ""
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="llm.api_key must be a non-empty string"):
        load_config(config_path)


def test_redaction_masks_known_secret_in_nested_values():
    secret = "sk-test-1234567890"
    redacted = redact_secret(
        {
            "api_key": secret,
            "plain_api_key": "plain-secret-value",
            "message": f"provider rejected {secret}",
            "nested": {"authorization": f"Bearer {secret}"},
        },
        secrets=[secret],
    )

    assert secret not in str(redacted)
    assert "plain-secret-value" not in str(redacted)
    assert redacted["api_key"] == "***"
    assert redacted["plain_api_key"] == "***"
    assert redacted["message"] == "provider rejected ***"
    assert redacted["nested"]["authorization"] == "Bearer ***"


def test_build_agent_constructs_api_key_and_subscription_without_network():
    api_key_agent = build_agent(
        LLMConfig(
            auth_mode="api_key",
            base_url="https://api.openai.com/v1",
            model="gpt-test",
            api_key="test-api-key-no-network",
        )
    )
    subscription_agent = build_agent(
        LLMConfig(
            auth_mode="subscription",
            base_url="http://127.0.0.1:8645/v1",
            model="hermes-test-model",
        )
    )

    assert api_key_agent.config.api_key == "test-api-key-no-network"
    assert subscription_agent.config.api_key is None
    assert "test-api-key-no-network" not in repr(api_key_agent.config)


def test_build_agent_subscription_passes_placeholder_not_environment_api_key(monkeypatch):
    provider_kwargs = {}

    class FakeProvider:
        def __init__(self, **kwargs):
            provider_kwargs.update(kwargs)

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self, *args, **kwargs):
            pass

    monkeypatch.setenv("OPENAI_API_KEY", "sk-rea...cret")
    monkeypatch.setattr("pulsekeeper.llm.agent.OpenAIProvider", FakeProvider)
    monkeypatch.setattr(
        "pulsekeeper.llm.agent.OpenAIModel",
        lambda model, provider: "fake-model",
    )
    monkeypatch.setattr("pulsekeeper.llm.agent.Agent", FakeAgent)

    built = build_agent(
        LLMConfig(
            auth_mode="subscription",
            base_url="http://127.0.0.1:8645/v1",
            model="hermes-model",
        )
    )

    assert built.config.api_key is None
    assert provider_kwargs["api_key"] == "pulsekeeper-hermes-proxy"
    assert provider_kwargs["api_key"] != "sk-rea...cret"
    assert "sk-rea...cret" not in repr(built.config)


def test_build_agent_passes_config_timeout_to_openai_http_client(monkeypatch):
    provider_kwargs = {}

    class FakeProvider:
        def __init__(self, **kwargs):
            provider_kwargs.update(kwargs)

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self, *args, **kwargs):
            pass

    monkeypatch.setattr("pulsekeeper.llm.agent.OpenAIProvider", FakeProvider)
    monkeypatch.setattr(
        "pulsekeeper.llm.agent.OpenAIModel",
        lambda model, provider: "fake-model",
    )
    monkeypatch.setattr("pulsekeeper.llm.agent.Agent", FakeAgent)

    build_agent(
        LLMConfig(
            auth_mode="api_key",
            base_url="https://llm.example.test/v1",
            model="example-model",
            api_key="sk-test",
            timeout=17,
        )
    )

    http_client = provider_kwargs["http_client"]
    assert http_client.timeout.connect == 17
    assert http_client.timeout.read == 17
