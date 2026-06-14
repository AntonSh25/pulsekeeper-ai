# PulseKeeper architecture

PulseKeeper is a self-hosted, Telegram-first health memory agent. The MVP is intentionally small: a Telegram gateway, a BYOK LLM/tool-calling runtime, local SQLite memory, deterministic summaries, reminders, and import/media seams that keep private data understandable.

## High-level flow

```text
Telegram update
  -> Telegram adapters
  -> Agent runtime
  -> Agent tools
  -> SQLite storage
  -> Telegram reply
```

Normal user text is routed through the agent runtime and typed tools. Deterministic slash commands such as `/today`, `/week`, `/undo`, `/profile`, and reminder commands use the same store-backed domain paths when a model call is not needed.

## Telegram adapters

The Telegram layer is split into testable seams:

- update parsing extracts chat ID, user ID, message ID, text, and attachment metadata;
- polling persists offsets so restarts do not reprocess old updates;
- delivery sends concise Telegram-safe replies;
- private-chat and owner allowlist guards reject unexpected users;
- logs and diagnostics redact bot tokens and provider keys.

The adapters should not infer health meaning from free text. They normalize provider payloads and delegate health interpretation to the runtime/tools.

## Agent runtime

The runtime builds a message context, loads user profile/memory, exposes the available tool registry, executes validated tool calls, and returns a user-facing response. This keeps product logic transport-neutral: the same runtime can serve Telegram, CLI smoke paths, and future gateways.

Health safety is part of the runtime contract. PulseKeeper summarizes patterns and facts, asks clarifying questions when needed, and does not diagnose, prescribe treatment, or invent medical certainty.

## Agent tools

Agent tools are typed, registered capabilities with descriptions, schemas, permissions, and safety notes. MVP tools include:

- `log_health_entry` for food, weight, workout, sleep, symptom, medication, and note events;
- summary tools for daily, weekly, monthly, and custom windows;
- profile and preference memory tools;
- search and durable summary-memory tools;
- correction and delete-last-entry tools backed by auditable store updates;
- reminder scheduling, listing, and cancellation tools.

Tools write only through store interfaces. They do not directly write JSONL files, call Telegram, or bypass validation.

## SQLite storage

SQLite storage is the canonical local state layer. The default layout is under `~/.pulsekeeper/`:

```text
state.db       # canonical SQLite database
config.toml    # non-secret config
.env           # local BYOK secrets, never committed
exports/       # user export files
media/         # locally stored Telegram media
logs/          # redacted logs
```

Explicit migrations initialize users, gateway accounts, health entries, FTS search, profile facts, preferences, conversation state, summary memory, reminders, Telegram offsets, and import idempotency tables. Stores handle transactions, UTC datetime text, soft deletes, FTS-safe search, and migration idempotency.

Legacy JSONL remains only for isolated dev/export compatibility and is not the runtime storage path.

## LLM providers

PulseKeeper is BYOK by default. Provider config selects the model provider, model name, OpenAI-compatible base URL, timeout, and API-key environment variable. Unit tests use fake providers and never call live LLM APIs.

Provider setup is intentionally explicit:

- missing API keys produce actionable errors;
- `pulsekeeper config` and `pulsekeeper doctor` redact secrets;
- live reachability checks are opt-in diagnostics;
- tool-calling is the preferred path for natural-language health entries.

## Reminders

Reminders are stored in SQLite with schedule metadata, timezone, enabled state, last-sent time, and next due time. The scheduler has a one-iteration primitive plus a loop wrapper so due-item processing can be tested without a live daemon.

Downtime catch-up sends a reminder once rather than replaying every missed occurrence. Telegram delivery is injected as a plain callable in tests and wired to the Telegram client in the runtime command path.

## Imports and media integrations

Imports and media are optional seams, not mandatory cloud dependencies.

- Apple Health XML imports weight, sleep, workouts, and steps through `HealthEntryStore` with `source="import"`.
- External IDs are recorded in `ImportStore` so reruns skip duplicates.
- Telegram photo handling stores local media bytes/metadata and passes concise attachment context into the agent.
- Vision-provider config is disabled by default and follows BYOK/redaction rules.

Imports and media integrations should start from local fixtures and plain metadata before adding live provider calls.

## Data and secret boundaries

### What stays local

- SQLite `state.db` health entries, profiles, preferences, reminders, offsets, imports, and summary memory.
- `~/.pulsekeeper/.env` secrets.
- Local exports, media files, and redacted logs.
- Deterministic summary data before any optional LLM prose layer.

### What can leave the host

- Telegram messages and replies necessarily pass through Telegram.
- If a BYOK LLM provider is configured, selected message context, relevant memory, attachment metadata, and tool schemas can be sent to that provider.
- If an optional vision provider is enabled later, selected local image bytes or derived image content can be sent to that provider.

Diagnostics, examples, tests, and logs must not print real Telegram tokens, LLM API keys, or inline secret values.

## Extension rules

New production behavior should be added with strict TDD: write the failing test first, verify the expected failure, implement the smallest passing change, run targeted tests, then run the full suite and lint. New integrations should preserve the transport-neutral seams and keep privacy, BYOK, and health-safety boundaries visible to users.
