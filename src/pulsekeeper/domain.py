from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator

HealthEntryKind = Literal[
    "food",
    "weight",
    "workout",
    "sleep",
    "symptom",
    "medication",
    "note",
]
HealthEntrySource = Literal["telegram", "cli", "import", "manual"]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


class HealthEntryDraft(BaseModel):
    kind: HealthEntryKind
    note: str | None = None
    logged_at: datetime = Field(default_factory=utc_now)
    value: float | None = None
    unit: str | None = None
    source: HealthEntrySource = "manual"
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata", "data", "metadata_json"),
    )
    schema_version: int = 1

    @field_validator("logged_at", mode="before")
    @classmethod
    def logged_at_must_be_aware(cls, value: Any) -> Any:
        if value is None:
            return utc_now()
        if isinstance(value, datetime):
            return _ensure_aware_datetime(value)
        return value


class HealthEntryPatch(BaseModel):
    kind: HealthEntryKind | None = None
    note: str | None = None
    logged_at: datetime | None = None
    value: float | None = None
    unit: str | None = None
    source: HealthEntrySource | None = None
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata", "data", "metadata_json"),
    )
    schema_version: int | None = None

    @field_validator("logged_at")
    @classmethod
    def logged_at_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _ensure_aware_datetime(value)


class HealthEntry(BaseModel):
    kind: HealthEntryKind
    note: str | None = None
    value: float | None = None
    unit: str | None = None
    logged_at: datetime | date = Field(default_factory=date.today)
    id: int | None = None
    user_id: int | None = None
    source: HealthEntrySource | None = None
    metadata: dict[str, Any] | None = None
    schema_version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    @field_validator("logged_at")
    @classmethod
    def normalize_logged_at(cls, value: datetime | date) -> datetime | date:
        if isinstance(value, datetime):
            return _ensure_aware_datetime(value)
        return value

    @field_validator("created_at", "updated_at", "deleted_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _ensure_aware_datetime(value)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        data = super().model_dump(*args, **kwargs)
        for field_name in (
            "id",
            "user_id",
            "source",
            "metadata",
            "schema_version",
            "created_at",
            "updated_at",
            "deleted_at",
        ):
            if data.get(field_name) is None:
                data.pop(field_name, None)
        return data


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
