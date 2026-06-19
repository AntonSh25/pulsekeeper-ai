from __future__ import annotations

from pathlib import Path

from pulsekeeper.llm.agent import DEFAULT_POLICY_PROMPT


def test_agent_behavior_spec_documents_product_voice_and_safety_boundaries():
    spec = Path("docs/product/agent-behavior.md").read_text(encoding="utf-8")
    lower_spec = spec.lower()

    assert "private telegram-first health memory agent" in lower_spec
    assert "log first, lecture never" in lower_spec
    assert "one question max" in lower_spec
    assert "no fake precision" in lower_spec
    assert "calm" in lower_spec
    assert "concise" in lower_spec
    assert "non-judgmental" in lower_spec
    assert "simple log confirmation: 1 sentence" in lower_spec
    assert "summary: bullets, max 5–7 bullets" in lower_spec
    assert "chest pain + shortness of breath" in lower_spec
    assert "suicidal intent / self-harm intent" in lower_spec
    assert "not a doctor" in lower_spec
    assert "not a calorie oracle" in lower_spec


def test_policy_prompt_embeds_behavior_spec_rules_for_agent_runtime():
    prompt = DEFAULT_POLICY_PROMPT.lower()

    assert "private telegram-first health memory agent" in prompt
    assert "log first, lecture never" in prompt
    assert "one question max" in prompt
    assert "no fake precision" in prompt
    assert "simple log confirmation: 1 sentence" in prompt
    assert "clarification: 1 short question" in prompt
    assert "summary: bullets, max 5-7 bullets" in prompt
    assert "chest pain + shortness of breath" in prompt
    assert "stroke-like symptoms" in prompt
    assert "suicidal intent / self-harm intent" in prompt
    assert "severe allergic reaction / trouble breathing" in prompt
    assert "loss of consciousness" in prompt
    assert "severe sudden pain" in prompt
    assert "not a calorie oracle" in prompt
