# PulseKeeper Project Implementation Roadmap

> **For Hermes:** Use subagent-driven-development skill to implement this plan increment-by-increment. Keep strict TDD for production code.

**Goal:** Build PulseKeeper into a Telegram-first, BYOK, self-host-friendly health memory agent.

**Architecture:** PulseKeeper is a minimal Hermes-like domain agent platform for health. Telegram and future gateways turn incoming events into agent messages; a BYOK model runtime chooses typed health tools; tools validate arguments with Pydantic and perform deterministic storage, memory, summary, reminder, and integration actions. User interaction must go through the agent runtime and typed tools, not through hand-written parsers.

**Tech Stack:** Python 3.11, uv, Typer, Pydantic, pytest, ruff, SQLite canonical state store with FTS where useful, optional JSONL export, optional BYOK LLM providers, Telegram Bot API.

---

## Current status

- ~~OSS repo scaffolded as `pulsekeeper-ai`.~~
- ~~Project renamed to PulseKeeper.~~
- ~~Python package under `src/pulsekeeper`.~~
- ~~CLI entrypoint `pulsekeeper`.~~
- ~~Unit tests and ruff configured.~~
- ~~Basic domain model `HealthEntry`.~~
- ~~Bootstrap local JSONL storage.~~
- ~~Daily/weekly local summaries.~~
- ~~Telegram adapter seam without live network.~~
- ~~Telegram multi-user storage routing.~~
- ~~Telegram transport seam for Bot API update JSON.~~
- ~~Telegram polling client seam with fixture-based tests.~~
- ~~Initial `AgentRuntime`, `MessageContext`, `ToolExecutor`, and typed tool call seam.~~
- ~~Telegram natural-language input no longer uses parser when no model runtime is configured.~~
- ~~SQLite `Database`, migrations, `HealthEntryStore`, memory stores, FTS search, and transaction tests.~~
- ~~Pydantic-ai agent facade and OpenAI-compatible BYOK config seam.~~
- ~~Aiogram Telegram gateway with owner/private-chat guards and slash commands.~~
- ~~Current quality gate: `uv run pytest -q` passes: 91 tests.~~
- ~~Current quality gate: `uv run ruff check .` passes.~~

---

## 1. Product foundation

- ~~Define positioning: open-source Telegram-first health agent with BYOK LLM support.~~
- ~~Document principles: Telegram-first, BYOK, self-host friendly, privacy-first, agentic summaries.~~
- Keep the project boring and useful before adding integrations.
- Keep medical behavior conservative: summarize patterns, do not diagnose.
- Keep every subsystem replaceable through narrow interfaces.

---

## 2. Core domain and storage

- ~~Create `HealthEntry`.~~
- ~~Support basic entry kinds: food, weight, workout, sleep, note.~~
- ~~Bootstrap JSONL storage exists from the first scaffold.~~
- ~~Support per-user Telegram storage path in the bootstrap storage.~~
- Treat current JSONL code as temporary scaffold/export compatibility, not the canonical database.
- ~~Add stable entry IDs in SQLite `health_entries`.~~
- ~~Add `created_at` and `updated_at` timestamps in SQLite.~~
- ~~Add optional `source` field: `telegram`, `cli`, `import`, `manual`.~~
- ~~Add optional `metadata` for tool-generated structured details.~~
- ~~Add schema versioning for future migrations.~~
- Add export commands:
  - JSONL
  - CSV
  - Markdown

---

## 2A. SQLite state database layer

PulseKeeper should have a normal local database layer from the start, following the Hermes pattern: a canonical SQLite state store under the app home directory, with typed stores/repositories on top. Files/JSONL can remain for export and simple debugging, but tools and the agent runtime should not write directly to ad-hoc paths.

### Hermes-inspired storage principles

- Use one canonical local SQLite database, analogous to Hermes `~/.hermes/state.db`.
- Default path: `~/.pulsekeeper/state.db`.
- Put profile-specific or self-host-specific state under the app home, not scattered files.
- Keep storage local-first and self-host friendly.
- Use typed store classes as the only write/read boundary for agent tools.
- Use migrations from the beginning; never rely on implicit table creation sprinkled across tools.
- Use SQLite FTS5 for searchable health memory, notes, summaries, and conversations where useful.
- Keep JSONL/CSV/Markdown as export formats, not the primary operational database.

### Database files and directories

```text
~/.pulsekeeper/
  state.db                  # canonical SQLite database
  config.toml               # non-secret config
  .env                      # secrets / BYOK keys, never committed
  exports/                  # JSONL/CSV/Markdown exports
  media/                    # Telegram photos / future food images
  logs/                     # local app logs, redacted
```

### Initial tables

- `users`
  - internal user ID;
  - gateway user IDs;
  - created/updated timestamps.
- `gateway_accounts`
  - gateway name: telegram, future web/api/etc.;
  - external user/chat IDs;
  - mapping to internal user.
- `health_entries`
  - canonical health events;
  - kind, note, value, unit, logged_at, source, metadata JSON;
  - created_at, updated_at, deleted_at.
- `health_entries_fts`
  - FTS5 index over note/metadata text for search.
- `user_profile_facts`
  - stable profile memory facts;
  - fact type/key/value/confidence/source timestamps.
- `preferences`
  - answer style, tracking preferences, reminder preferences.
- `conversation_state`
  - short-lived pending actions/clarifications with expiry.
- `summary_memory`
  - weekly/monthly observations and durable patterns.
- `summary_memory_fts`
  - FTS5 index for retrieval.
- `reminders`
  - schedule, timezone, enabled, last_sent_at, next_due_at.
- `telegram_offsets`
  - polling offset per bot/profile/gateway account.
- `imports`
  - import batches and source metadata.
- `import_items`
  - external IDs for idempotency.
- `schema_migrations`
  - applied migration version and timestamp.

### Store interfaces

- `Database`
  - opens SQLite connection;
  - applies migrations;
  - owns transaction helper.
- `UserStore`
  - maps Telegram users/chats to internal users.
- `HealthEntryStore`
  - append/list/update/delete/search health entries.
- `ProfileStore`
  - get/set profile facts.
- `PreferenceStore`
  - get/set preferences.
- `ConversationStateStore`
  - get/set/clear pending state.
- `SummaryMemoryStore`
  - write/search summary memory.
- `ReminderStore`
  - add/list/cancel/list_due/mark_sent.
- `GatewayStateStore`
  - Telegram offsets and gateway runtime state.
- `ImportStore`
  - idempotent import batch tracking.

### Implementation tasks

- ~~Create `src/pulsekeeper/storage/sqlite.py`.~~
- ~~Create migration files under `src/pulsekeeper/migrations/`.~~
- ~~Add automatic idempotent init at gateway startup / store tests.~~
- Partially replace direct `JsonlHealthLog` usage: aiogram gateway uses SQLite stores; legacy `agent_runtime.py` still writes JSONL.
- Keep `JsonlHealthLog` only for legacy tests/export until removed.
- ~~Add tests with temporary SQLite DB files.~~
- ~~Add migration tests.~~
- ~~Add FTS search tests.~~
- ~~Add transaction tests.~~
- Add transaction tests for multi-tool turns.

---

## 3. Agent runtime core

This is the center of the product. PulseKeeper should feel like Hermes specialized for health: gateways, model runtime, typed tools, memory, scheduler, policies, and domain protocols.

### Principle

The model should not output prose that the app parses, and user interaction should not be routed through regex/rule parsers. The model calls typed tools with validated arguments; deterministic code executes those tools.

Target flow:

```text
Telegram message
  -> Telegram gateway
  -> AgentRuntime
  -> BYOK model runtime with typed tools
  -> deterministic tool executor
  -> Pydantic validation
  -> SQLite state database / memory / summaries / reminders / integrations
  -> Telegram response
```

Core runtime objects:

- `AgentRuntime`: owns one turn of reasoning and tool execution.
- `MessageContext`: user ID, chat ID, timestamp, timezone, gateway, recent conversation state.
- `ModelRuntime`: BYOK LLM wrapper with tool-calling support.
- `ToolRegistry`: available domain tools with schemas, descriptions, permissions, and safety metadata.
- `ToolExecutor`: validates arguments, executes deterministic tools, returns structured tool results.
- `Database`: canonical SQLite state store, migrations, transactions, and FTS indexes.
- `Store` layer: typed repositories for health entries, memory, reminders, gateway state, and imports.
- `MemoryProvider`: user profile, health memory, summary memory, preferences, and short dialog state backed by stores.
- `PolicyLayer`: medical-safety, privacy, and secret-redaction checks.
- `Gateway`: Telegram first, but not hard-coded into the agent core.

### Core tools to implement

- `log_health_entry`
  - arguments:
    - `kind`: food / weight / workout / sleep / symptom / medication / note
    - `note`
    - `logged_at`
    - `value`
    - `unit`
    - `metadata`
  - writes a validated `HealthEntry`.

- `get_health_summary`
  - arguments:
    - `period`: day / week / month / custom
    - `start`
    - `end`
  - returns a Telegram-friendly summary.

- `ask_clarifying_question`
  - arguments:
    - `text`
  - returns a question without writing to storage.

- `update_last_entry`
  - arguments:
    - patch fields
  - supports correction flows like “не 84.2, а 83.9”.

- `delete_last_entry`
  - supports `/undo` and natural-language undo.

- `set_user_profile_fact`
  - stores stable personal context: timezone, goals, preferences, constraints.

- `schedule_reminder`
  - stores reminder intent: type, cadence, time, timezone.

- `search_health_memory`
  - retrieves relevant prior logs, summaries, and profile facts for the current turn.

- `write_summary_memory`
  - stores stable weekly/monthly observations as memory, separate from raw health events.

### Implementation tasks

- ~~Add Pydantic schemas for currently wired tool arguments.~~
- Add tool metadata: name, description, input schema, output schema, permissions, safety notes.
- Add a tool registry.
- ~~Add a deterministic tool executor seam.~~
- ~~Add model-observable tool results and tool errors for current facade.~~
- ~~Add tests where fake model responses call tools directly.~~
- Ensure model cannot write raw storage directly.
- Ensure tools write only through typed stores backed by the SQLite database layer.
- Add safety checks inside tools, not only in prompts.
- Ensure all Telegram user-facing interactions route through the agent runtime or direct tool mappings, not parsers.

---

## 4. No parser-based user interaction

- ~~A basic `parse_health_log(text)` exists from the bootstrap phase.~~
- ~~Remove parser usage from Telegram/user-facing flows.~~
- Do not add regex/rule parsing for natural-language health input.
- Do not make `pulsekeeper parse` or `pulsekeeper log` the primary UX.
- Keep any remaining parser code only as temporary dev scaffolding until the agent tool loop replaces it.
- If an offline/no-LLM mode is needed later, implement it as a deterministic command/tool path, not as a parallel natural-language parser product.
- Natural language like “вес 84.2”, “дай сводку”, “напомни утром”, “не 84.2, а 83.9” must be handled by model tool calls.

---

## 5. CLI

- ~~`pulsekeeper parse`.~~
- ~~`pulsekeeper log`.~~
- ~~`pulsekeeper summary`.~~
- ~~`pulsekeeper telegram-handle`.~~
- ~~`pulsekeeper telegram-update`.~~
- ~~`pulsekeeper telegram-poll-once`.~~
- Add `pulsekeeper agent-handle` to run one message through the tool-calling agent.
- Add `pulsekeeper config`.
- Add `pulsekeeper doctor`.
- Add `pulsekeeper export`.
- Add `pulsekeeper reminders`.
- Add `pulsekeeper telegram-run` for live long polling.

---

## 6. Telegram adapter and transport

- ~~Local Telegram text adapter exists.~~
- ~~Telegram update transport exists.~~
- ~~Polling client seam exists.~~
- ~~Add Bot API HTTP client seam for `getUpdates` / `sendMessage`.~~
- ~~Add `TELEGRAM_BOT_TOKEN` config / `.env.example` entry.~~
- Add long polling loop:
  - offset persistence;
  - graceful shutdown;
  - retry/backoff;
  - safe logs without token leaks.
- Add Telegram-safe formatting.
- ~~Add command support:
  - `/help`
  - `/summary`
  - `/today`
  - `/week`
  - `/undo`
  - `/profile`
  - `/reminders` placeholder~~
- ~~Route normal text through agent runtime path.~~
- Map slash commands like `/summary`, `/undo`, `/reminders`, and `/profile` into the same typed tools used by natural language.
- Only trivial gateway/system commands such as `/start` and `/help` may bypass the model, and even then they should not parse health input.

---

## 7. BYOK LLM providers

- ~~Add provider/agent facade using pydantic-ai.~~
- ~~Add fake provider for tests.~~
- ~~Add OpenAI-compatible provider construction first.~~
- ~~Add config for:
  - provider;
  - model;
  - API key env var;
  - base URL;
  - timeout.~~
- Later add:
  - Anthropic;
  - OpenRouter;
  - local Ollama/OpenAI-compatible endpoints.
- Never require a hosted PulseKeeper key.
- Never call live LLMs in unit tests.

---

## 8. User profile and memory

Memory is a core Hermes-like capability, not just settings.

- ~~Add per-user profile storage.~~
- ~~Store stable facts separately from health logs.~~
- Split memory into:
  - profile memory: stable facts about the user;
  - health log: raw events and measurements;
  - conversation state: short-lived dialog context;
  - summary memory: weekly/monthly observations and patterns;
  - preferences: answer style, reminder preferences, tracking preferences.
- Initial profile fields:
  - timezone;
  - language;
  - health goals;
  - dietary constraints;
  - relevant context user explicitly gives.
- Add profile/memory tools:
  - ~~`set_user_profile_fact` foundation in pydantic-ai facade; registry metadata still pending~~;
  - `get_user_profile`;
  - `search_health_memory`;
  - `write_summary_memory`.
- Add Telegram commands that map into tools:
  - ~~/profile~~;
  - `/set timezone ...`;
  - `/set goal ...`.
- Keep memory editable and exportable.

---

## 9. Summaries and insights

- ~~Basic daily/weekly summaries exist.~~
- Add deterministic summary data builder.
- Add LLM summary generation on top of structured data.
- Keep no-LLM summary fallback.
- Add blocks:
  - weight;
  - food;
  - sleep;
  - workouts;
  - symptoms/medications;
  - notes.
- Add pattern detection:
  - trends;
  - streaks;
  - notable changes;
  - missing data.
- Guardrail: summaries notice patterns but do not diagnose.

---

## 10. Conversation state

- ~~Add short-lived per-user dialog state store.~~
- Support clarification flows:
  - ambiguous food entry;
  - missing date/time;
  - unclear correction.
- Support correction flows:
  - “не 84.2, а 83.9”;
  - “удали последнюю запись”;
  - ~~/undo~~.
- Keep state small and inspectable.

---

## 11. Reminders and scheduler

Scheduler is a core agent capability: PulseKeeper should be able to initiate useful health check-ins, not only answer messages.

- Add reminder model.
- Add storage for reminders.
- Add scheduler loop.
- Add Telegram reminder delivery.
- Add commands:
  - `/remind weight daily 09:00`;
  - `/reminders`;
  - `/reminder off`.
- Use timezone from profile.
- Avoid missed-reminder spam after downtime.

---

## 12. Integrations

Implement only after Telegram + BYOK agent loop is useful.

- Apple Health import:
  - XML export first;
  - weight, sleep, workouts, steps.
- Whoop import:
  - recovery, sleep, workouts if API/export is practical.
- Later:
  - Oura;
  - Garmin;
  - Google Fit / Health Connect.
- All imports should be idempotent.
- Imported data should have `source` and external IDs.

---

## 13. Food image logging

- Add Telegram photo handling.
- Add local file storage for images.
- Add optional BYOK vision provider.
- Add tool call path for image-derived entries.
- UX:
  - user sends photo;
  - agent logs approximate meal note;
  - asks clarification if needed.
- Guardrail: do not claim precise calories from images.


---

## 14. Health protocols

Health protocols are the domain-specific equivalent of Hermes skills: reusable procedures the agent follows for common health tasks.

- Weight tracking protocol:
  - log weight;
  - notice trend;
  - avoid overreacting to daily noise.
- Sleep check-in protocol:
  - capture duration/quality;
  - connect patterns cautiously;
  - do not diagnose sleep disorders.
- Workout logging protocol:
  - capture type, duration, intensity;
  - connect to recovery/sleep/weight when enough data exists.
- Food logging protocol:
  - capture meal context;
  - avoid fake precision unless user explicitly tracks calories/macros.
- Weekly review protocol:
  - summarize changes;
  - identify missing data;
  - propose one small next action.
- Medication/symptom caution protocol:
  - log facts;
  - flag urgent language carefully;
  - advise professional care when appropriate;
  - do not give treatment instructions.

---

## 15. Packaging and deployment

- Add `.env.example`.
- Add Dockerfile.
- Add docker-compose example.
- Add persistent volume docs.
- Add systemd example.
- Add GitHub Actions:
  - tests;
  - ruff;
  - build;
  - Docker publish.
- Later publish package to PyPI for `pipx install pulsekeeper-ai`.

---

## 16. OSS polish

- Add `LICENSE`.
- Add `CONTRIBUTING.md`.
- Add issue templates.
- Add PR template.
- Add architecture docs:
  - adapters;
  - agent tools;
  - storage;
  - LLM providers;
  - reminders;
  - integrations.
- Add screenshots/GIF.
- Add quickstart that works in under 3 minutes.

---

## 17. Security and privacy

- Never log secrets.
- Redact bot token in errors/logs.
- Make LLM calls opt-in through BYOK config.
- Document what data goes to Telegram and LLM providers.
- Add export/delete commands.
- Add `pulsekeeper doctor` checks:
  - token configured;
  - storage writable;
  - provider reachable;
  - no obvious unsafe config.

---

## 18. Recommended next increments

1. **Agent runtime + tool executor skeleton**
   - ~~`AgentRuntime`, `MessageContext`, `ToolExecutor` seam;~~
   - `ToolRegistry`;
   - Pydantic tool arg schemas;
   - fake model tests;
   - ~~`log_health_entry` and `get_health_summary` tool execution;~~

2. **SQLite database layer**
   - `~/.pulsekeeper/state.db` equivalent;
   - migrations;
   - typed stores;
   - FTS for health/summary memory;
   - replace direct JSONL writes in tools.

3. **Memory + scheduler foundations**
   - profile memory backed by SQLite;
   - conversation state backed by SQLite;
   - reminder model/store;
   - no LLM provider needed yet because tests use fake model/tool calls.

4. **BYOK OpenAI-compatible provider seam**
   - fake provider remains default for tests;
   - real provider only behind config;
   - tool-calling support is mandatory.

5. **Agent-handled Telegram messages**
   - normal Telegram text goes through `AgentRuntime`;
   - slash commands map into the same tools;
   - remove parser-based user interaction from Telegram paths.

6. **Config + doctor**
   - `.env` loading;
   - config object;
   - no secret leaks;
   - `pulsekeeper doctor`.

7. **Live Telegram polling**
   - `telegram-run`;
   - real HTTP client;
   - offset persistence;
   - Docker-friendly operation.

8. **Conversation corrections**
   - `/undo`;
   - `update_last_entry`;
   - delete last entry.

9. **Reminders**
   - daily weight;
   - evening journal;
   - weekly summary.

---

## Explicit non-goals for now

- No parser-based natural-language user interaction.
- No large hand-written parser as the main intelligence layer.
- No mandatory hosted backend.
- No mandatory hosted LLM key.
- No diagnosis or medical treatment recommendations.
- Build a minimal Hermes-like domain agent platform: gateway, typed tools, memory, scheduler, BYOK model runtime, policies, and health protocols. Avoid unrelated Hermes subsystems until needed.


