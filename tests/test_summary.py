from datetime import date

from pulsekeeper.domain import HealthEntry
from pulsekeeper.summary import summarize_entries


def test_daily_summary_groups_entries_and_keeps_latest_weight():
    entries = [
        HealthEntry(
            kind="weight",
            note="вес 84.2 кг",
            value=84.2,
            unit="kg",
            logged_at=date(2026, 6, 12),
        ),
        HealthEntry(kind="food", note="завтрак: омлет", logged_at=date(2026, 6, 12)),
        HealthEntry(kind="workout", note="зал 45 минут", logged_at=date(2026, 6, 12)),
        HealthEntry(
            kind="weight",
            note="вес 83.9 кг",
            value=83.9,
            unit="kg",
            logged_at=date(2026, 6, 12),
        ),
        HealthEntry(kind="sleep", note="сон 7 часов", logged_at=date(2026, 6, 11)),
    ]

    summary = summarize_entries(entries, start=date(2026, 6, 12), end=date(2026, 6, 12))

    assert summary.period_start == date(2026, 6, 12)
    assert summary.period_end == date(2026, 6, 12)
    assert summary.total_entries == 4
    assert summary.counts_by_kind == {"food": 1, "weight": 2, "workout": 1}
    assert summary.latest_weight_kg == 83.9
    assert summary.highlights == ["завтрак: омлет", "зал 45 минут"]


def test_summary_markdown_is_short_and_human_readable():
    entries = [
        HealthEntry(kind="food", note="ужин: рыба и салат", logged_at=date(2026, 6, 12)),
        HealthEntry(kind="sleep", note="сон 6.5 часов", logged_at=date(2026, 6, 12)),
    ]

    summary = summarize_entries(entries, start=date(2026, 6, 12), end=date(2026, 6, 12))

    assert summary.to_markdown() == (
        "## PulseKeeper summary: 2026-06-12\n"
        "- Entries: 2\n"
        "- By kind: food 1, sleep 1\n"
        "- Highlights:\n"
        "  - ужин: рыба и салат\n"
        "  - сон 6.5 часов"
    )


def test_empty_summary_has_no_highlights():
    summary = summarize_entries([], start=date(2026, 6, 12), end=date(2026, 6, 12))

    assert summary.total_entries == 0
    assert summary.counts_by_kind == {}
    assert summary.latest_weight_kg is None
    assert summary.highlights == []
    assert summary.to_markdown() == (
        "## PulseKeeper summary: 2026-06-12\n"
        "- Entries: 0\n"
        "- By kind: none\n"
        "- Highlights: none"
    )
