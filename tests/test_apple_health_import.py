from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from pulsekeeper.storage.health_entries import HealthEntryStore
from pulsekeeper.storage.imports import ImportStore
from pulsekeeper.storage.sqlite import Database


def run(coro):
    return asyncio.run(coro)


async def create_user(db: Database) -> int:
    cursor = await db.execute("INSERT INTO users DEFAULT VALUES")
    user_id = cursor.lastrowid
    assert user_id is not None
    return user_id


def test_apple_health_xml_imports_weight_sleep_workout_and_steps_idempotently(tmp_path):
    async def scenario() -> None:
        from pulsekeeper.importers.apple_health import import_apple_health_xml

        export_path = tmp_path / "apple_export.xml"
        export_path.write_text(
            """<?xml version='1.0' encoding='UTF-8'?>
<HealthData>
  <Record
    type="HKQuantityTypeIdentifierBodyMass"
    sourceName="Health"
    unit="kg"
    creationDate="2026-06-01 07:00:00 +0000"
    startDate="2026-06-01 07:00:00 +0000"
    endDate="2026-06-01 07:00:00 +0000"
    value="84.2"/>
  <Record
    type="HKCategoryTypeIdentifierSleepAnalysis"
    sourceName="Watch"
    startDate="2026-06-01 22:30:00 +0000"
    endDate="2026-06-02 06:45:00 +0000"
    value="HKCategoryValueSleepAnalysisAsleepCore"/>
  <Record
    type="HKQuantityTypeIdentifierStepCount"
    sourceName="Watch"
    unit="count"
    startDate="2026-06-02 00:00:00 +0000"
    endDate="2026-06-02 23:59:59 +0000"
    value="12345"/>
  <Workout
    workoutActivityType="HKWorkoutActivityTypeRunning"
    sourceName="Watch"
    duration="45"
    durationUnit="min"
    totalDistance="7.2"
    totalDistanceUnit="km"
    startDate="2026-06-03 06:15:00 +0000"
    endDate="2026-06-03 07:00:00 +0000"/>
</HealthData>
""",
            encoding="utf-8",
        )

        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            result = await import_apple_health_xml(db, user_id=user_id, path=export_path)
            second_result = await import_apple_health_xml(db, user_id=user_id, path=export_path)

            assert result.imported == 4
            assert result.skipped == 0
            assert second_result.imported == 0
            assert second_result.skipped == 4

            entries = await HealthEntryStore(db).list(
                user_id,
                start=datetime(2026, 6, 1, tzinfo=UTC),
                end=datetime(2026, 6, 4, tzinfo=UTC),
            )
            assert [(entry.kind, entry.value, entry.unit) for entry in entries] == [
                ("weight", 84.2, "kg"),
                ("sleep", 8.25, "h"),
                ("note", 12345.0, "steps"),
                ("workout", 45.0, "min"),
            ]
            assert entries[0].source == "import"
            assert entries[0].metadata == {
                "apple_health_type": "HKQuantityTypeIdentifierBodyMass",
                "external_id": (
                    "record:HKQuantityTypeIdentifierBodyMass:"
                    "2026-06-01 07:00:00 +0000:"
                    "2026-06-01 07:00:00 +0000:84.2"
                ),
                "source_name": "Health",
            }
            assert entries[1].note == "Apple Health sleep: 8.25 h"
            assert entries[2].note == "Apple Health steps: 12345 steps"
            assert entries[3].metadata == {
                "apple_health_type": "HKWorkoutActivityTypeRunning",
                "distance": 7.2,
                "distance_unit": "km",
                "external_id": (
                    "workout:HKWorkoutActivityTypeRunning:"
                    "2026-06-03 06:15:00 +0000:"
                    "2026-06-03 07:00:00 +0000:45"
                ),
                "source_name": "Watch",
            }

            runs = await db.fetchall("SELECT * FROM imports ORDER BY id ASC")
            assert [row["source"] for row in runs] == ["apple_health", "apple_health"]
            second_items = await ImportStore(db).list_items(second_result.import_id)
            assert {item.status for item in second_items} == {"skipped"}
        finally:
            await db.close()

    run(scenario())
