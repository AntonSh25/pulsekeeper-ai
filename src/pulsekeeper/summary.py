from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from pulsekeeper.domain import HealthEntry, HealthEntryKind


class HealthSummary(BaseModel):
    period_start: date
    period_end: date
    total_entries: int
    counts_by_kind: dict[HealthEntryKind, int]
    latest_weight_kg: float | None = None
    highlights: list[str]
    blocks: dict[str, list[str]] = Field(default_factory=dict)
    patterns: list[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        title = _format_title(self.period_start, self.period_end)
        by_kind = _format_counts(self.counts_by_kind)
        lines = [
            f"## PulseKeeper summary: {title}",
            f"- Entries: {self.total_entries}",
            f"- By kind: {by_kind}",
        ]
        if self.latest_weight_kg is not None:
            lines.append(f"- Latest weight: {self.latest_weight_kg:g} kg")
        if not self.highlights:
            lines.append("- Highlights: none")
        else:
            lines.append("- Highlights:")
            lines.extend(f"  - {highlight}" for highlight in self.highlights)
        if self.patterns:
            lines.append("- Patterns:")
            lines.extend(f"  - {pattern}" for pattern in self.patterns)
        return "\n".join(lines)


def summarize_entries(entries: list[HealthEntry], *, start: date, end: date) -> HealthSummary:
    period_entries = [entry for entry in entries if start <= _entry_date(entry) <= end]
    counts = Counter(entry.kind for entry in period_entries)
    latest_weight = _latest_weight(period_entries)
    highlights = [entry.note for entry in period_entries if entry.kind != "weight" and entry.note]
    blocks = _build_blocks(period_entries)
    patterns = _detect_patterns(period_entries, start=start, end=end)

    return HealthSummary(
        period_start=start,
        period_end=end,
        total_entries=len(period_entries),
        counts_by_kind=dict(sorted(counts.items())),
        latest_weight_kg=latest_weight,
        highlights=highlights,
        blocks=blocks,
        patterns=patterns,
    )


def build_summary_prose_prompt(summary: HealthSummary, *, language: str = "en") -> str:
    """Build a safety-bounded prompt for optional LLM prose around deterministic data."""
    title = _format_title(summary.period_start, summary.period_end)
    lines = [
        f"Write a concise Telegram-friendly health journal summary in {language}.",
        "Use only the deterministic facts below.",
        "Do not diagnose, prescribe, or infer causes.",
        (
            "If mentioning symptoms or medications, keep them factual and suggest "
            "professional care only for urgent/risky symptoms."
        ),
        "Period: " + title,
        f"Total entries: {summary.total_entries}",
        f"Counts by kind: {_format_counts(summary.counts_by_kind)}",
    ]
    if summary.blocks:
        lines.append("Blocks:")
        for key, values in summary.blocks.items():
            lines.extend(f"- {key}: {value}" for value in values)
    if summary.patterns:
        lines.append("Cautious patterns:")
        lines.extend(f"- {pattern}" for pattern in summary.patterns)
    lines.append("Return prose only; do not include raw JSON.")
    return "\n".join(lines)


def _latest_weight(entries: list[HealthEntry]) -> float | None:
    for entry in reversed(entries):
        if entry.kind == "weight" and entry.value is not None:
            return entry.value
    return None


def _build_blocks(entries: list[HealthEntry]) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    weights = [entry for entry in entries if entry.kind == "weight" and entry.value is not None]
    if weights:
        latest = weights[-1]
        weight_text = f"Latest {latest.value:g} {latest.unit or 'kg'}"
        if len(weights) >= 2:
            change = latest.value - weights[0].value
            unit = latest.unit or weights[0].unit or "kg"
            weight_text += f"; change {change:+g} {unit} over period."
        else:
            weight_text += "."
        blocks["weight"] = [weight_text]

    for kind, block_key, label in (
        ("food", "food", "food"),
        ("sleep", "sleep", "sleep"),
        ("workout", "workouts", "workout"),
        ("note", "notes", "note"),
    ):
        kind_entries = [entry for entry in entries if entry.kind == kind]
        if not kind_entries:
            continue
        if len(kind_entries) == 1 and kind == "note":
            noun = label
        else:
            noun = f"{label} entry" if len(kind_entries) == 1 else f"{label} entries"
        prefix = f"{len(kind_entries)} {noun}"
        latest_note = kind_entries[-1].note
        if kind in {"food", "note"} and len(kind_entries) == 1 and latest_note:
            blocks[block_key] = [f"{prefix}: {latest_note}"]
        elif latest_note:
            blocks[block_key] = [f"{prefix}; latest: {latest_note}"]
        else:
            blocks[block_key] = [prefix]

    symptom_notes = [entry.note for entry in entries if entry.kind == "symptom" and entry.note]
    medication_notes = [
        entry.note for entry in entries if entry.kind == "medication" and entry.note
    ]
    symptom_medication_lines = []
    if symptom_notes:
        symptom_medication_lines.append(f"Symptoms: {'; '.join(symptom_notes)}")
    if medication_notes:
        symptom_medication_lines.append(f"Medications: {'; '.join(medication_notes)}")
    if symptom_medication_lines:
        blocks["symptoms_medications"] = symptom_medication_lines

    return blocks


def _detect_patterns(entries: list[HealthEntry], *, start: date, end: date) -> list[str]:
    patterns: list[str] = []
    weights = [entry for entry in entries if entry.kind == "weight" and entry.value is not None]
    if len(weights) >= 2:
        change = weights[-1].value - weights[0].value
        if change < 0:
            direction = "decreased"
        elif change > 0:
            direction = "increased"
        else:
            direction = "stayed about the same"
        patterns.append(
            f"Weight {direction} by {abs(change):g} kg over this period; "
            "treat short-term changes cautiously."
        )

    logged_dates = {_entry_date(entry) for entry in entries}
    period_dates = {start + timedelta(days=offset) for offset in range((end - start).days + 1)}
    missing_count = len(period_dates - logged_dates)
    if entries and missing_count:
        day_word = "day" if missing_count == 1 else "days"
        patterns.append(f"No entries for {missing_count} {day_word} in this period.")
    elif entries and len(period_dates) >= 2:
        patterns.append(f"Logged entries on {len(period_dates)} consecutive days.")

    if len(weights) >= 2:
        first_weight = weights[0].value
        last_weight = weights[-1].value
        if first_weight is None or last_weight is None:
            return patterns
        first_date = _entry_date(weights[0])
        last_date = _entry_date(weights[-1])
        change = last_weight - first_weight
        days = max((last_date - first_date).days, 1)
        if abs(change) >= 1.5:
            patterns.append(
                f"Notable weight change: {abs(change):g} kg over {days} days; "
                "review context rather than treating it as a diagnosis."
            )
    return patterns


def _entry_date(entry: HealthEntry) -> date:
    if isinstance(entry.logged_at, datetime):
        return entry.logged_at.date()
    return entry.logged_at


def _format_counts(counts: dict[HealthEntryKind, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{kind} {count}" for kind, count in counts.items())


def _format_title(start: date, end: date) -> str:
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()}..{end.isoformat()}"
