from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from pulsekeeper.domain import HealthEntryDraft
from pulsekeeper.storage.health_entries import HealthEntryStore
from pulsekeeper.storage.imports import ImportStore
from pulsekeeper.storage.sqlite import Database


@dataclass(frozen=True)
class AppleHealthImportResult:
    import_id: int
    imported: int
    skipped: int
    unsupported: int


async def import_apple_health_xml(
    db: Database,
    *,
    user_id: int,
    path: str | Path,
) -> AppleHealthImportResult:
    import_store = ImportStore(db)
    entry_store = HealthEntryStore(db)
    import_run = await import_store.start(
        user_id=user_id,
        source="apple_health",
        metadata={"file": Path(path).name},
    )
    imported = 0
    skipped = 0
    unsupported = 0

    for draft in _iter_supported_drafts(Path(path)):
        if await _already_imported(db, user_id=user_id, external_id=draft.external_id):
            await import_store.upsert_item(
                import_id=import_run.id,
                external_id=draft.external_id,
                status="skipped",
                metadata={"reason": "duplicate"},
            )
            skipped += 1
            continue

        await entry_store.append(user_id, draft.entry)
        await import_store.upsert_item(
            import_id=import_run.id,
            external_id=draft.external_id,
            status="imported",
            metadata={"kind": draft.entry.kind},
        )
        imported += 1

    await import_store.finish(import_run.id)
    return AppleHealthImportResult(
        import_id=import_run.id,
        imported=imported,
        skipped=skipped,
        unsupported=unsupported,
    )


@dataclass(frozen=True)
class _ImportedDraft:
    external_id: str
    entry: HealthEntryDraft


def _iter_supported_drafts(path: Path) -> list[_ImportedDraft]:
    root = ElementTree.parse(path).getroot()
    drafts: list[_ImportedDraft] = []
    for element in root:
        if element.tag == "Record":
            draft = _record_to_draft(element.attrib)
        elif element.tag == "Workout":
            draft = _workout_to_draft(element.attrib)
        else:
            draft = None
        if draft is not None:
            drafts.append(draft)
    return drafts


def _record_to_draft(attributes: dict[str, str]) -> _ImportedDraft | None:
    record_type = attributes.get("type", "")
    if record_type == "HKQuantityTypeIdentifierBodyMass":
        value = float(attributes["value"])
        external_id = _record_external_id(attributes)
        return _ImportedDraft(
            external_id=external_id,
            entry=HealthEntryDraft(
                kind="weight",
                note="Apple Health weight",
                logged_at=_parse_apple_datetime(attributes["startDate"]),
                value=value,
                unit=attributes.get("unit") or "kg",
                source="import",
                metadata=_base_metadata(attributes, record_type, external_id),
            ),
        )
    if record_type == "HKCategoryTypeIdentifierSleepAnalysis":
        start = _parse_apple_datetime(attributes["startDate"])
        end = _parse_apple_datetime(attributes["endDate"])
        hours = round((end - start).total_seconds() / 3600, 2)
        external_id = _record_external_id(attributes)
        return _ImportedDraft(
            external_id=external_id,
            entry=HealthEntryDraft(
                kind="sleep",
                note=f"Apple Health sleep: {hours:g} h",
                logged_at=start,
                value=hours,
                unit="h",
                source="import",
                metadata={
                    **_base_metadata(attributes, record_type, external_id),
                    "end_date": attributes.get("endDate"),
                    "sleep_value": attributes.get("value"),
                },
            ),
        )
    if record_type == "HKQuantityTypeIdentifierStepCount":
        steps = float(attributes["value"])
        external_id = _record_external_id(attributes)
        return _ImportedDraft(
            external_id=external_id,
            entry=HealthEntryDraft(
                kind="note",
                note=f"Apple Health steps: {steps:g} steps",
                logged_at=_parse_apple_datetime(attributes["startDate"]),
                value=steps,
                unit="steps",
                source="import",
                metadata=_base_metadata(attributes, record_type, external_id),
            ),
        )
    return None


def _workout_to_draft(attributes: dict[str, str]) -> _ImportedDraft | None:
    activity_type = attributes.get("workoutActivityType")
    if not activity_type:
        return None
    duration = float(attributes.get("duration", "0"))
    duration_unit = attributes.get("durationUnit") or "min"
    external_id = ":".join(
        [
            "workout",
            activity_type,
            attributes.get("startDate", ""),
            attributes.get("endDate", ""),
            attributes.get("duration", ""),
        ]
    )
    metadata: dict[str, Any] = _base_metadata(attributes, activity_type, external_id)
    if attributes.get("totalDistance") is not None:
        metadata["distance"] = float(attributes["totalDistance"])
        metadata["distance_unit"] = attributes.get("totalDistanceUnit")
    label = activity_type.removeprefix("HKWorkoutActivityType") or activity_type
    return _ImportedDraft(
        external_id=external_id,
        entry=HealthEntryDraft(
            kind="workout",
            note=f"Apple Health workout: {label} {duration:g} {duration_unit}",
            logged_at=_parse_apple_datetime(attributes["startDate"]),
            value=duration,
            unit=duration_unit,
            source="import",
            metadata=metadata,
        ),
    )


def _record_external_id(attributes: dict[str, str]) -> str:
    return ":".join(
        [
            "record",
            attributes.get("type", ""),
            attributes.get("startDate", ""),
            attributes.get("endDate", ""),
            attributes.get("value", ""),
        ]
    )


def _base_metadata(attributes: dict[str, str], apple_type: str, external_id: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "apple_health_type": apple_type,
        "external_id": external_id,
    }
    if attributes.get("sourceName") is not None:
        metadata["source_name"] = attributes["sourceName"]
    return metadata


def _parse_apple_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")


async def _already_imported(db: Database, *, user_id: int, external_id: str) -> bool:
    row = await db.fetchone(
        """
        SELECT 1
        FROM import_items AS item
        JOIN imports AS run ON run.id = item.import_id
        WHERE run.user_id = ?
          AND run.source = 'apple_health'
          AND item.external_id = ?
          AND item.status = 'imported'
        LIMIT 1
        """,
        (user_id, external_id),
    )
    return row is not None


__all__ = ["AppleHealthImportResult", "import_apple_health_xml"]
