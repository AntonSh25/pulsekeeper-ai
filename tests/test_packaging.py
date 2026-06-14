from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_docker_packaging_files_support_self_hosted_runtime_without_inline_secrets():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.example.yml").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "pulsekeeper" in dockerfile
    assert "PULSEKEEPER_CONFIG=/config/config.toml" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert ".env" in dockerignore
    assert ".pulsekeeper" in dockerignore

    assert "pulsekeeper-ai" in compose
    assert "pulsekeeper telegram-run" in compose
    assert "./config.toml.example:/config/config.toml:ro" in compose
    assert "pulsekeeper-data:/data" in compose
    assert "TELEGRAM_BOT_TOKEN" in compose
    assert "OPENAI_API_KEY" in compose
    assert "CHANGE_ME" not in compose


def test_deployment_doc_explains_persistent_volume_and_doctor_flow():
    deployment_doc = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")

    assert "docker compose" in deployment_doc
    assert "pulsekeeper doctor" in deployment_doc
    assert "pulsekeeper-data" in deployment_doc
    assert "config.toml" in deployment_doc
    assert ".env" in deployment_doc
    assert "Do not commit real secrets" in deployment_doc
