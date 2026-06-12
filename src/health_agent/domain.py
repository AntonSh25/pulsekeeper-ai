from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

HealthEntryKind = Literal["food", "weight", "workout", "sleep", "note"]


class HealthEntry(BaseModel):
    kind: HealthEntryKind
    note: str
    value: float | None = None
    unit: str | None = None
    logged_at: date = Field(default_factory=date.today)


_WEIGHT_RE = re.compile(r"(?:вес|weight)\s*[:\-]?\s*(\d+(?:[\.,]\d+)?)\s*(кг|kg)?", re.IGNORECASE)
_FOOD_MARKERS = ("завтрак", "обед", "ужин", "перекус", "еда", "съел", "съела", "food")
_WORKOUT_MARKERS = ("тренировка", "зал", "пробежка", "workout", "run", "gym")
_SLEEP_MARKERS = ("сон", "спал", "спала", "sleep")


def parse_health_log(text: str) -> HealthEntry:
    note = text.strip()
    if not note:
        raise ValueError("empty health log")

    weight_match = _WEIGHT_RE.search(note)
    if weight_match:
        value = float(weight_match.group(1).replace(",", "."))
        return HealthEntry(kind="weight", note=note, value=value, unit="kg")

    lower = note.lower()
    if any(marker in lower for marker in _FOOD_MARKERS):
        return HealthEntry(kind="food", note=note)
    if any(marker in lower for marker in _WORKOUT_MARKERS):
        return HealthEntry(kind="workout", note=note)
    if any(marker in lower for marker in _SLEEP_MARKERS):
        return HealthEntry(kind="sleep", note=note)
    return HealthEntry(kind="note", note=note)
