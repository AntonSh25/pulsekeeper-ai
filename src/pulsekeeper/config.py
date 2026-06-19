from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from pulsekeeper.llm.agent import LLMConfig

DEFAULT_HERMES_PROXY_BASE_URL = "http://127.0.0.1:8645/v1"
_SECRET_KEYS = ("api_key", "apikey", "authorization", "token", "secret", "password")
_SECRET_PATTERN = re.compile(r"\b(?:sk|pk|sess|key|token)-[A-Za-z0-9._-]{6,}\b")


class ConfigError(ValueError):
    """Raised when PulseKeeper configuration is missing or invalid."""


@dataclass(frozen=True)
class StorageConfig:
    dir: Path
    database: str = "state.db"

    @property
    def database_path(self) -> Path:
        return self.dir / self.database


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = False
    bot_token: str | None = None
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"

    def __repr__(self) -> str:
        token_repr = "'***'" if self.bot_token else "None"
        return (
            "TelegramConfig("
            f"enabled={self.enabled!r}, bot_token={token_repr}, "
            f"bot_token_env={self.bot_token_env!r})"
        )


@dataclass(frozen=True)
class VisionConfig:
    enabled: bool = False
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    timeout: int = 60

    def __repr__(self) -> str:
        key_repr = "'***'" if self.api_key else "None"
        return (
            "VisionConfig("
            f"enabled={self.enabled!r}, base_url={self.base_url!r}, "
            f"model={self.model!r}, api_key={key_repr}, "
            f"api_key_env={self.api_key_env!r}, timeout={self.timeout!r})"
        )


@dataclass(frozen=True)
class PulseKeeperConfig:
    storage: StorageConfig
    telegram: TelegramConfig
    llm: LLMConfig
    vision: VisionConfig = VisionConfig()


def load_config(path: Path | str, env_path: Path | str | None = None) -> PulseKeeperConfig:
    """Load PulseKeeper TOML config and optional .env secrets without mutating os.environ."""
    config_path = Path(path)
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Config file not found: {config_path}. "
            "Copy config.toml.example into place or create ~/.pulsekeeper/config.toml."
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a TOML table")

    llm_section = raw.get("llm")
    if not isinstance(llm_section, dict):
        raise ConfigError("Missing required [llm] config section")

    env = _load_env(env_path, config_path=config_path)
    return PulseKeeperConfig(
        storage=_load_storage_config(raw.get("storage"), config_path=config_path),
        telegram=_load_telegram_config(raw.get("telegram"), env=env),
        llm=_load_llm_config(llm_section, env=env),
        vision=_load_vision_config(raw.get("vision"), env=env),
    )


def redact_secret(value: Any, *, secrets: list[str] | tuple[str, ...] = ()) -> Any:
    """Return value with known secrets and secret-looking values masked as '***'."""
    secret_values = tuple(secret for secret in secrets if secret)

    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if _is_secret_key(str(key)) and item not in (None, ""):
                redacted_item = redact_secret(item, secrets=secret_values)
                redacted[key] = (
                    redacted_item if isinstance(item, str) and redacted_item != item else "***"
                )
            else:
                redacted[key] = redact_secret(item, secrets=secret_values)
        return redacted
    if isinstance(value, list):
        return [redact_secret(item, secrets=secret_values) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secret(item, secrets=secret_values) for item in value)
    if isinstance(value, str):
        redacted_text = value
        for secret in secret_values:
            redacted_text = redacted_text.replace(secret, "***")
        return _SECRET_PATTERN.sub("***", redacted_text)
    return value


def _load_llm_config(section: dict[str, Any], *, env: Mapping[str, str]) -> LLMConfig:
    auth_mode = section.get("auth_mode", "api_key")
    if auth_mode not in {"api_key", "subscription"}:
        raise ConfigError("llm.auth_mode must be 'api_key' or 'subscription'")

    model = _required_str(section, "model")
    base_url = section.get("base_url")
    if base_url is None and auth_mode == "subscription":
        base_url = DEFAULT_HERMES_PROXY_BASE_URL
    if auth_mode != "test":
        base_url = _required_str({**section, "base_url": base_url}, "base_url")
    elif base_url is not None and not isinstance(base_url, str):
        raise ConfigError("llm.base_url must be a string")

    api_key = _resolve_api_key(section, env=env)
    if auth_mode == "api_key" and not api_key:
        api_key_env = section.get("api_key_env")
        hint = (
            f" Set {api_key_env} in .env or the process environment."
            if api_key_env
            else " Set llm.api_key_env or llm.api_key."
        )
        raise ConfigError(f"Missing llm api_key for auth_mode='api_key'.{hint}")
    if auth_mode == "subscription":
        api_key = None

    return LLMConfig(
        auth_mode=auth_mode,
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout=_positive_int(section.get("timeout", 60), "llm.timeout"),
        max_tool_iterations=_positive_int(
            section.get("max_tool_iterations", 4), "llm.max_tool_iterations"
        ),
    )


def _load_storage_config(section: Any, *, config_path: Path) -> StorageConfig:
    if section is None:
        return StorageConfig(dir=Path.home() / ".pulsekeeper")
    if not isinstance(section, dict):
        raise ConfigError("storage config section must be a TOML table")

    raw_dir = section.get("dir", str(Path.home() / ".pulsekeeper"))
    if not isinstance(raw_dir, str) or not raw_dir:
        raise ConfigError("storage.dir must be a non-empty string")
    storage_dir = Path(raw_dir).expanduser()
    if not storage_dir.is_absolute():
        storage_dir = config_path.parent / storage_dir

    database = section.get("database", "state.db")
    if not isinstance(database, str) or not database:
        raise ConfigError("storage.database must be a non-empty string")
    if Path(database).is_absolute():
        raise ConfigError("storage.database must be a relative filename")
    return StorageConfig(dir=storage_dir, database=database)


def _load_telegram_config(section: Any, *, env: Mapping[str, str]) -> TelegramConfig:
    if section is None:
        return TelegramConfig(bot_token=env.get("TELEGRAM_BOT_TOKEN"))
    if not isinstance(section, dict):
        raise ConfigError("telegram config section must be a TOML table")

    enabled = section.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("telegram.enabled must be true or false")
    bot_token_env = section.get("bot_token_env", "TELEGRAM_BOT_TOKEN")
    if not isinstance(bot_token_env, str) or not bot_token_env:
        raise ConfigError("telegram.bot_token_env must be a non-empty string")

    direct = section.get("bot_token")
    if direct is not None and (not isinstance(direct, str) or not direct):
        raise ConfigError("telegram.bot_token must be a non-empty string when provided")
    token = direct or env.get(bot_token_env)
    return TelegramConfig(enabled=enabled, bot_token=token, bot_token_env=bot_token_env)


def _load_vision_config(section: Any, *, env: Mapping[str, str]) -> VisionConfig:
    if section is None:
        return VisionConfig()
    if not isinstance(section, dict):
        raise ConfigError("vision config section must be a TOML table")

    enabled = section.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("vision.enabled must be true or false")
    if not enabled:
        return VisionConfig(enabled=False)

    base_url = section.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        raise ConfigError("Missing required vision.base_url")
    model = section.get("model")
    if not isinstance(model, str) or not model:
        raise ConfigError("Missing required vision.model")

    api_key = _resolve_vision_api_key(section, env=env)
    if not api_key:
        api_key_env = section.get("api_key_env", "OPENAI_API_KEY")
        raise ConfigError(
            f"Missing vision api_key. Set {api_key_env} in .env or the process environment."
        )
    api_key_env = section.get("api_key_env", "OPENAI_API_KEY")
    if not isinstance(api_key_env, str) or not api_key_env:
        raise ConfigError("vision.api_key_env must be a non-empty string")
    return VisionConfig(
        enabled=True,
        base_url=base_url,
        model=model,
        api_key=api_key,
        api_key_env=api_key_env,
        timeout=_positive_int(section.get("timeout", 60), "vision.timeout"),
    )


def _load_env(env_path: Path | str | None, *, config_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path(env_path) if env_path is not None else config_path.parent / ".env"
    if path.exists():
        values.update(
            {key: value for key, value in dotenv_values(path).items() if value is not None}
        )
    values.update(os.environ)
    return values


def _resolve_api_key(section: dict[str, Any], *, env: Mapping[str, str]) -> str | None:
    direct = section.get("api_key")
    if isinstance(direct, str) and direct:
        if direct.startswith("${") and direct.endswith("}"):
            return env.get(direct[2:-1])
        return direct
    if direct == "":
        raise ConfigError("llm.api_key must be a non-empty string when provided")
    if direct is not None:
        raise ConfigError("llm.api_key must be a string when provided")

    api_key_env = section.get("api_key_env")
    if api_key_env is None:
        return None
    if not isinstance(api_key_env, str) or not api_key_env:
        raise ConfigError("llm.api_key_env must be a non-empty string")
    return env.get(api_key_env)


def _resolve_vision_api_key(section: dict[str, Any], *, env: Mapping[str, str]) -> str | None:
    direct = section.get("api_key")
    if isinstance(direct, str) and direct:
        if direct.startswith("${") and direct.endswith("}"):
            return env.get(direct[2:-1])
        return direct
    if direct == "":
        raise ConfigError("vision.api_key must be a non-empty string when provided")
    if direct is not None:
        raise ConfigError("vision.api_key must be a string when provided")

    api_key_env = section.get("api_key_env", "OPENAI_API_KEY")
    if not isinstance(api_key_env, str) or not api_key_env:
        raise ConfigError("vision.api_key_env must be a non-empty string")
    return env.get(api_key_env)


def _required_str(section: dict[str, Any], key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"Missing required llm.{key}")
    return value


def _positive_int(value: Any, key: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{key} must be a positive integer")
    return value


def _is_secret_key(key: str) -> bool:
    key_lower = key.lower().replace("-", "_")
    return any(marker in key_lower for marker in _SECRET_KEYS)


__all__ = [
    "ConfigError",
    "DEFAULT_HERMES_PROXY_BASE_URL",
    "PulseKeeperConfig",
    "StorageConfig",
    "TelegramConfig",
    "VisionConfig",
    "load_config",
    "redact_secret",
]
