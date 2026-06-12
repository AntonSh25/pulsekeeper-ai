import json
from datetime import date

from health_agent.domain import HealthEntry
from health_agent.storage import JsonlHealthLog


def test_append_entry_writes_one_json_line(tmp_path):
    log = JsonlHealthLog(tmp_path / "health.jsonl")

    log.append(
        HealthEntry(
            kind="weight",
            note="вес 84.2 кг",
            value=84.2,
            unit="kg",
            logged_at=date(2026, 6, 12),
        )
    )

    lines = (tmp_path / "health.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "kind": "weight",
        "note": "вес 84.2 кг",
        "value": 84.2,
        "unit": "kg",
        "logged_at": "2026-06-12",
    }


def test_read_all_returns_entries_in_file_order(tmp_path):
    log = JsonlHealthLog(tmp_path / "health.jsonl")
    first = HealthEntry(kind="food", note="завтрак: омлет", logged_at=date(2026, 6, 12))
    second = HealthEntry(kind="workout", note="зал 45 минут", logged_at=date(2026, 6, 13))

    log.append(first)
    log.append(second)

    assert log.read_all() == [first, second]


def test_read_all_missing_file_returns_empty_list(tmp_path):
    log = JsonlHealthLog(tmp_path / "missing.jsonl")

    assert log.read_all() == []
