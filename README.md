# PulseKeeper

Open-source Telegram-first health agent with BYOK LLM support.

## Product direction

PulseKeeper is a privacy-first personal health memory agent: a minimal Hermes-like domain agent platform for health. It receives Telegram messages, lets a BYOK model choose typed health tools, validates tool arguments, stores health memory locally, and produces safe summaries, reminders, and follow-ups.

Core principles:

- **Telegram-first**: fastest possible capture UX.
- **Hermes-like agent architecture**: gateway, agent runtime, typed tools, memory, scheduler, policies, and domain protocols.
- **Tool-calling-first**: natural-language user interaction goes through model-selected typed tools, not hand-written parsers.
- **BYOK**: users bring their own LLM API key.
- **Self-host friendly**: local files/database first, no mandatory cloud.
- **Privacy-first**: explicit data ownership and export.
- **Agentic summaries**: not just calorie tracking; it should notice patterns over time.
- **Careful health behavior**: summarize patterns, do not diagnose.

## Target architecture

```text
Telegram gateway
  -> AgentRuntime
  -> BYOK model runtime with typed tools
  -> ToolExecutor + Pydantic validation
  -> SQLite state database / memory / scheduler / integrations
  -> Telegram response
```

The repository still contains bootstrap CLI/parser code from the first scaffold. That code is useful for deterministic tests and early storage/summary smoke checks, but it is not the intended user-interaction architecture. Telegram/user-facing natural-language input is now blocked unless it goes through `AgentRuntime` and typed tools.

## MVP scope

- Telegram gateway for user messages.
- Agent runtime with typed health tools.
- Hermes-like local SQLite state database with typed stores and migrations.
- BYOK model provider configuration.
- Daily/weekly summaries through the same tool system.
- Reminder/scheduler capability.
- Later: Apple Health / Whoop imports, image food logging, charts.


## Storage model

PulseKeeper should use a canonical local SQLite state database, similar in spirit to Hermes `~/.hermes/state.db`.

Default layout:

```text
~/.pulsekeeper/
  state.db
  config.toml
  .env
  exports/
  media/
  logs/
```

The database layer should expose typed stores for health entries, profile memory, preferences, conversation state, summary memory, reminders, gateway offsets, and imports. JSONL/CSV/Markdown are export/debug formats, not the primary runtime database.

## Initial health tools

- `log_health_entry`
- `get_health_summary`
- `ask_clarifying_question`
- `update_last_entry`
- `delete_last_entry`
- `set_user_profile_fact`
- `search_health_memory`
- `write_summary_memory`
- `schedule_reminder`

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run pulsekeeper --help
```

## Bootstrap CLI / dev smoke checks

These commands exist from the first scaffold and are useful for local testing while the agent runtime is being built. They should not be treated as the final user UX.

Parse one message without writing it:

```bash
uv run pulsekeeper parse "вес 84.2 кг"
```

Append a local health log entry:

```bash
uv run pulsekeeper log "завтрак: омлет 3 яйца, кофе"
```

Print a daily or weekly markdown summary:

```bash
uv run pulsekeeper summary --date 2026-06-12
uv run pulsekeeper summary --date 2026-06-12 --period week
```

The bootstrap commands still use `~/.pulsekeeper/health.jsonl` unless `--file` is passed. The intended runtime database is `~/.pulsekeeper/state.db`; JSONL is legacy scaffold/export compatibility.

## Telegram seams without live credentials

The current Telegram-facing seams can be tested locally without a bot token. Natural-language messages require a configured model runtime; deterministic commands still work as smoke checks:

```bash
uv run pulsekeeper telegram-handle "вес 84.2 кг"   # asks for BYOK model runtime; does not parse/log
uv run pulsekeeper telegram-handle "/summary"
uv run pulsekeeper telegram-handle "/summary week"
```

For Telegram-style multi-user routing, pass `--user-id`. PulseKeeper stores each user's log separately under `~/.pulsekeeper/users/<user-id>/health.jsonl`:

```bash
uv run pulsekeeper telegram-handle "вес 84.2 кг" --user-id 111
uv run pulsekeeper telegram-handle "/summary" --user-id 111
```

Use `--storage-dir path/to/storage` to test this without touching your real local data.

A transport-level Telegram Bot API update can also be tested without network calls:

```bash
uv run pulsekeeper telegram-update '{"message":{"chat":{"id":555},"from":{"id":111},"text":"вес 84.2 кг"}}'
```

The transport layer extracts `chat.id`, `from.id`, and `text`, then delegates to the adapter. Natural-language health input is only logged when an agent model returns a typed tool call.

A single polling iteration can be tested from a fixture without a bot token:

```bash
cat > /tmp/pulsekeeper-update.json <<'JSON'
{"ok": true, "result": [{"update_id": 42, "message": {"chat": {"id": 555}, "from": {"id": 111}, "text": "вес 84.2 кг"}}]}
JSON
uv run pulsekeeper telegram-poll-once --fixture /tmp/pulsekeeper-update.json --offset 41
```

This exercises the polling path while keeping live Telegram credentials out of tests and logs.
