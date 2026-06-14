from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HealthProtocol:
    name: str
    steps: tuple[str, ...]


HEALTH_PROTOCOLS: tuple[HealthProtocol, ...] = (
    HealthProtocol(
        name="Weight tracking protocol",
        steps=(
            "log weight exactly as provided with unit and time when available",
            "notice multi-entry trends only when enough stored data exists",
            "avoid overreacting to daily noise or encouraging unsafe weight loss",
        ),
    ),
    HealthProtocol(
        name="Sleep check-in protocol",
        steps=(
            "capture duration, timing, and user-described quality as facts",
            "connect patterns cautiously only when repeated data exists",
            "no diagnosis or claims about sleep disorders",
        ),
    ),
    HealthProtocol(
        name="Workout logging protocol",
        steps=(
            "capture type, duration, intensity, and recovery context when provided",
            "connect workouts to recovery, sleep, or weight only when enough data exists",
            "avoid prescriptive training or medical advice",
        ),
    ),
    HealthProtocol(
        name="Food logging protocol",
        steps=(
            "capture meal context and user-provided details",
            "avoid fake calorie precision unless the user explicitly tracks calories or macros",
            "avoid shame, coercive restriction language, or invented nutrition facts",
        ),
    ),
    HealthProtocol(
        name="Weekly review protocol",
        steps=(
            "summarize changes using stored facts only",
            "identify missing data and weak evidence explicitly",
            "propose one small next action without diagnosis or prescription",
        ),
    ),
    HealthProtocol(
        name="Medication/symptom caution protocol",
        steps=(
            "log medication and symptom facts exactly as provided",
            "flag urgent language carefully and recommend professional care when appropriate",
            "do not give treatment instructions, dosing advice, or medication stop/start advice",
        ),
    ),
)


def render_protocol_prompt(protocols: tuple[HealthProtocol, ...] = HEALTH_PROTOCOLS) -> str:
    lines = ["Health protocols:"]
    for protocol in protocols:
        lines.append(f"- {protocol.name}:")
        lines.extend(f"  - {step}" for step in protocol.steps)
    return "\n".join(lines)


__all__ = ["HEALTH_PROTOCOLS", "HealthProtocol", "render_protocol_prompt"]
