from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_project_has_open_source_contribution_metadata_and_templates():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    bug_report = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.md").read_text(
        encoding="utf-8"
    )
    feature_request = (
        ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.md"
    ).read_text(encoding="utf-8")
    pr_template = (ROOT / ".github" / "pull_request_template.md").read_text(
        encoding="utf-8"
    )

    assert "MIT License" in license_text
    assert "uv sync --extra dev" in contributing
    assert "uv run pytest -q" in contributing
    assert "uv run ruff check ." in contributing
    assert "strict TDD" in contributing
    assert "Do not include real Telegram tokens" in contributing

    assert "name: Bug report" in bug_report
    assert "Expected behavior" in bug_report
    assert "Self-hosting context" in bug_report
    assert "Do not paste real tokens or API keys" in bug_report

    assert "name: Feature request" in feature_request
    assert "Health safety/privacy impact" in feature_request
    assert "Telegram-first" in feature_request

    assert "TDD evidence" in pr_template
    assert "Privacy and secret safety" in pr_template
    assert "Health safety" in pr_template
    assert "uv run pytest -q" in pr_template


def test_architecture_docs_explain_public_mvp_components_and_boundaries():
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    assert "Telegram adapters" in architecture
    assert "Agent tools" in architecture
    assert "SQLite storage" in architecture
    assert "LLM providers" in architecture
    assert "Reminders" in architecture
    assert "Imports and media integrations" in architecture
    assert "Data and secret boundaries" in architecture
    assert "What stays local" in architecture
    assert "What can leave the host" in architecture
    assert "does not diagnose" in architecture


def test_readme_has_three_minute_quickstart_and_demo_artifact_references():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    screenshots = (ROOT / "docs" / "screenshots.md").read_text(encoding="utf-8")

    assert "## Quickstart: under 3 minutes" in readme
    assert "uv sync --extra dev" in readme
    assert "cp .env.example .env" in readme
    assert "uv run pulsekeeper doctor" in readme
    assert "uv run pulsekeeper export jsonl" in readme
    assert "uv run pulsekeeper telegram-run" in readme
    assert "TELEGRAM_BOT_TOKEN" in readme
    assert "PULSEKEEPER_OPENAI_API_KEY" in readme
    assert "Do not paste real tokens" in readme
    assert "~/.pulsekeeper/state.db" in readme
    assert "docs/screenshots.md" in readme

    assert "# Screenshots and GIFs" in screenshots
    assert "assets/demo-telegram-capture.gif" in screenshots
    assert "assets/demo-doctor.png" in screenshots
    assert "placeholder" in screenshots.lower()
    assert "Do not use real health data" in screenshots


def test_post_mvp_product_hardening_plan_starts_at_phase_16():
    plan = (
        ROOT / "docs" / "plans" / "2026-06-post-mvp-product-hardening.md"
    ).read_text(encoding="utf-8")

    assert "# PulseKeeper — Next Phases After MVP" in plan
    assert "## Phase 16" in plan
    assert "16.1" in plan
    assert "Behavior spec" in plan


def test_post_mvp_plan_records_completed_onboarding_slice():
    plan = (
        ROOT / "docs" / "plans" / "2026-06-post-mvp-product-hardening.md"
    ).read_text(encoding="utf-8")

    assert "### ~~16.2 Onboarding flow~~" in plan
    assert "**Objective:** ~~Сделать `/start`" in plan
    assert "**Status:** ✅ Complete" in plan
    assert "`/start` now returns the Telegram-first onboarding text" in plan
    assert "- `/start` is useful to a new user. ✅" in plan
    assert "- It explains what to write. ✅" in plan
    assert "- It mentions privacy/BYO-LLM/local storage. ✅" in plan
    assert "- It includes medical safety boundary. ✅" in plan
    assert "- It does not overwhelm the user. ✅" in plan

def test_implementation_plan_records_completed_mvp_status_consistently():
    plan = (
        ROOT / "docs" / "plans" / "2026-06-13-implementation-plan-and-architecture.md"
    ).read_text(encoding="utf-8")

    assert "Статус: implementation roadmap completed through MVP success criteria" in plan
    assert "2. ~~Map slash commands to deterministic/store-backed paths:~~" in plan
    assert "4. ~~Add `pulsekeeper doctor` checks:~~" in plan
    assert "3. ~~Implement `telegram-run` long polling loop:~~" in plan
    assert "3. ~~send Telegram messages like:~~" in plan
    assert "4. ~~Summary blocks:~~" in plan
    assert "5. ~~Pattern detection:~~" in plan
    assert "6. ~~GitHub Actions:" in plan
    assert "5. ~~Add architecture docs:" in plan
    assert "### Increment 1 — ToolRegistry + schemas\n\n- ~~Add `ToolRegistry`.~~" in plan
    assert "### Increment 7 — Reminders MVP\n\n- ~~ReminderStore.~~" in plan
    assert "- ~~normal text не идёт в parser;~~" in plan
    assert "- ~~fresh DB initializes deterministically;~~" in plan
    assert "- ~~agent can remember stable explicit facts;~~" in plan
    assert "- ~~no live LLM calls in unit tests;~~" in plan
    assert "- ~~“вес 84.2” becomes tool call, not parser result;~~" in plan
    assert "- ~~all imports idempotent;~~" in plan
    assert "   - ~~provider reachable~~;" in plan
    assert "   - ~~list reminders;~~" in plan
    assert "   - ~~flag urgent language carefully;~~" in plan
    assert "   - ~~tests;~~" in plan
    assert "   - ~~adapters;~~" in plan
    assert "   - ~~“вес 84.2”;~~" in plan
    assert "   - ~~name;~~" in plan
    assert "   - ~~input schema;~~" in plan
    assert "   - ~~opens connection;~~" in plan
    assert "   - ~~api_key_env;~~" in plan
    assert "   - ~~/start~~;" in plan
