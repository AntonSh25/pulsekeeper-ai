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


def test_post_mvp_plan_records_completed_user_goal_slice():
    plan = (
        ROOT / "docs" / "plans" / "2026-06-post-mvp-product-hardening.md"
    ).read_text(encoding="utf-8")

    assert "### ~~16.3 User goal and tracking focus~~" in plan
    assert "**Status:** ✅ Complete" in plan
    assert "`GoalProfile` uses `Field(default_factory=list)`" in plan
    assert "- User can state goal and tracking focus in natural language. ✅" in plan
    assert "- `GoalProfile` хранится в профиле" in plan
    assert "- Tracking focus хранится отдельно от goal_type." in plan
    assert "- `GoalProfile` читается обратно как типизированная структура" in plan


def test_post_mvp_plan_records_completed_communication_cadence_slice():
    plan = (
        ROOT / "docs" / "plans" / "2026-06-post-mvp-product-hardening.md"
    ).read_text(encoding="utf-8")

    assert "### ~~16.4 Communication cadence~~" in plan
    assert "**Objective:** ~~Define when PulseKeeper should proactively communicate.~~" in plan
    assert "**Status:** ✅ Complete" in plan
    assert "communication-cadence.md" in plan
    assert "- No proactive nudges unless configured. ✅" in plan
    assert "- Reminders are useful and short. ✅" in plan
    assert "- Weekly review suggests one small next action. ✅" in plan
    assert "- No guilt/shame language. ✅" in plan


def test_post_mvp_plan_records_completed_prompt_hardening_slice():
    plan = (
        ROOT / "docs" / "plans" / "2026-06-post-mvp-product-hardening.md"
    ).read_text(encoding="utf-8")

    assert "### ~~16.5 Prompt hardening~~" in plan
    assert (
        "**Objective:** ~~Strengthen the default agent prompt with product UX behavior.~~"
        in plan
    )
    assert "**Status:** ✅ Complete" in plan
    assert (
        "tests/test_agent_behavior_prompt.py::"
        "test_policy_prompt_contains_phase_16_5_ux_and_goal_safety_rails" in plan
    )
    assert "- Prompt contains explicit UX rules. ✅" in plan
    assert "- Prompt contains goal-driven safety rails (9.1). ✅" in plan
    assert "- Tests verify no generic lecturing. ✅" in plan
    assert "- Tests verify one-question-max behavior. ✅" in plan
    assert "- Safety constraints remain intact. ✅" in plan


def test_post_mvp_plan_records_completed_behavior_contract_slice():
    plan = (
        ROOT / "docs" / "plans" / "2026-06-post-mvp-product-hardening.md"
    ).read_text(encoding="utf-8")

    assert "### ~~16.6 Behavior test suite~~" in plan
    assert "**Objective:** ~~Lock desired user experience with tests.~~" in plan
    assert "**Status:** ✅ Complete" in plan
    assert "- Tests verify goal-driven rails and hard overrides (16.6). ✅" in plan
    assert "tests/test_agent_behavior_prompt.py" in plan
    assert "tests/test_communication_cadence.py" in plan
    assert "tests/test_aiogram_gateway.py" in plan


def test_post_mvp_plan_marks_phase_16_done_when_criteria_are_satisfied():
    plan = (
        ROOT / "docs" / "plans" / "2026-06-post-mvp-product-hardening.md"
    ).read_text(encoding="utf-8")

    assert "## ~~Phase 16 — Agent behavior & communication design~~" in plan
    assert "**Phase 16 status:** ✅ Complete" in plan
    assert "- ~~`docs/product/agent-behavior.md` exists.~~ ✅" in plan
    assert "- ~~/start feels useful.~~ ✅" in plan
    assert "- ~~Agent prompt has explicit UX rules.~~ ✅" in plan
    assert "- ~~User goals can be captured.~~ ✅" in plan
    assert "- ~~Communication cadence is documented.~~ ✅" in plan
    assert "- ~~Behavior contract tests pass.~~ ✅" in plan
    assert "- ~~Full test suite and ruff are green.~~ ✅" in plan


def test_post_mvp_plan_records_phase_17_1_actionable_doctor_blocker():
    plan = (
        ROOT / "docs" / "plans" / "2026-06-post-mvp-product-hardening.md"
    ).read_text(encoding="utf-8")

    assert "### 17.1 Local live run" in plan
    assert "**Status:** Partially verified" in plan
    assert "`uv run pulsekeeper doctor` now reports an actionable missing-config hint" in plan
    assert "`uv run pulsekeeper telegram-run --max-iterations 0` also exits safely" in plan
    assert "`~/.pulsekeeper/config.toml` is still missing" in plan
    assert "- ~~Doctor passes or reports actionable redacted errors.~~ ✅" in plan
    assert "Next safe step: create `~/.pulsekeeper/config.toml` from `config.toml.example`" in plan


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
