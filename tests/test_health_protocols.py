from __future__ import annotations

from pulsekeeper.llm.agent import DEFAULT_POLICY_PROMPT
from pulsekeeper.llm.tools import build_default_tool_registry
from pulsekeeper.protocols import HEALTH_PROTOCOLS, render_protocol_prompt


def test_protocol_prompt_encodes_initial_health_protocols():
    prompt = render_protocol_prompt(HEALTH_PROTOCOLS)

    for protocol_name in (
        "Weight tracking protocol",
        "Sleep check-in protocol",
        "Workout logging protocol",
        "Food logging protocol",
        "Weekly review protocol",
        "Medication/symptom caution protocol",
    ):
        assert protocol_name in prompt

    assert "avoid overreacting to daily noise" in prompt
    assert "no diagnosis" in prompt.lower()
    assert "avoid fake calorie precision" in prompt
    assert "propose one small next action" in prompt
    assert "professional care" in prompt
    assert "do not give treatment instructions" in prompt


def test_default_agent_policy_includes_health_protocols():
    lower_prompt = DEFAULT_POLICY_PROMPT.lower()

    assert "health protocols" in lower_prompt
    assert "weight tracking protocol" in lower_prompt
    assert "sleep check-in protocol" in lower_prompt
    assert "workout logging protocol" in lower_prompt
    assert "food logging protocol" in lower_prompt
    assert "weekly review protocol" in lower_prompt
    assert "medication/symptom caution protocol" in lower_prompt
    assert "do not give treatment instructions" in lower_prompt


def test_tool_safety_notes_encode_protocol_specific_boundaries():
    registry = build_default_tool_registry()

    log_notes = " ".join(registry.get("log_health_entry").safety_notes).lower()
    summary_notes = " ".join(registry.get("get_health_summary").safety_notes).lower()
    memory_notes = " ".join(registry.get("write_summary_memory").safety_notes).lower()
    reminder_notes = " ".join(registry.get("schedule_reminder").safety_notes).lower()

    assert "daily weight noise" in log_notes
    assert "fake calorie precision" in log_notes
    assert "medication" in log_notes and "symptom" in log_notes
    assert "professional care" in log_notes
    assert "one small next action" in summary_notes
    assert "do not diagnose" in summary_notes
    assert "durable" in memory_notes and "daily noise" in memory_notes
    assert "check-in" in reminder_notes
