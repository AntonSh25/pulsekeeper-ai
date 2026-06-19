from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

GoalType: TypeAlias = Literal[
    "lose",
    "maintain",
    "gain",
    "recomp",
    "performance",
    "medical_managed",
    "unspecified",
]
GoalFlag: TypeAlias = Literal["pregnancy", "ed_history", "clinical_supervision"]
TrackingFocus: TypeAlias = Literal[
    "weight",
    "food",
    "sleep",
    "training",
    "symptom",
    "medication",
    "general_journal",
]


class GoalProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_type: GoalType = "unspecified"
    target_rate_kg_per_week: float | None = None
    target_weight_kg: float | None = None
    flags: list[GoalFlag] = Field(default_factory=list)


class TrackingFocusList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TrackingFocus] = Field(default_factory=list)


__all__ = ["GoalFlag", "GoalProfile", "GoalType", "TrackingFocus", "TrackingFocusList"]
