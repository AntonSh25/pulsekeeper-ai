# PulseKeeper: архитектура и пошаговый план реализации

Дата: 2026-06-13  
Статус: implementation roadmap completed through MVP success criteria
Репозиторий: `AntonSh25/pulsekeeper-ai`  
Ветка: `feat/mvp-summaries`

---

## 0. Краткая суть проекта

PulseKeeper — open-source Telegram-first health-agent: персональный health memory agent, который принимает сообщения в Telegram, через BYOK LLM вызывает типизированные health tools, хранит данные локально и помогает пользователю вести дневник здоровья, получать сводки, напоминания и осторожные инсайты по паттернам.

Цель проекта — не «бот-парсер дневника», а маленькая domain-specific agent platform в духе Hermes, но сфокусированная на здоровье:

- gateway/adapters;
- agent runtime;
- BYOK model runtime;
- typed tools;
- local memory/state database;
- summaries;
- reminders/scheduler;
- privacy/security policies;
- health protocols.

---

## 1. Product principles

### Основные принципы

- **Telegram-first UX**: ввод должен быть быстрым, как сообщение самому себе.
- **BYOK**: пользователь приносит свой LLM API key; у PulseKeeper нет обязательного hosted key.
- **Self-host friendly**: локальный запуск, локальная база, Docker/systemd позже.
- **Privacy-first**: понятно, что хранится локально, что уходит в Telegram и LLM provider.
- **Tool-calling-first**: естественный язык обрабатывается через LLM tool calls, а не через большой regex/parser.
- **Careful health behavior**: агент замечает паттерны, но не ставит диагнозы и не даёт медицинские назначения.
- **Boring useful MVP first**: сначала стабильный дневник/сводки/напоминания, потом Apple Health/Whoop/images.

### Non-goals на ближайший этап

- Не строить большой hand-written parser как основной intelligence layer.
- Не делать mandatory cloud/backend.
- Не требовать hosted LLM key.
- Не давать диагнозы или treatment recommendations.
- Не копировать весь Hermes: брать только нужные паттерны — gateway, runtime, tools, memory, scheduler, policies.

---

## 2. Целевая архитектура

```text
Telegram gateway
  -> AgentRuntime
  -> BYOK ModelRuntime with typed tools
  -> ToolExecutor + Pydantic validation
  -> SQLite state database / stores / memory / reminders / integrations
  -> Telegram response
```

### Компоненты

#### 2.1 Gateway layer

Первый gateway — Telegram.

Задачи:

- принимать Telegram updates;
- извлекать `chat_id`, `user_id`, `text`, `message_id`, attachments;
- хранить offset для long polling;
- безопасно логировать без bot token/secrets;
- маршрутизировать сообщения в `AgentRuntime`;
- отправлять ответ пользователю.

Gateway не должен парсить health-смысл сообщения. Он может обрабатывать только системные команды типа `/start` и `/help`.

#### 2.2 AgentRuntime

Центр продукта. Отвечает за один turn взаимодействия.

Задачи:

- собрать `MessageContext`;
- загрузить profile/preferences/recent memory;
- передать model runtime список доступных tools;
- получить tool call(s);
- выполнить их через `ToolExecutor`;
- вернуть пользователю понятный Telegram-friendly ответ;
- применить policy checks.

#### 2.3 ModelRuntime / BYOK providers

Обёртка вокруг LLM provider.

Минимальный интерфейс:

```python
class ModelRuntime:
    def complete_with_tools(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSpec],
        context: MessageContext,
    ) -> ModelResponse: ...
```

Провайдеры:

1. fake provider для тестов;
2. OpenAI-compatible provider;
3. позже Anthropic/OpenRouter/Ollama/local endpoints.

Правила:

- unit tests не ходят в live LLM;
- real provider включается только через config/BYOK;
- tool-calling обязателен для естественного языка.

#### 2.4 ToolRegistry

Каталог доступных domain tools.

Каждый tool имеет:

- name;
- description;
- Pydantic input schema;
- output schema/structured result;
- permissions/safety metadata;
- executor function.

#### 2.5 ToolExecutor

Детерминированно выполняет tools.

Задачи:

- валидировать аргументы через Pydantic;
- выполнять только зарегистрированные tools;
- возвращать structured result;
- обрабатывать ошибки в формате, понятном модели и пользователю;
- писать данные только через typed stores, не напрямую в JSONL/файлы.

#### 2.6 SQLite state database

Canonical runtime storage — локальная SQLite база.

Default layout:

```text
~/.pulsekeeper/
  state.db                  # canonical SQLite database
  config.toml               # non-secret config
  .env                      # BYOK/secrets, never committed
  exports/                  # JSONL/CSV/Markdown exports
  media/                    # Telegram photos / future food images
  logs/                     # redacted logs
```

JSONL остаётся только как legacy scaffold/export/debug format.

#### 2.7 Store layer

Typed repositories поверх SQLite:

- `Database` — connection, migrations, transactions;
- `UserStore` — users and gateway identity mapping;
- `HealthEntryStore` — append/list/update/delete/search health entries;
- `ProfileStore` — durable user profile facts;
- `PreferenceStore` — user preferences;
- `ConversationStateStore` — short-lived pending dialog state;
- `SummaryMemoryStore` — durable observations/patterns;
- `ReminderStore` — reminders and due reminders;
- `GatewayStateStore` — Telegram offsets/runtime state;
- `ImportStore` — import batches/idempotency.

#### 2.8 MemoryProvider

Memory — core capability, не просто settings.

Типы memory:

- profile memory: timezone, language, goals, constraints;
- raw health log: events/measurements;
- conversation state: short-lived pending clarifications;
- summary memory: weekly/monthly observations;
- preferences: answer style, reminders, tracking preferences.

#### 2.9 PolicyLayer

Guardrails:

- no diagnosis;
- no treatment instructions;
- secrets redaction;
- no token leakage in logs/errors;
- clear boundaries of what goes to LLM provider;
- conservative behavior around symptoms/medications.

#### 2.10 Scheduler

Отвечает за reminders/check-ins.

Задачи:

- хранить reminders;
- находить due reminders;
- отправлять Telegram messages;
- учитывать timezone;
- не спамить после downtime.

---

## 3. Начальные health tools

### 3.1 `log_health_entry`

Назначение: записать health event.

Аргументы:

- `kind`: `food`, `weight`, `workout`, `sleep`, `symptom`, `medication`, `note`;
- `note`;
- `logged_at`;
- `value`;
- `unit`;
- `metadata`.

Пишет запись через `HealthEntryStore`.

### 3.2 `get_health_summary`

Назначение: получить daily/weekly/monthly/custom summary.

Аргументы:

- `period`: `day`, `week`, `month`, `custom`;
- `start`;
- `end`.

Сначала строит deterministic summary data, затем optional LLM summary.

### 3.3 `ask_clarifying_question`

Назначение: задать уточнение без записи в storage.

Примеры:

- непонятное время;
- неясный тип записи;
- correction без target.

### 3.4 `update_last_entry`

Назначение: correction flow.

Примеры:

- «не 84.2, а 83.9»;
- «завтрак был не омлет, а творог».

### 3.5 `delete_last_entry`

Назначение:

- `/undo`;
- «удали последнюю запись».

Лучше использовать soft delete через `deleted_at`.

### 3.6 `set_user_profile_fact`

Назначение: сохранить stable facts.

Примеры:

- timezone;
- goal;
- dietary constraint;
- language preference.

### 3.7 `search_health_memory`

Назначение: достать релевантные health logs, summaries, profile facts.

Требует FTS/search поверх SQLite.

### 3.8 `write_summary_memory`

Назначение: сохранить durable observations.

Пример:

- «последние 3 недели вес снижается примерно на 0.3 кг/неделю».

### 3.9 `schedule_reminder`

Назначение: создать reminder.

Примеры:

- daily weight 09:00;
- evening journal;
- weekly review.

---

## 4. SQLite database design

### 4.1 Initial tables

#### `users`

- `id`;
- `created_at`;
- `updated_at`.

#### `gateway_accounts`

- `id`;
- `user_id`;
- `gateway`: `telegram`, future `web`, `api`, etc.;
- `external_user_id`;
- `external_chat_id`;
- timestamps.

#### `health_entries`

- `id`;
- `user_id`;
- `kind`;
- `note`;
- `value`;
- `unit`;
- `logged_at`;
- `source`: `telegram`, `cli`, `import`, `manual`;
- `metadata_json`;
- `schema_version`;
- `created_at`;
- `updated_at`;
- `deleted_at`.

#### `health_entries_fts`

FTS5 index по `note` и useful metadata text.

#### `user_profile_facts`

- `id`;
- `user_id`;
- `key`;
- `value_json`;
- `confidence`;
- `source`;
- timestamps.

#### `preferences`

- `id`;
- `user_id`;
- `key`;
- `value_json`;
- timestamps.

#### `conversation_state`

- `id`;
- `user_id`;
- `state_type`;
- `payload_json`;
- `expires_at`;
- timestamps.

#### `summary_memory`

- `id`;
- `user_id`;
- `period_start`;
- `period_end`;
- `kind`;
- `text`;
- `metadata_json`;
- timestamps.

#### `summary_memory_fts`

FTS5 по summary text.

#### `reminders`

- `id`;
- `user_id`;
- `type`;
- `schedule_json`;
- `timezone`;
- `enabled`;
- `last_sent_at`;
- `next_due_at`;
- timestamps.

#### `telegram_offsets`

- `id`;
- `bot_profile`;
- `offset`;
- `updated_at`.

#### `imports`

- `id`;
- `user_id`;
- `source`;
- `started_at`;
- `finished_at`;
- `metadata_json`.

#### `import_items`

- `id`;
- `import_id`;
- `external_id`;
- `status`;
- `metadata_json`.

#### `schema_migrations`

- `version`;
- `applied_at`.

### 4.2 Migration rules

- migrations are explicit files under `src/pulsekeeper/migrations/`;
- startup can auto-apply idempotent migrations;
- tests cover fresh DB and migration path;
- no implicit table creation hidden inside tools.

---

## 5. Что уже сделано

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
- ~~SQLite `Database` class with explicit idempotent migrations, WAL/FK setup and transaction helper.~~
- ~~Initial SQLite schema under `src/pulsekeeper/migrations/001_initial_schema.sql`.~~
- ~~`HealthEntryStore` with append/list/get_last/update/soft_delete/search via FTS5.~~
- ~~Memory stores: `ProfileStore`, `PreferenceStore`, `ConversationStateStore`, `SummaryMemoryStore`.~~
- ~~Pydantic AI facade for `log_health_entry`, summary, clarifying questions and model-tool loop tests.~~
- ~~LLM access config and OpenAI-compatible/pydantic-ai provider construction seam.~~
- ~~Aiogram Telegram gateway skeleton with owner allowlist/private-chat guard.~~
- ~~Telegram slash commands: `/start`, `/help`, `/summary`, `/today`, `/week`, `/undo`, `/profile`, `/reminders` placeholder.~~
- ~~Config and doctor diagnostics, including redacted provider reachability check.~~
- ~~Apple Health XML import slice for weight, sleep, workouts, and steps, with idempotent external-ID tracking and CLI command.~~
- ~~Telegram photo metadata handling and local media storage seam for food-image logging.~~
- ~~Optional BYOK vision provider config/doctor seam for future food-photo descriptions.~~
- ~~Quality gate: `uv run pytest -q` passes — 142 tests.~~
- ~~SQLite health-entry export CLI: `pulsekeeper export jsonl|csv|markdown` with optional metadata redaction.~~
- ~~Quality gate: `uv run pytest -q` passes — 146 tests.~~
- ~~Quality gate: `uv run ruff check .` passes.~~

---

## 6. Пошаговый план реализации

## Phase 1 — Agent runtime + tool system hardening

Цель: сделать agent runtime главным маршрутом для user-facing interaction.

### Tasks

1. ~~Создать базовый `AgentRuntime`.~~
2. ~~Создать `MessageContext`.~~
3. ~~Создать `ToolExecutor` seam.~~
4. ~~Добавить `ToolRegistry`.~~
5. ~~Добавить Pydantic schemas для currently wired tools: `log_health_entry`, `get_health_summary`, `ask_clarifying_question`.~~
6. ~~Добавить metadata для tools:
   - name;
   - description;
   - input schema;
   - output shape;
   - safety notes.~~
7. ~~Добавить fake/test model runtime для тестов.~~
8. ~~Сделать тесты, где fake model возвращает tool call.~~
9. ~~Убедиться, что model не пишет в storage напрямую.~~
10. ~~Все normal Telegram text messages route through agent runtime path in aiogram gateway.~~

### Acceptance criteria

- ~~normal text не идёт в parser;~~
- ~~fake model может вызвать `log_health_entry`;~~
- ~~fake model может вызвать `get_health_summary`;~~
- ~~invalid tool args дают controlled error;~~
- ~~tests green.~~

---

## Phase 2 — SQLite state database layer

Цель: заменить runtime storage на нормальную локальную БД.

### Tasks

1. ~~Создать `src/pulsekeeper/storage/sqlite.py`.~~
2. ~~Создать `Database` class:
   - opens connection;
   - applies migrations;
   - transaction helper.~~
3. ~~Создать migrations folder.~~
4. ~~Реализовать initial schema.~~
5. Реализовать stores:
   - ~~`UserStore`;~~
   - ~~`HealthEntryStore`;~~
   - ~~`ProfileStore`;~~
   - ~~`PreferenceStore`;~~
   - ~~`ConversationStateStore`;~~
   - ~~`SummaryMemoryStore`;~~
   - ~~`ReminderStore`;~~
   - ~~`GatewayStateStore`;~~
   - ~~`ImportStore`.~~
6. ~~Добавить FTS5 для `health_entries` и `summary_memory`.~~
7. ~~Написать tests with temp SQLite DB.~~
8. ~~Добавить migration tests.~~
9. ~~Добавить transaction tests.~~
10. ~~Перевести active aiogram runtime на store layer: aiogram gateway uses SQLite `HealthEntryStore`; legacy JSONL remains isolated to old CLI/dev smoke adapter.~~
11. ~~Оставить JSONL только для legacy/export/dev smoke checks.~~

### Acceptance criteria

- ~~fresh DB initializes deterministically;~~
- ~~migrations idempotent;~~
- ~~health entry append/list/update/delete works;~~
- ~~FTS search works;~~
- ~~agent tools write through stores;~~
- ~~no direct JSONL writes in runtime path.~~

---

## Phase 3 — Memory foundation

Цель: сделать memory первым-class capability.

### Tasks

1. ~~Profile facts storage.~~
2. ~~Preferences storage.~~
3. ~~Conversation state with expiry.~~
4. ~~Summary memory storage.~~
5. ~~`set_user_profile_fact` with first-class registry/tool metadata.~~
6. ~~`search_health_memory` tool.~~
7. ~~`write_summary_memory` tool.~~
8. ~~/profile reads saved facts through reusable `get_user_profile` helper/tool.~~
9. Telegram commands mapping:
   - ~~/profile~~;
   - ~~/set timezone ...~~;
   - ~~/set goal ...~~.

### Acceptance criteria

- ~~agent can remember stable explicit facts;~~
- ~~short-lived clarification state expires;~~
- ~~summary memory searchable;~~
- ~~profile exportable/editable later.~~

---

## Phase 4 — BYOK provider seam

Цель: подключить реальный LLM только через config и BYOK.

### Tasks

1. ~~Define pydantic-ai `PulseKeeperAgent` / model construction seam.~~
2. ~~Keep fake provider as test default.~~
3. ~~Add OpenAI-compatible provider construction seam.~~
4. ~~Add config fields:
   - provider;
   - model;
   - base_url;
   - api_key_env;
   - timeout.~~
5. ~~Add `.env` loading / env based config.~~
6. ~~Add secret redaction in config representation/errors where present.~~
7. ~~Add provider construction tests without live API.~~
8. ~~Provider construction and tool registration covered without live API; live provider smoke remains post-MVP setup work.~~

### Acceptance criteria

- ~~no live LLM calls in unit tests;~~
- ~~provider can return tool calls;~~
- ~~missing API key gives clear error;~~
- ~~secrets never printed.~~

---

## Phase 5 — Agent-handled Telegram UX

Цель: Telegram становится реальным пользовательским интерфейсом агента.

### Tasks

1. ~~Route normal Telegram text through pydantic-ai agent runtime path in `TelegramGateway`.~~
2. Map slash commands to deterministic/store-backed paths:
   - ~~/summary~~;
   - ~~/today~~;
   - ~~/week~~;
   - ~~/undo~~;
   - ~~/profile~~;
   - ~~/reminders placeholder~~.
3. ~~Allow only trivial system commands to bypass model:
   - `/start`;
   - `/help`.~~
4. ~~Add minimal Telegram-safe formatting.~~
5. ~~Add aiogram gateway tests with fake gateway/update + fake agent.~~
6. ~~Slash commands with registered tool equivalents use store-backed typed paths; `/undo` remains deterministic store-backed until Phase 8 correction tools.~~

### Acceptance criteria

- ~~“вес 84.2” becomes tool call, not parser result;~~
- ~~“дай сводку за неделю” becomes summary tool call;~~
- ~~`/week` uses the same summary tool path;~~
- ~~user receives concise Telegram-friendly response.~~

---

## Phase 6 — Config and doctor

Цель: сделать self-host setup понятным.

### Tasks

1. ~~Add `config.toml` support.~~
2. ~~Add `.env.example`.~~
3. ~~Add `pulsekeeper config`.~~
4. ~~Add `pulsekeeper doctor` checks:~~
   - ~~storage writable~~;
   - ~~DB migrations OK~~;
   - ~~Telegram token configured if needed~~;
   - ~~provider configured~~;
   - ~~provider reachable~~;
   - ~~no obvious unsafe config~~.
5. ~~Add redacted diagnostics.~~

### Acceptance criteria

- ~~new user can run doctor and understand next action~~;
- ~~doctor does not leak secrets~~;
- ~~config errors are actionable~~.

---

## Phase 7 — Live Telegram polling

Цель: запустить настоящего Telegram bot без live network в tests.

### Tasks

1. ~~Add real HTTP client seam for `getUpdates` / `sendMessage` via `urllib`-based `TelegramBotApiClient`.~~
2. ~~Add `TELEGRAM_BOT_TOKEN` config / `.env.example` entry for polling seam.~~
3. ~~Implement `telegram-run` long polling loop:~~
   - ~~load offset~~;
   - ~~get updates~~;
   - ~~handle messages~~;
   - ~~send replies~~;
   - ~~persist offset~~;
   - ~~graceful shutdown.~~
4. ~~Add retry/backoff.~~
5. ~~Add safe logs.~~
6. ~~Add integration-ish tests with mocked HTTP.~~

### Acceptance criteria

- ~~bot can run locally with token;~~
- ~~restart does not reprocess old updates;~~
- ~~token is never logged;~~
- ~~network errors backoff and recover.~~

---

## Phase 8 — Corrections and undo

Цель: сделать дневник usable в реальной жизни.

### Tasks

1. ~~Implement `HealthEntryStore.update` for last-entry correction foundation.~~
2. ~~Implement `HealthEntryStore.soft_delete` / soft delete.~~
3. ~~Implement `/undo` in aiogram gateway.~~
4. ~~Add natural-language correction flows:
   - “не 84.2, а 83.9”;
   - “удали последнюю запись”;
   - “это был обед, не завтрак”.~~
5. ~~Use conversation state when target is ambiguous.~~

### Acceptance criteria

- ~~last entry can be corrected;~~
- ~~deletion is reversible/auditable via soft delete;~~
- ~~ambiguous corrections ask clarification.~~

---

## Phase 9 — Summaries and insights

Цель: сделать summaries полезными, но осторожными.

### Tasks

1. ~~Bootstrap deterministic daily/weekly summaries and gateway counts exist; richer structured summary builder now returns health blocks and cautious patterns.~~
2. ~~Add no-LLM fallback for `/today`, `/week`, `/summary`.~~
3. ~~Add optional LLM prose layer.~~
4. ~~Summary blocks:~~
   - ~~weight~~;
   - ~~food~~;
   - ~~sleep~~;
   - ~~workouts~~;
   - ~~symptoms/medications~~;
   - ~~notes~~.
5. ~~Pattern detection:~~
   - ~~trends~~;
   - ~~streaks~~;
   - ~~notable changes~~;
   - ~~missing data~~.
6. ~~Store durable weekly/monthly observations in summary memory.~~

### Acceptance criteria

- ~~daily/weekly summaries work without LLM~~;
- ~~LLM summary does not diagnose~~;
- ~~useful patterns are saved as summary memory only when durable~~.

---

## Phase 10 — Reminders and scheduler

Цель: агент умеет сам инициировать useful check-ins.

### Tasks

1. ~~Add reminder model/store.~~
2. ~~Add scheduler loop.~~
3. ~~Add Telegram reminder delivery.~~
4. ~~Add reminder tools:
   - `schedule_reminder`;
   - list reminders;
   - cancel reminder.~~
5. ~~Add commands:
   - `/remind weight daily 09:00`;
   - `/reminders`;
   - `/reminder off`.~~
6. ~~Use timezone from profile for Telegram reminder commands.~~
7. ~~Avoid missed-reminder spam after downtime.~~

### Acceptance criteria

- ~~reminders fire at expected local time;~~
- ~~downtime does not cause spam storm;~~
- ~~user can list/cancel reminders.~~

---

## Phase 11 — Health protocols

Цель: добавить domain procedures, похожие на Hermes skills, но для здоровья.

### Protocols

1. ~~Weight tracking protocol:
   - log weight;
   - notice trend;
   - avoid overreacting to daily noise.~~
2. ~~Sleep check-in protocol:
   - capture duration/quality;
   - connect patterns cautiously;
   - no diagnosis.~~
3. ~~Workout logging protocol:
   - capture type/duration/intensity;
   - connect to recovery/sleep/weight when enough data exists.~~
4. ~~Food logging protocol:
   - capture meal context;
   - avoid fake calorie precision unless user explicitly tracks calories/macros.~~
5. ~~Weekly review protocol:
   - summarize changes;
   - identify missing data;
   - propose one small next action.~~
6. ~~Medication/symptom caution protocol:
   - log facts;
   - flag urgent language carefully;
   - advise professional care when appropriate;
   - do not give treatment instructions.~~

### Acceptance criteria

- ~~prompt/tool descriptions encode these protocols;~~
- ~~safety tests cover symptom/medication cases;~~
- ~~summaries stay conservative.~~

---

## Phase 12 — Imports and integrations

Только после полезного Telegram + BYOK loop.

### Apple Health

Start with XML export:

- ~~weight;~~
- ~~sleep;~~
- ~~workouts;~~
- ~~steps.~~

### Tasks

1. ~~Add Apple Health XML importer for supported export records.~~
2. ~~Persist imported events through `HealthEntryStore` with `source="import"`.~~
3. ~~Track external IDs in `ImportStore` and skip duplicates on rerun.~~
4. ~~Expose a local `pulsekeeper import-apple-health` CLI command.~~

### Whoop

If API/export is practical:

- recovery;
- sleep;
- workouts.

### Later

- Oura;
- Garmin;
- Google Fit / Health Connect.

### Rules

- ~~all imports idempotent;~~
- ~~external IDs stored in `import_items`;~~
- ~~imported events have `source` and metadata.~~

---

## Phase 13 — Food image logging

Только после text Telegram flow.

### Tasks

1. ~~Telegram photo handling.~~
2. ~~Local media storage.~~
3. ~~Optional BYOK vision provider.~~
4. ~~Image-derived entry tool path.~~
5. ~~Ask clarification if needed.~~

### Guardrail

Do not claim precise calories from images.

---

## Phase 14 — Packaging and deployment

### Tasks

1. ~~`.env.example`.~~
2. ~~Dockerfile.~~
3. ~~docker-compose example.~~
4. ~~Persistent volume docs.~~
5. ~~systemd example.~~
6. ~~GitHub Actions:
   - tests;
   - ruff;
   - build;
   - Docker publish.~~
7. ~~PyPI package for `pipx install pulsekeeper-ai` via tag-gated trusted publishing.~~

---

## Phase 15 — OSS polish

### Tasks

1. ~~Add `LICENSE`.~~
2. ~~Add `CONTRIBUTING.md`.~~
3. ~~Add issue templates.~~
4. ~~Add PR template.~~
5. ~~Add architecture docs:
   - adapters;
   - agent tools;
   - storage;
   - LLM providers;
   - reminders;
   - integrations.~~
6. ~~Add screenshots/GIF.~~
7. ~~Add quickstart that works in under 3 minutes.~~

---

## 7. Recommended immediate next increments

### Increment 1 — ToolRegistry + schemas

- ~~Add `ToolRegistry`.~~
- ~~Finish metadata for all tools.~~
- ~~Migrate existing pydantic schemas into registry entries.~~
- ~~Verify tool args validation.~~

### Increment 2 — Agent tools use SQLite stores

- ~~Replace legacy `agent_runtime.py` JSONL writes with SQLite-backed stores or retire it behind pydantic-ai facade.~~
- ~~Keep JSONL only as legacy/export path.~~
- ~~Add transaction tests around multi-tool turns.~~

### Increment 3 — Complete missing stores

- ~~UserStore.~~
- ~~GatewayStateStore / Telegram offsets.~~
- ~~ReminderStore.~~
- ~~ImportStore.~~

### Increment 4 — Live Telegram polling loop

- ~~`telegram-run`.~~
- ~~offset persistence.~~
- ~~retry/backoff.~~
- ~~graceful shutdown.~~
- ~~safe token-redacted logs.~~

### Increment 5 — Config and doctor

- ~~`pulsekeeper config`.~~
- ~~`pulsekeeper doctor`.~~
- ~~actionable redacted diagnostics.~~

### Increment 6 — Rich summaries + memory

- ~~deterministic summary data builder.~~
- ~~optional LLM prose layer.~~
- ~~write durable summary observations.~~

### Increment 7 — Reminders MVP

- ~~ReminderStore.~~
- ~~scheduler loop.~~
- ~~list/cancel commands.~~
- ~~timezone-aware delivery.~~

---

## 8. Engineering rules

### TDD

Use strict TDD for production code:

1. write failing test;
2. run targeted test and verify expected failure;
3. implement smallest passing code;
4. run targeted test;
5. run full suite;
6. refactor only while green.

### Quality gates

Before each commit:

```bash
uv run pytest -q
uv run ruff check .
```

### Secrets

- never commit `.env`;
- never log bot token/API keys;
- redact secrets in doctor/errors/logs.

### Health safety

- summarize patterns;
- ask clarifying questions;
- do not diagnose;
- do not prescribe;
- for urgent symptoms, recommend professional/emergency care carefully.

---

## 9. Success criteria for MVP

MVP считается useful, когда пользователь может:

1. ~~self-host bot locally;~~
2. ~~configure Telegram token and BYOK LLM;~~
3. ~~send Telegram messages like:
   - “вес 84.2”;
   - “завтрак омлет и кофе”;
   - “тренировка 45 минут зона 2”;
   - “дай сводку за неделю”;
   - “напомни взвешиваться по утрам”;~~
4. ~~receive concise useful confirmations/summaries;~~
5. ~~correct/delete last entry;~~
6. ~~export data;~~
7. ~~understand where data is stored and what goes to LLM provider.~~

---

## 10. Strategic direction

PulseKeeper should become a credible OSS health-agent project and career asset: not a toy parser, but a small, clean, inspectable health-specific agent platform.

The strongest positioning:

> “Self-hosted Telegram-first health memory agent with BYOK LLM, local SQLite memory, typed health tools, careful summaries, and reminders.”

Build order should optimize for GitHub credibility:

1. clean architecture;
2. reliable local setup;
3. visible Telegram UX;
4. privacy/BYOK story;
5. useful summaries/reminders;
6. integrations/images later.
