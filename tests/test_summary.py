from datetime import date

from pulsekeeper.domain import HealthEntry
from pulsekeeper.summary import build_summary_prose_prompt, summarize_entries


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


def test_summary_builds_health_blocks_and_cautious_patterns():
    entries = [
        HealthEntry(
            kind="weight",
            note="вес 84.2 кг",
            value=84.2,
            unit="kg",
            logged_at=date(2026, 6, 8),
        ),
        HealthEntry(
            kind="weight",
            note="вес 83.7 кг",
            value=83.7,
            unit="kg",
            logged_at=date(2026, 6, 14),
        ),
        HealthEntry(kind="food", note="завтрак: омлет", logged_at=date(2026, 6, 14)),
        HealthEntry(
            kind="sleep",
            note="сон 6.5 часов",
            value=6.5,
            unit="h",
            logged_at=date(2026, 6, 13),
        ),
        HealthEntry(
            kind="workout",
            note="зона 2 45 минут",
            value=45,
            unit="min",
            logged_at=date(2026, 6, 12),
        ),
        HealthEntry(kind="symptom", note="болела голова вечером", logged_at=date(2026, 6, 12)),
        HealthEntry(kind="medication", note="принял магний", logged_at=date(2026, 6, 12)),
        HealthEntry(kind="note", note="много работы", logged_at=date(2026, 6, 11)),
    ]

    summary = summarize_entries(entries, start=date(2026, 6, 8), end=date(2026, 6, 14))

    assert summary.blocks == {
        "weight": ["Latest 83.7 kg; change -0.5 kg over period."],
        "food": ["1 food entry: завтрак: омлет"],
        "sleep": ["1 sleep entry; latest: сон 6.5 часов"],
        "workouts": ["1 workout entry; latest: зона 2 45 минут"],
        "symptoms_medications": [
            "Symptoms: болела голова вечером",
            "Medications: принял магний",
        ],
        "notes": ["1 note: много работы"],
    }
    assert summary.patterns == [
        "Weight decreased by 0.5 kg over this period; treat short-term changes cautiously.",
        "No entries for 2 days in this period.",
    ]
    assert "- Patterns:" in summary.to_markdown()
    assert (
        "  - Weight decreased by 0.5 kg over this period; "
        "treat short-term changes cautiously."
    ) in summary.to_markdown()


def test_summary_prose_prompt_wraps_structured_data_with_health_safety_bounds():
    entries = [
        HealthEntry(
            kind="weight",
            note="вес 84.2 кг",
            value=84.2,
            unit="kg",
            logged_at=date(2026, 6, 8),
        ),
        HealthEntry(
            kind="weight",
            note="вес 83.7 кг",
            value=83.7,
            unit="kg",
            logged_at=date(2026, 6, 14),
        ),
        HealthEntry(kind="symptom", note="болела голова вечером", logged_at=date(2026, 6, 12)),
    ]
    summary = summarize_entries(entries, start=date(2026, 6, 8), end=date(2026, 6, 14))

    prompt = build_summary_prose_prompt(summary, language="ru")

    assert "Write a concise Telegram-friendly health journal summary in ru." in prompt
    assert "Do not diagnose, prescribe, or infer causes." in prompt
    assert "If mentioning symptoms or medications, keep them factual" in prompt
    assert "Period: 2026-06-08..2026-06-14" in prompt
    assert "Total entries: 3" in prompt
    assert "weight: Latest 83.7 kg; change -0.5 kg over period." in prompt
    assert "symptoms_medications: Symptoms: болела голова вечером" in prompt
    assert (
        "Weight decreased by 0.5 kg over this period; treat short-term changes cautiously."
        in prompt
    )
    assert "Return prose only; do not include raw JSON." in prompt


def test_summary_detects_logging_streaks_and_notable_weight_changes():
    entries = [
        HealthEntry(
            kind="weight",
            note="вес 84.2 кг",
            value=84.2,
            unit="kg",
            logged_at=date(2026, 6, 10),
        ),
        HealthEntry(kind="food", note="ужин", logged_at=date(2026, 6, 10)),
        HealthEntry(kind="sleep", note="сон 7 часов", logged_at=date(2026, 6, 11)),
        HealthEntry(kind="workout", note="зал", logged_at=date(2026, 6, 12)),
        HealthEntry(
            kind="weight",
            note="вес 82.6 кг",
            value=82.6,
            unit="kg",
            logged_at=date(2026, 6, 12),
        ),
    ]

    summary = summarize_entries(entries, start=date(2026, 6, 10), end=date(2026, 6, 12))

    assert "Logged entries on 3 consecutive days." in summary.patterns
    assert (
        "Notable weight change: 1.6 kg over 2 days; "
        "review context rather than treating it as a diagnosis."
    ) in summary.patterns
