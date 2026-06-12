from datetime import date

import pytest

from health_agent.domain import HealthEntry, parse_health_log


def test_parse_weight_log_from_russian_text():
    entry = parse_health_log("вес 84.2 кг")

    assert entry.kind == "weight"
    assert entry.value == 84.2
    assert entry.unit == "kg"
    assert entry.note == "вес 84.2 кг"


def test_parse_food_log_keeps_original_note():
    entry = parse_health_log("завтрак: омлет 3 яйца, кофе")

    assert entry.kind == "food"
    assert entry.note == "завтрак: омлет 3 яйца, кофе"
    assert entry.value is None
    assert entry.unit is None


def test_health_entry_serializes_date_as_iso_string():
    entry = HealthEntry(kind="workout", note="зал 45 минут", logged_at=date(2026, 6, 12))

    assert entry.model_dump(mode="json") == {
        "kind": "workout",
        "note": "зал 45 минут",
        "value": None,
        "unit": None,
        "logged_at": "2026-06-12",
    }


def test_rejects_empty_log():
    with pytest.raises(ValueError, match="empty"):
        parse_health_log("   ")
