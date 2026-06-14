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


def test_systemd_example_runs_telegram_loop_with_externalized_config_and_secrets():
    unit = (ROOT / "deploy" / "systemd" / "pulsekeeper.service.example").read_text(
        encoding="utf-8"
    )
    deployment_doc = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")

    assert "Description=PulseKeeper Telegram health memory agent" in unit
    assert "User=pulsekeeper" in unit
    assert "EnvironmentFile=/etc/pulsekeeper/pulsekeeper.env" in unit
    assert "PULSEKEEPER_CONFIG=/etc/pulsekeeper/config.toml" in unit
    assert "ExecStart=/usr/local/bin/pulsekeeper telegram-run" in unit
    assert "Restart=on-failure" in unit
    assert "NoNewPrivileges=true" in unit
    assert "TELEGRAM_BOT_TOKEN=" not in unit
    assert "OPENAI_API_KEY=" not in unit

    assert "systemd" in deployment_doc
    assert "pulsekeeper.service.example" in deployment_doc
    assert "/etc/pulsekeeper/pulsekeeper.env" in deployment_doc
    assert "systemctl enable --now pulsekeeper" in deployment_doc


def test_github_actions_ci_runs_quality_build_and_docker_publish_without_plain_secrets():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv run ruff check ." in workflow
    assert "uv run pytest -q" in workflow
    assert "uv build" in workflow
    assert "docker/build-push-action" in workflow
    expected_tag_push_guard = (
        "push: ${{ github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v') }}"
    )
    assert expected_tag_push_guard in workflow
    assert "ghcr.io/${{ github.repository }}" in workflow
    assert "GITHUB_TOKEN" in workflow
    assert "TELEGRAM_BOT_TOKEN" not in workflow
    assert "OPENAI_API_KEY" not in workflow
