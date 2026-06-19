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


def test_policy_prompt_contains_phase_16_5_ux_and_goal_safety_rails():
    prompt = " ".join(DEFAULT_POLICY_PROMPT.lower().split())

    assert "if the user provides a clear health log" in prompt
    assert "call the relevant tool" in prompt
    assert "respond with one short confirmation" in prompt
    assert "do not provide generic wellness education unless explicitly asked" in prompt
    assert "prefer structured logging over free-form chat" in prompt
    assert "if uncertain, say what is known and what is unknown" in prompt
    assert (
        "do not infer precise calories, macros, diagnoses, causes, or medication advice"
        in prompt
    )
    assert "focus on observed patterns and data gaps" in prompt
    assert "end longer summaries with at most one small optional next action" in prompt

    assert "personalize to the user's goalprofile" in prompt
    assert "do not blanket-refuse deficit talk" in prompt
    assert "0.25-1.0% body weight / week" in prompt
    assert "0.25-0.5% body weight / week" in prompt
    assert "do not endorse intake below ~1200 kcal/day" in prompt
    assert "not silently executed" in prompt
    assert "not silently clamped" in prompt
    assert "underweight -> do not support further loss" in prompt
    assert "pregnancy -> no weight-loss deficit" in prompt
    assert "declared ed history / clinical_supervision -> defer to professional" in prompt
    assert "net-kcal/deficit shown only when goal-relevant" in prompt
    assert "set ed_history only from an explicit user statement" in prompt
    assert "never infer these flags from weight, food, symptoms, or tone" in prompt
