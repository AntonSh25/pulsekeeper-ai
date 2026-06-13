from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from pulsekeeper.domain import HealthEntryDraft, HealthEntryPatch
from pulsekeeper.storage.health_entries import HealthEntryStore
from pulsekeeper.storage.sqlite import Database


def run(coro):
    return asyncio.run(coro)


async def create_user(db: Database) -> int:
    cursor = await db.execute("INSERT INTO users DEFAULT VALUES")
    user_id = cursor.lastrowid
    assert user_id is not None
    return user_id


def test_health_entry_draft_and_patch_validate_phase_1_schema_fields():
    logged_at = datetime(2026, 6, 13, 9, 30, tzinfo=UTC)

    draft = HealthEntryDraft(
        kind="symptom",
        note="mild headache",
        logged_at=logged_at,
        value=3,
        unit="severity",
        source="telegram",
        metadata={"severity": 3, "location": "head"},
    )

    assert draft.kind == "symptom"
    assert draft.logged_at == logged_at
    assert draft.source == "telegram"
    assert draft.schema_version == 1
    assert draft.metadata == {"severity": 3, "location": "head"}

    patch = HealthEntryPatch(kind="medication", note="ibuprofen 200mg", metadata={"dose": "200mg"})
    assert patch.kind == "medication"
    assert patch.note == "ibuprofen 200mg"
    assert patch.metadata == {"dose": "200mg"}

    with pytest.raises(ValidationError):
        HealthEntryDraft(kind="mood", note="not in phase 1 schema", logged_at=logged_at)


def test_health_entry_store_append_persists_and_returns_stored_model(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            store = HealthEntryStore(db)
            logged_at = datetime(2026, 6, 13, 8, 15, tzinfo=UTC)

            stored = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="food",
                    note="oatmeal breakfast",
                    logged_at=logged_at,
                    value=350,
                    unit="kcal",
                    metadata={"meal": "breakfast", "confidence": "explicit"},
                ),
            )

            assert stored.id is not None
            assert stored.user_id == user_id
            assert stored.kind == "food"
            assert stored.note == "oatmeal breakfast"
            assert stored.logged_at == logged_at
            assert stored.value == 350
            assert stored.unit == "kcal"
            assert stored.source == "manual"
            assert stored.metadata == {"meal": "breakfast", "confidence": "explicit"}
            assert stored.schema_version == 1
            assert stored.created_at.tzinfo is not None
            assert stored.updated_at.tzinfo is not None
            assert stored.deleted_at is None

            row = await db.fetchone(
                "SELECT metadata_json FROM health_entries WHERE id = ?",
                (stored.id,),
            )
            assert row is not None
            assert row["metadata_json"] == '{"confidence":"explicit","meal":"breakfast"}'
        finally:
            await db.close()

    run(scenario())


def test_health_entry_store_normalizes_timezones_for_ordering_and_ranges(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            store = HealthEntryStore(db)
            utc_plus_two = timezone(timedelta(hours=2))

            first_chronological = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="note",
                    note="late evening with +02 offset",
                    logged_at=datetime(2026, 6, 13, 1, 30, tzinfo=utc_plus_two),
                ),
            )
            second_chronological = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="note",
                    note="midnight utc",
                    logged_at=datetime(2026, 6, 13, 0, 0, tzinfo=UTC),
                ),
            )

            listed = await store.list(
                user_id,
                start=datetime(2026, 6, 12, 23, 0, tzinfo=UTC),
                end=datetime(2026, 6, 13, 0, 30, tzinfo=UTC),
            )

            assert [entry.id for entry in listed] == [
                first_chronological.id,
                second_chronological.id,
            ]
            assert [entry.logged_at for entry in listed] == [
                datetime(2026, 6, 12, 23, 30, tzinfo=UTC),
                datetime(2026, 6, 13, 0, 0, tzinfo=UTC),
            ]
        finally:
            await db.close()

    run(scenario())


def test_health_entry_store_list_filters_user_range_kind_and_deleted_rows(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            other_user_id = await create_user(db)
            store = HealthEntryStore(db)
            start = datetime(2026, 6, 13, 0, 0, tzinfo=UTC)
            mid = start + timedelta(hours=8)
            later_same_time = start + timedelta(hours=12)
            end = start + timedelta(days=1)

            before = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="note",
                    note="before",
                    logged_at=start - timedelta(seconds=1),
                ),
            )
            first = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="weight",
                    note="84.2 kg",
                    value=84.2,
                    unit="kg",
                    logged_at=mid,
                ),
            )
            second = await store.append(
                user_id,
                HealthEntryDraft(kind="symptom", note="headache", logged_at=later_same_time),
            )
            third = await store.append(
                user_id,
                HealthEntryDraft(kind="food", note="lunch", logged_at=later_same_time),
            )
            at_end = await store.append(
                user_id,
                HealthEntryDraft(kind="note", note="exclusive end", logged_at=end),
            )
            await store.append(
                other_user_id,
                HealthEntryDraft(kind="weight", note="other user", logged_at=mid),
            )
            await db.execute(
                "UPDATE health_entries SET deleted_at = ? WHERE id = ?",
                (datetime(2026, 6, 14, tzinfo=UTC).isoformat(), second.id),
            )

            listed = await store.list(user_id, start=start, end=end)
            assert [entry.id for entry in listed] == [first.id, third.id]
            assert before.id not in [entry.id for entry in listed]
            assert at_end.id not in [entry.id for entry in listed]

            weight_only = await store.list(user_id, start=start, end=end, kinds=["weight"])
            assert [entry.id for entry in weight_only] == [first.id]
        finally:
            await db.close()

    run(scenario())


def test_health_entry_store_get_last_is_user_scoped_kind_filtered_and_ignores_deleted(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            other_user_id = await create_user(db)
            store = HealthEntryStore(db)
            base = datetime(2026, 6, 13, 8, 0, tzinfo=UTC)

            first = await store.append(
                user_id,
                HealthEntryDraft(kind="weight", note="84.2 kg", logged_at=base),
            )
            same_time_later_id = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="food",
                    note="breakfast",
                    logged_at=base + timedelta(hours=1),
                ),
            )
            deleted_latest = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="note",
                    note="delete me",
                    logged_at=base + timedelta(hours=2),
                ),
            )
            await store.append(
                other_user_id,
                HealthEntryDraft(
                    kind="note",
                    note="other user latest",
                    logged_at=base + timedelta(hours=3),
                ),
            )
            await store.soft_delete(deleted_latest.id)

            last_any = await store.get_last(user_id)
            last_weight = await store.get_last(user_id, kind="weight")
            last_missing_kind = await store.get_last(user_id, kind="sleep")

            assert last_any is not None
            assert last_any.id == same_time_later_id.id
            assert last_weight is not None
            assert last_weight.id == first.id
            assert last_missing_kind is None
        finally:
            await db.close()

    run(scenario())


def test_health_entry_store_update_only_explicit_fields_and_can_clear_metadata(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            store = HealthEntryStore(db)
            logged_at = datetime(2026, 6, 13, 8, 0, tzinfo=UTC)
            entry = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="food",
                    note="oatmeal",
                    logged_at=logged_at,
                    value=350,
                    unit="kcal",
                    metadata={"meal": "breakfast", "protein_g": 12},
                ),
            )

            updated = await store.update(entry.id, HealthEntryPatch(note="oatmeal and berries"))

            assert updated.id == entry.id
            assert updated.kind == "food"
            assert updated.note == "oatmeal and berries"
            assert updated.value == 350
            assert updated.unit == "kcal"
            assert updated.logged_at == logged_at
            assert updated.metadata == {"meal": "breakfast", "protein_g": 12}
            assert updated.updated_at >= entry.updated_at

            cleared = await store.update(entry.id, HealthEntryPatch(metadata=None))
            assert cleared.metadata is None
        finally:
            await db.close()

    run(scenario())


def test_health_entry_store_update_and_delete_missing_or_deleted_entries_are_controlled(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            store = HealthEntryStore(db)
            entry = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="note",
                    note="temporary",
                    logged_at=datetime(2026, 6, 13, tzinfo=UTC),
                ),
            )

            await store.soft_delete(entry.id)
            await store.soft_delete(entry.id)

            with pytest.raises(LookupError):
                await store.update(entry.id, HealthEntryPatch(note="should not update deleted"))
            with pytest.raises(LookupError):
                await store.update(9999, HealthEntryPatch(note="missing"))
            with pytest.raises(LookupError):
                await store.soft_delete(9999)
        finally:
            await db.close()

    run(scenario())


def test_health_entry_store_search_uses_fts_for_note_metadata_scope_limit_and_deleted_filter(
    tmp_path,
):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            other_user_id = await create_user(db)
            store = HealthEntryStore(db)
            logged_at = datetime(2026, 6, 13, 8, 0, tzinfo=UTC)

            berries = await store.append(
                user_id,
                HealthEntryDraft(kind="food", note="oatmeal with berries", logged_at=logged_at),
            )
            metadata_match = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="symptom",
                    note="after lunch",
                    logged_at=logged_at + timedelta(minutes=1),
                    metadata={"location": "knee", "trigger": "running"},
                ),
            )
            deleted = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="note",
                    note="berries deleted",
                    logged_at=logged_at + timedelta(minutes=2),
                ),
            )
            await store.append(
                other_user_id,
                HealthEntryDraft(
                    kind="food",
                    note="berries other user",
                    logged_at=logged_at + timedelta(minutes=3),
                ),
            )
            await store.soft_delete(deleted.id)

            note_results = await store.search(user_id, "berries", limit=10)
            metadata_results = await store.search(user_id, "running", limit=10)
            limited_results = await store.search(user_id, "oatmeal OR running", limit=1)
            blank_results = await store.search(user_id, "   ")

            assert [entry.id for entry in note_results] == [berries.id]
            assert [entry.id for entry in metadata_results] == [metadata_match.id]
            assert len(limited_results) == 1
            assert blank_results == []
        finally:
            await db.close()

    run(scenario())


def test_health_entry_store_search_handles_natural_punctuation_queries(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            store = HealthEntryStore(db)
            logged_at = datetime(2026, 6, 13, 8, 0, tzinfo=UTC)

            knee_pain = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="symptom",
                    note="knee pain after run",
                    logged_at=logged_at,
                ),
            )
            after_run = await store.append(
                user_id,
                HealthEntryDraft(
                    kind="workout",
                    note="after-run stretching felt good",
                    logged_at=logged_at + timedelta(minutes=1),
                ),
            )

            punctuation_results = await store.search(user_id, "knee pain?", limit=10)
            hyphen_results = await store.search(user_id, "after-run", limit=10)
            no_token_results = await store.search(user_id, " ? - ", limit=10)

            assert knee_pain.id in [entry.id for entry in punctuation_results]
            assert {entry.id for entry in hyphen_results} == {after_run.id, knee_pain.id}
            assert no_token_results == []
        finally:
            await db.close()

    run(scenario())
