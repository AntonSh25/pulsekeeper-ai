from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pulsekeeper.llm.agent import DEFAULT_POLICY_PROMPT
from pulsekeeper.reminder_scheduler import reminder_text
from pulsekeeper.storage.reminders import Reminder

ROOT = Path(__file__).resolve().parents[1]


def test_communication_cadence_doc_defines_proactive_boundaries():
    doc = (ROOT / "docs" / "product" / "communication-cadence.md").read_text(
        encoding="utf-8"
    )
    lower_doc = doc.lower()

    assert "daily check-in" in lower_doc
    assert "only if the user opted in" in lower_doc
    assert "weekly review" in lower_doc
    assert "default useful cadence" in lower_doc
    assert "missed logging nudge" in lower_doc
    assert "no guilt" in lower_doc
    assert "no proactive nudges unless configured" in lower_doc
    assert "one small next action" in lower_doc


def test_policy_prompt_embeds_communication_cadence_rules():
    prompt = DEFAULT_POLICY_PROMPT.lower()

    assert "no proactive nudges unless configured" in prompt
    assert "daily check-ins are optional and opt-in only" in prompt
    assert "missed logging nudges are opt-in only" in prompt
    assert "reminders should be short, useful, and non-judgmental" in prompt
    assert "no guilt or shame language in reminders" in prompt
    assert "weekly reviews should suggest at most one small optional next action" in prompt


def test_due_reminder_text_is_short_useful_and_non_shaming():
    reminder = Reminder(
        id=1,
        user_id=42,
        type="weight",
        schedule={"kind": "daily", "time": "09:00"},
        timezone="Europe/Moscow",
        enabled=True,
        last_sent_at=None,
        next_due_at=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
    )

    text = reminder_text(reminder)

    assert text == "Короткое напоминание: можно записать вес одной фразой."
    assert "пропуст" not in text.lower()
    assert "важно" not in text.lower()
    assert "долж" not in text.lower()
