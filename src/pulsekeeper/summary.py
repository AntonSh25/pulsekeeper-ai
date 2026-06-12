from __future__ import annotations

from collections import Counter
from datetime import date

from pydantic import BaseModel

from pulsekeeper.domain import HealthEntry, HealthEntryKind


class HealthSummary(BaseModel):
    period_start: date
    period_end: date
    total_entries: int
    counts_by_kind: dict[HealthEntryKind, int]
    latest_weight_kg: float | None = None
    highlights: list[str]

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
            return "\n".join(lines)
        lines.append("- Highlights:")
        lines.extend(f"  - {highlight}" for highlight in self.highlights)
        return "\n".join(lines)


def summarize_entries(entries: list[HealthEntry], *, start: date, end: date) -> HealthSummary:
    period_entries = [entry for entry in entries if start <= entry.logged_at <= end]
    counts = Counter(entry.kind for entry in period_entries)
    latest_weight = _latest_weight(period_entries)
    highlights = [entry.note for entry in period_entries if entry.kind != "weight"]

    return HealthSummary(
        period_start=start,
        period_end=end,
        total_entries=len(period_entries),
        counts_by_kind=dict(sorted(counts.items())),
        latest_weight_kg=latest_weight,
        highlights=highlights,
    )


def _latest_weight(entries: list[HealthEntry]) -> float | None:
    for entry in reversed(entries):
        if entry.kind == "weight" and entry.value is not None:
            return entry.value
    return None


def _format_counts(counts: dict[HealthEntryKind, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{kind} {count}" for kind, count in counts.items())


def _format_title(start: date, end: date) -> str:
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()}..{end.isoformat()}"
