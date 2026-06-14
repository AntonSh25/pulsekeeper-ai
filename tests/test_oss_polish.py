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
