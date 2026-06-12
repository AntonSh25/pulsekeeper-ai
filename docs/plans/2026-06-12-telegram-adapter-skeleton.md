# Telegram Adapter Skeleton Implementation Plan

> **For Hermes:** Use test-driven-development for each code change. Do not write production code before a failing test.

**Goal:** Add the first Telegram-facing adapter skeleton that routes incoming text through the existing PulseKeeper core: parse/log/summary.

**Architecture:** Keep Telegram integration thin and testable. The adapter should not depend on a live Telegram network call yet. It should convert inbound text into domain actions and return outbound text, while storage and core behavior stay in `pulsekeeper.domain`, `pulsekeeper.storage`, and `pulsekeeper.summary`.

**Tech Stack:** Python 3.11, Typer CLI, Pydantic, JSONL storage, pytest, ruff, uv.

---

## Scope for this iteration

Implement only a local, testable Telegram adapter skeleton:

- Recognize Telegram-style messages:
  - regular health log text: `вес 84.2 кг`, `завтрак: омлет`
  - `/summary`
  - `/summary week`
  - `/help`
- Route health log messages into `JsonlHealthLog`.
- Return short Russian responses suitable for Telegram.
- Add CLI command to simulate Telegram input locally: `pulsekeeper telegram-handle "вес 84.2 кг" --file ...`.
- Do not add real Telegram Bot API polling/webhook yet.
- Do not add LLM calls yet.
- Do not add user profiles/reminders yet.

## Acceptance criteria

- `uv run pytest -q` passes.
- `uv run ruff check .` passes.
- Manual smoke test works:
  - `uv run pulsekeeper telegram-handle "вес 84.2 кг" --file /tmp/pulsekeeper.jsonl`
  - `uv run pulsekeeper telegram-handle "/summary" --file /tmp/pulsekeeper.jsonl`
- Adapter is independently unit-tested without real Telegram.
- Existing CLI commands still work.

---

## Task 1: Add adapter behavior tests

**Objective:** Define desired Telegram-style routing before implementation.

**Files:**
- Create: `tests/test_telegram_adapter.py`
- Later create: `src/pulsekeeper/telegram_adapter.py`

**Step 1: Write failing tests**

Add tests for:

```python
def test_telegram_adapter_logs_health_text_and_returns_short_confirmation(tmp_path):
    log_path = tmp_path / "health.jsonl"

    response = handle_telegram_text("вес 84.2 кг", log_path=log_path)

    assert response == "Записал: weight — вес 84.2 кг"
    assert JsonlHealthLog(log_path).read_all()[0].kind == "weight"
```

```python
def test_telegram_adapter_daily_summary_command(tmp_path):
    log_path = tmp_path / "health.jsonl"
    JsonlHealthLog(log_path).append(
        HealthEntry(kind="food", note="завтрак: омлет", logged_at=date.today())
    )

    response = handle_telegram_text("/summary", log_path=log_path)

    assert "## PulseKeeper summary:" in response
    assert "- Entries: 1" in response
    assert "завтрак: омлет" in response
```

```python
def test_telegram_adapter_weekly_summary_command(tmp_path):
    response = handle_telegram_text("/summary week", log_path=tmp_path / "health.jsonl")

    assert "PulseKeeper summary" in response
```

```python
def test_telegram_adapter_help_command():
    response = handle_telegram_text("/help", log_path=Path("unused.jsonl"))

    assert "Напиши вес, еду, тренировку или сон" in response
    assert "/summary" in response
```

**Step 2: Verify RED**

Run:

```bash
uv run pytest tests/test_telegram_adapter.py -q
```

Expected: FAIL because `pulsekeeper.telegram_adapter` does not exist.

---

## Task 2: Implement minimal `telegram_adapter.py`

**Objective:** Make the adapter tests pass with minimal code.

**Files:**
- Create: `src/pulsekeeper/telegram_adapter.py`

**Implementation shape:**

```python
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from pulsekeeper.domain import parse_health_log
from pulsekeeper.storage import JsonlHealthLog
from pulsekeeper.summary import summarize_entries

HELP_TEXT = """Напиши вес, еду, тренировку или сон обычным текстом.
Команды:
/summary — сводка за сегодня
/summary week — сводка за 7 дней
/help — помощь"""


def handle_telegram_text(text: str, *, log_path: Path) -> str:
    message = text.strip()
    if not message:
        return HELP_TEXT
    if message == "/help":
        return HELP_TEXT
    if message.startswith("/summary"):
        return _handle_summary(message, log_path)

    entry = parse_health_log(message)
    JsonlHealthLog(log_path).append(entry)
    return f"Записал: {entry.kind} — {entry.note}"


def _handle_summary(message: str, log_path: Path) -> str:
    end = date.today()
    period = "week" if message == "/summary week" else "day"
    start = end if period == "day" else end - timedelta(days=6)
    entries = JsonlHealthLog(log_path).read_all()
    return summarize_entries(entries, start=start, end=end).to_markdown()
```

**Step 2: Verify GREEN**

Run:

```bash
uv run pytest tests/test_telegram_adapter.py -q
```

Expected: PASS.

**Self-check:**

- Adapter has no Telegram network dependency.
- Adapter does not duplicate parsing/storage/summary logic.
- Adapter returns text only; no side effects except JSONL append for log messages.

---

## Task 3: Add CLI simulation command

**Objective:** Make Telegram adapter usable locally without Telegram credentials.

**Files:**
- Modify: `src/pulsekeeper/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write failing CLI test**

Add:

```python
def test_telegram_handle_command_routes_message_through_adapter(tmp_path):
    log_path = tmp_path / "health.jsonl"

    result = runner.invoke(
        app,
        ["telegram-handle", "вес 84.2 кг", "--file", str(log_path)],
    )

    assert result.exit_code == 0
    assert "Записал: weight" in result.stdout
    assert JsonlHealthLog(log_path).read_all()[0].kind == "weight"
```

**Step 2: Verify RED**

Run:

```bash
uv run pytest tests/test_cli.py::test_telegram_handle_command_routes_message_through_adapter -q
```

Expected: FAIL because command does not exist.

**Step 3: Implement command**

In `src/pulsekeeper/cli.py`, import:

```python
from pulsekeeper.telegram_adapter import handle_telegram_text
```

Add:

```python
@app.command("telegram-handle")
def telegram_handle(
    text: str,
    file: Annotated[Path, typer.Option("--file", "-f")] = DEFAULT_LOG_PATH,
) -> None:
    """Simulate handling one Telegram message locally."""
    typer.echo(handle_telegram_text(text, log_path=file))
```

**Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/test_cli.py::test_telegram_handle_command_routes_message_through_adapter -q
uv run pytest -q
```

Expected: PASS.

---

## Task 4: Add command validation edge cases

**Objective:** Prevent confusing behavior around unknown slash commands.

**Files:**
- Modify: `tests/test_telegram_adapter.py`
- Modify: `src/pulsekeeper/telegram_adapter.py`

**Step 1: Write failing test**

```python
def test_telegram_adapter_unknown_command_returns_help():
    response = handle_telegram_text("/unknown", log_path=Path("unused.jsonl"))

    assert "Не понял команду" in response
    assert "/summary" in response
```

**Step 2: Verify RED**

Run:

```bash
uv run pytest tests/test_telegram_adapter.py::test_telegram_adapter_unknown_command_returns_help -q
```

Expected: FAIL because unknown command currently gets parsed as note/logged.

**Step 3: Implement minimal guard**

In `handle_telegram_text`, before parsing health log:

```python
if message.startswith("/"):
    return f"Не понял команду.\n\n{HELP_TEXT}"
```

**Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/test_telegram_adapter.py -q
uv run pytest -q
```

Expected: PASS.

---

## Task 5: Update README with Telegram adapter simulation

**Objective:** Make the new local Telegram flow discoverable.

**Files:**
- Modify: `README.md`

Add section:

```markdown
## Telegram adapter skeleton

The first Telegram-facing layer can be tested locally without a bot token:

```bash
uv run pulsekeeper telegram-handle "вес 84.2 кг"
uv run pulsekeeper telegram-handle "/summary"
uv run pulsekeeper telegram-handle "/summary week"
```

This command uses the same core parser, JSONL storage, and summary modules that a real Telegram bot/webhook will use later.
```

**Verify:**

```bash
uv run ruff check .
uv run pytest -q
```

---

## Task 6: Full self-review and cleanup

**Objective:** Catch design mistakes before commit/push.

Run these checks:

```bash
uv run pytest -q
uv run ruff check .
uv run pulsekeeper telegram-handle "вес 84.2 кг" --file /tmp/pulsekeeper-smoke.jsonl
uv run pulsekeeper telegram-handle "/summary" --file /tmp/pulsekeeper-smoke.jsonl
git diff --stat
git diff -- src/pulsekeeper/telegram_adapter.py src/pulsekeeper/cli.py tests/test_telegram_adapter.py tests/test_cli.py README.md
```

Self-review checklist:

- [ ] No production code was written before a failing test.
- [ ] Adapter is thin and does not duplicate core parser/storage/summary logic.
- [ ] No live Telegram dependency added yet.
- [ ] No LLM dependency added yet.
- [ ] Unknown slash commands do not pollute health log.
- [ ] Summary behavior remains in `summary.py`, not adapter.
- [ ] Existing commands still work.
- [ ] README examples match actual CLI.

---

## Task 7: Commit and push

**Objective:** Save the completed increment in GitHub.

Run:

```bash
git status --short
git add README.md src/pulsekeeper/cli.py src/pulsekeeper/telegram_adapter.py tests/test_cli.py tests/test_telegram_adapter.py
git commit -m "feat: add telegram adapter skeleton"
git push -u origin HEAD
```

Expected:

- Clean working tree after commit.
- Branch pushed to GitHub.

---

## Deliberately not implementing yet

These are next iterations, not this one:

- Real Telegram Bot API polling or webhook.
- Secrets/config for `TELEGRAM_BOT_TOKEN`.
- LLM-based parsing or summarization.
- Reminders/scheduler.
- Apple Health / Whoop imports.

Implemented in follow-up iteration:

- Multi-user storage routing by Telegram user ID via `--user-id` and `storage_dir/users/<id>/health.jsonl`.

Reason: first we need a clean adapter seam. Then real Telegram integration becomes mostly transport, not business logic.
