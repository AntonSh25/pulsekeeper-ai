# PulseKeeper — implementation spec (для Codex)

Дата: 2026-06-13 (ревизия 5 — goal-driven within safety rails)
Статус: implementation-ready spec
Репозиторий: `AntonSh25/pulsekeeper-ai`
Тип проекта: **отдельный** OSS-продукт (не плагин Hermes, не платформа с нуля)

> Этот документ — контракт на реализацию. Codex должен делать **ровно** то, что описано, в порядке фаз, с TDD и acceptance-критериями. Где сказано «переиспользовать» — не писать своё. Где сказано «не строить» — не строить.

-----

## 0. Суть и ключевые решения

PulseKeeper — open-source Telegram-first health-agent для **одного пользователя на инстанс** (single-user self-host). Принимает сообщения в Telegram, через LLM с tool-calling ведёт дневник здоровья (еда/вес/тренировки/сон/симптомы/лекарства/заметки), считает КБЖУ и нетто-ккал, делает осторожные сводки, напоминания и инсайты по паттернам. Данные хранятся локально в SQLite.

### Архитектурное решение (зафиксировано)

Не строим generic agent-платформу заново и не живём плагином внутри Hermes. **Гибрид:**

1. **Generic agent-слой берём библиотекой** — `pydantic-ai`. Он даёт agent loop, tool-calling, парсинг вызовов, провайдер-абстракцию. Свой `ModelRuntime`/`ToolRegistry`/`ToolExecutor`/парсер tool-вызовов **не пишем**.
1. **Авторизацию LLM решаем loopback-прокси (паттерн Hermes)** — ядро всегда говорит только OpenAI-compatible с `http://localhost:<port>`. Вся грязь OAuth/подписки изолирована в прокси-процессе. См. раздел 4.
1. **Домен пишем руками** — health-tools, протоколы, сводки, policy/safety. Это и есть ценность продукта.

### Что переиспользуем из Hermes

- **`hermes proxy`** как сайдкар для subscription/OAuth-режима: он выставляет OAuth-backed Codex/Claude/xAI как локальный OpenAI-compatible эндпоинт (по докам Hermes v0.14+). Codex: подтвердить точную команду/порт по докам установленной версии Hermes; не реверсить — это внешний процесс.
- **Паттерн** (не код): транспорт-агностичность через единый OpenAI-compatible интерфейс; multi-provider выбор через конфиг, не через код.

### Non-goals

- Multi-tenant / SaaS. Один деплой = один пользователь = один набор креденшелов.
- Свой agent loop / tool-parser / model runtime (берём `pydantic-ai`).
- Свой OAuth-транспорт к Codex/Claude (берём прокси).
- Большой hand-written NL-парсер как основной intelligence.
- Диагнозы и treatment recommendations.

### Принципы

- **Telegram-first UX**: ввод быстрый, как сообщение самому себе.
- **BYO-LLM**: подписка через прокси (Codex/OAuth) ИЛИ raw API key. Нет обязательного hosted key.
- **Single-user self-host**.
- **Privacy-honest**: вся БД и медиа локально; но контент сообщений уходит выбранному LLM-провайдеру — это явно проговаривается пользователю. Полностью локальный путь — только через local-модели (хуже tool-calling).
- **Tool-calling-first**.
- **Careful health behavior + ED-safety** (раздел 9).
- **Boring useful MVP first**.

-----

## 1. Технологический стек (зафиксирован)

|Слой              |Выбор                                                                  |Примечание                                                                        |
|------------------|-----------------------------------------------------------------------|----------------------------------------------------------------------------------|
|Язык / пакетник   |Python 3.11+, `uv`                                                     |как в текущем репо                                                                |
|Agent loop / LLM  |`pydantic-ai`                                                          |за тонким фасадом `llm/agent.py`                                                  |
|API-key провайдеры|OpenAI-compatible URL провайдера (LiteLLM только для мульти-провайдера)|всегда через `base_url`, см. раздел 4                                             |
|Subscription/OAuth|`hermes proxy` сайдкар                                                 |OpenAI-compatible loopback                                                        |
|Telegram          |`aiogram`                                                              |НЕ raw httpx long-polling; offset держит сам aiogram                              |
|Хранилище         |SQLite + FTS5 через **`aiosqlite>=0.20`**                              |`~/.pulsekeeper/state.db`; stores async; транзакции через `Database.transaction()`|
|Схемы tools       |Pydantic v2                                                            |переиспользуются в pydantic-ai                                                    |
|Тесты             |`pytest`                                                               |unit не ходят в live LLM                                                          |
|Линт              |`ruff`                                                                 |quality gate                                                                      |
|Конфиг            |`config.toml` + `.env`                                                 |секреты только в `.env`                                                           |

**Тонкий фасад над pydantic-ai обязателен.** Весь остальной код зависит от модуля `llm/agent.py` (функция `run_turn(...)` + регистрация tools), а не от внутренностей pydantic-ai. Это страховка от churn библиотеки.

-----

## 2. Целевая архитектура

```text
Telegram  (aiogram gateway)
  -> AgentRuntime            # тонкая оркестрация одного turn
  -> llm/agent.py            # фасад над pydantic-ai (agent loop + tools)
       -> OpenAI-compatible HTTP -> http://localhost:<proxy_port>
  -> LLM access (гибрид, раздел 4):
       - subscription mode: hermes proxy сайдкар (Codex/Claude OAuth)
       - api_key mode:      OpenAI-compatible URL провайдера (или LiteLLM для мульти-провайдера)
  -> health tools (pydantic-ai @tool) -> typed Stores
  -> SQLite (state.db) + FTS5
  -> PolicyLayer             # health-safety + ED-safety + redaction
  -> Scheduler               # reminders/check-ins
  -> Telegram response
```

### Компоненты и зоны ответственности

#### 2.1 Gateway (`gateway/telegram.py`)

- На `aiogram`. Принимает updates, извлекает `chat_id/user_id/text/message_id/attachments`.
- Системные команды (`/start`, `/help`) обрабатывает сам; всё остальное — в `AgentRuntime`.
- Не парсит health-смысл. Безопасное логирование без токенов.
- Single-user: проверяет, что отправитель = владелец инстанса (allowlist по `user_id` из конфига); чужие сообщения вежливо игнорирует.

#### 2.2 AgentRuntime (`runtime/agent_runtime.py`)

Оркестрация **одного** turn:

1. собрать `MessageContext`;
1. взять DB-connection/сессию (без длинной транзакции — мутации делают tools короткими транзакциями, см. 13.6);
1. загрузить profile/preferences/recent memory как `deps` для pydantic-ai;
1. вызвать `llm.agent.run_turn(context, deps)`;
1. применить policy post-checks к ответу;
1. отформатировать Telegram-friendly ответ.

Сам agent loop (вызов модели → tool calls → результаты обратно → финальный текст) **внутри pydantic-ai**. AgentRuntime его не реализует, только конфигурирует:

- `max_tool_iterations` на turn (дефолт 3–5) — защита от зацикливания и от выжигания лимитов;
- при упоре в лимит итераций — graceful fallback (короткий честный ответ + предложение уточнить).

#### 2.3 LLM facade (`llm/agent.py`)

- Конструирует `pydantic_ai.Agent` с system prompt (включает протоколы и safety из раздела 9), списком tools и `deps_type`.
- Модель указывает на OpenAI-compatible эндпоинт (`base_url=http://localhost:<proxy_port>`, см. раздел 4).
- Экспортирует `run_turn(context, deps) -> AgentReply`.
- Fake/test модель для unit-тестов (pydantic-ai `TestModel`/`FunctionModel`) — дефолт в тестах.

#### 2.4 Health tools (`tools/*.py`)

pydantic-ai `@agent.tool` функции с Pydantic input-схемами (раздел 3). Пишут/читают **только** через Stores, не в файлы напрямую. Возвращают structured result.

#### 2.5 Stores (`storage/*.py`)

Типизированные репозитории поверх SQLite:
`Database` (connection/migrations/transactions), `UserStore`, `HealthEntryStore`, `ProfileStore`, `PreferenceStore`, `ConversationStateStore`, `SummaryMemoryStore`, `ReminderStore`, `GatewayStateStore`, `ImportStore`.

`Database.transaction()` — **короткие** транзакции внутри store-методов (атомарны per-операция). Не оборачивать ею LLM-loop (см. 13.6). Включить **WAL mode** при инициализации (лучше параллелизм writer-а gateway и reader-а scheduler, проще online-backup).

#### 2.6 PolicyLayer (`policy/*.py`)

- Зашивается в system prompt (раздел 9) + post-check ответа.
- Redaction секретов в логах/ошибках.
- ED-safety и health-safety проверки.

#### 2.7 Scheduler (`scheduler/*.py`)

- asyncio-loop в том же процессе, что и gateway.
- Хранит reminders, находит due, шлёт в Telegram, учитывает timezone.
- Catch-up алгоритм после downtime (раздел 7, Phase 9).

#### 2.8 CLI (`cli.py`)

`pulsekeeper` (TUI/help), `pulsekeeper gateway` (запуск бота), `pulsekeeper config`, `pulsekeeper doctor`, `pulsekeeper backup`, `pulsekeeper export <jsonl|csv|markdown>`.

-----

## 3. Health tools (input-схемы)

Все схемы — Pydantic v2. Поля `logged_at` опциональны (дефолт now в timezone профиля).

### 3.1 `log_health_entry`

```python
kind: Literal["food","weight","workout","sleep","symptom","medication","note"]
note: str | None
logged_at: datetime | None
value: float | None
unit: str | None
metadata: HealthMetadata | dict | None   # типизировано по kind (см. ниже); dict — только legacy/fallback
```

Пишет через `HealthEntryStore`. Для food без явного трекинга калорий — не выдумывать точные ккал (см. ED-safety).

**Типизированные metadata по `kind` (вместо «голого» dict):**

```python
class NutritionMetadata(BaseModel):       # kind="food"
    calories_kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    carbs_g: float | None = None
    confidence: Literal["explicit", "estimated", "unknown"] = "unknown"

class WorkoutMetadata(BaseModel):         # kind="workout"
    duration_minutes: float | None = None
    calories_burned_kcal: float | None = None
    intensity: str | None = None          # напр. "zone 2", "low", "high"

class SleepMetadata(BaseModel):           # kind="sleep"
    duration_minutes: float | None = None
    quality: str | None = None
    bedtime: datetime | None = None
    wake_time: datetime | None = None

class SymptomMetadata(BaseModel):         # kind="symptom"
    severity: int | None = None           # 1–10, только если явно указано
    location: str | None = None

class MedicationMetadata(BaseModel):      # kind="medication"
    dose: str | None = None               # ТОЛЬКО фиксируем сказанное пользователем
    frequency: str | None = None          # НЕ советовать дозировки/частоту (см. раздел 9)

# дискриминируется по kind; dict оставлен только как legacy/fallback
HealthMetadata = NutritionMetadata | WorkoutMetadata | SleepMetadata | SymptomMetadata | MedicationMetadata
```

`weight`/`note` метаданных обычно не требуют. Medication/symptom tool **логирует факты, но не назначает** дозы/лечение.

**Политика КБЖУ / нетто-ккал (см. раздел 9.1 — goal-driven within rails):**

- если пользователь явно указал калории/БЖУ → `confidence="explicit"`, сохраняем как есть;
- если значения оценены моделью → `confidence="estimated"`, НЕ выдавать ложную точность (округлять, говорить «примерно»);
- **нетто-ккал и дефицит/профицит** показываем **в соответствии с целью профиля** (для `lose` — это by design), нейтрально и как approximate; BMR/TDEE-оценку помечаем `estimated`. Величины ограничены безопасной полосой и override-правилами из 9.1 (недовес/беременность/ED-история и т.д.).

### 3.2 `get_health_summary`

```python
period: Literal["day","week","month","custom"]
start: date | None
end: date | None
```

Сначала deterministic summary data, затем optional LLM-проза.

### 3.3 `ask_clarifying_question`

Уточнение без записи в storage (непонятное время/тип/цель коррекции).

### 3.4 `update_last_entry`

Коррекция последней записи («не 84.2, а 83.9», «не омлет, а творог»).

### 3.5 `delete_last_entry`

`/undo` / «удали последнюю». Soft delete через `deleted_at`.

### 3.6 `set_user_profile_fact`

Stable facts: timezone, **goal (`GoalProfile`, см. 9.1)**, dietary constraint, language.

### 3.7 `search_health_memory`

Поиск по logs/summaries/profile facts. Требует FTS5.

### 3.8 `write_summary_memory`

Durable observations («3 недели вес снижается ~0.3 кг/нед»).

### 3.9 `schedule_reminder` / `list_reminders` / `cancel_reminder`

Создание/список/отмена напоминаний.

-----

## 4. LLM access — гибридная схема (ядро решения)

**Инвариант:** код ядра НИКОГДА не знает про OAuth, подписки и конкретного провайдера. Он делает OpenAI-compatible запросы на `http://localhost:<proxy_port>`. Разница режимов живёт в том, **что слушает этот порт**.

> Для онбординга по умолчанию (README/quickstart) — **api_key mode** как самый простой путь для широкой аудитории; subscription mode через `hermes proxy` — advanced-путь. См. Phase 14.

### Режим A — subscription (через `hermes proxy`)

- На том же VPS запущен `hermes proxy`, который через Codex-OAuth (ChatGPT-подписка) / Claude-OAuth выставляет OpenAI-compatible loopback.
- PulseKeeper `base_url` = адрес этого прокси.
- Codex: точную команду запуска и порт взять из документации установленного Hermes (v0.14+). Не хардкодить — вынести в `config.toml` (`llm.base_url`).
- Ограничение: usage идёт по лимитам плана. Логировать число вызовов/итераций (раздел 8, usage awareness).

### Режим B — api_key (всегда через OpenAI-compatible endpoint)

- `auth_mode = api_key`. Ключ в `.env` (`OPENAI_API_KEY`/…).
- `base_url` указывает на **OpenAI-compatible эндпоинт провайдера** (напр. `https://api.openai.com/v1`) — для одного провайдера LiteLLM НЕ нужен.
- Для мульти-провайдерности — поднять **LiteLLM** как локальный OpenAI-compatible прокси и указать `base_url` на него.
- Биллинг — metered, per-token.

**Инвариант (зафиксирован, Variant A):** `llm/agent.py` строит модель ТОЛЬКО как OpenAI-compatible клиент к `base_url`. Provider-specific клиентов pydantic-ai (Anthropic SDK напрямую и т.п.) в коде НЕТ — весь provider mess живёт снаружи (в `hermes proxy` или LiteLLM). Разница режимов = разный `base_url` + наличие/отсутствие `api_key`.

### Config (`config.toml`)

```toml
[llm]
auth_mode = "subscription"     # "subscription" | "api_key"
base_url  = "http://localhost:8787/v1"
model     = "model-name-from-proxy"  # placeholder: точное имя зависит от прокси/провайдера
timeout   = 60
max_tool_iterations = 4
```

`.env` (никогда не коммитить): `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_USER_ID` (Telegram id владельца, для allowlist), `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` (только для режима B).

> Разведение id: `OWNER_TELEGRAM_USER_ID` — внешний Telegram id (только для проверки «свой/чужой» на входе gateway). Внутри системы везде ходит internal `user_id` из SQLite; gateway резолвит Telegram id → internal `user_id` через `gateway_accounts` (см. 13.6).

### Tool-calling reliability

- Зафиксировать в docs минимальный рекомендованный класс модели (надёжный native tool calling).
- Невалидные/галлюцинированные tool-аргументы → controlled error обратно в loop (pydantic-ai это делает), не краш.
- Если модель не умеет tools — честный отказ, НЕ молчаливый фолбэк в parser.

-----

## 5. SQLite схема

Каждая таблица: `created_at`, `updated_at` где применимо. Миграции — явные файлы в `migrations/`, идемпотентные, применяются на старте; никаких неявных `CREATE TABLE` внутри tools.

- **`users`** — `id`, timestamps. (Single-user: одна строка-владелец; таблица оставлена для чистоты модели.)
- **`gateway_accounts`** — `id`, `user_id`, `gateway`(‘telegram’), `external_user_id`, `external_chat_id`, timestamps.
- **`health_entries`** — `id`, `user_id`, `kind`, `note`, `value`, `unit`, `logged_at`, `source`(‘telegram’|‘cli’|‘import’|‘manual’), `metadata_json`, `schema_version`, `created_at`, `updated_at`, `deleted_at`.
- **`health_entries_fts`** — FTS5 по `note` + полезный metadata-текст.
- **`user_profile_facts`** — `id`, `user_id`, `key`, `value_json`, `confidence`, `source`, timestamps.
- **`preferences`** — `id`, `user_id`, `key`, `value_json`, timestamps.
- **`conversation_state`** — `id`, `user_id`, `state_type`, `payload_json`, `expires_at`, timestamps.
- **`summary_memory`** — `id`, `user_id`, `period_start`, `period_end`, `kind`, `text`, `metadata_json`, timestamps.
- **`summary_memory_fts`** — FTS5 по summary text.
- **`reminders`** — `id`, `user_id`, `type`, `schedule_json`, `timezone`, `enabled`, `last_sent_at`, `next_due_at`, timestamps.
- **`telegram_offsets`** *(опционально / на будущее)* — `id`, `bot_profile`, `offset`, `updated_at`. **Для MVP НЕ использовать:** aiogram long-polling сам держит offset (Telegram отдаёт getUpdates с server-side offset, подтверждённые updates не реплеятся), restart-safety закрыта библиотекой. Таблицу заводить только если понадобится webhook/custom polling.
- **`imports`** — `id`, `user_id`, `source`, `started_at`, `finished_at`, `metadata_json`.
- **`import_items`** — `id`, `import_id`, `external_id`, `status`, `metadata_json`. (Идемпотентность импорта по `external_id`.)
- **`schema_migrations`** — `version`, `applied_at`.

-----

## 6. Что уже есть в репо и судьба этого кода

Из текущего scaffolding:

- **Оставить:** package под `src/pulsekeeper`, CLI-entrypoint, pytest+ruff конфиг, доменную модель `HealthEntry`, multi-user storage routing (переосмыслить как single-user), Telegram update-JSON парсинг.
- **Заменить:** hand-rolled `AgentRuntime`/`MessageContext`/`ToolExecutor`/typed-tool-call seam → на pydantic-ai через `llm/agent.py`. Свой Telegram polling seam → aiogram. JSONL-storage → SQLite (JSONL остаётся только как export/debug).

-----

## 7. Implementation plan (фазы)

Каждая фаза: строгий TDD (failing test → minimal code → green → refactor), в конце `uv run pytest -q` и `uv run ruff check .` зелёные.

### Phase 1 — SQLite foundation

SQLite через `aiosqlite`; stores async; транзакции через `Database.transaction()`. **Разбить на мелкие PR-инкременты (по одному за раз, каждый — отдельный green-цикл TDD):**

1. Add deps (`aiosqlite>=0.20`) + storage package skeleton (`storage/`).
1. `Database` (async connection) + migration runner (идемпотентный, из `migrations/`).
1. Initial schema migration (раздел 5).
1. `HealthEntryDraft` / `HealthEntryPatch` доменные модели.
1. `HealthEntryStore.append` / `list` (+ тесты с temp DB).
1. `HealthEntryStore.update` / `soft_delete` / `get_last`.
1. FTS5 для `health_entries` + `HealthEntryStore.search`.
1. Transaction tests + migration idempotency tests.

**Acceptance:** fresh DB инициализируется детерминированно; миграции идемпотентны; CRUD + soft delete работают; FTS поиск работает; `Database.transaction()` атомарен.

### Phase 2 — Memory stores

**Tasks:** `ProfileStore`, `PreferenceStore`, `ConversationStateStore` (с expiry), `SummaryMemoryStore` (+FTS5); тесты.
**Acceptance:** stable facts помнятся; short-lived state истекает; summary memory ищется.

### Phase 3 — pydantic-ai agent + health tools (fake model)

**Tasks:** добавить deps (`pydantic-ai>=...`, при необходимости `httpx` для OpenAI-транспорта); `llm/agent.py` фасад; зарегистрировать tools 3.1–3.9 как `@agent.tool` с Pydantic-схемами, завязать на Stores; `deps` = профиль/память/now/timezone; **минимальный safety system-prompt уже здесь** (no diagnosis / no treatment / ED-safety базово, раздел 9); тесты на fake-модели (`TestModel`/`FunctionModel` из pydantic-ai), где модель возвращает tool call; **базовые unit safety-тесты** (модель не выдаёт диагноз/назначение/агрессивный дефицит на заранее заданных кейсах).
**Acceptance:** fake-модель вызывает `log_health_entry` и `get_health_summary`; невалидные tool-args → controlled error; tools пишут только через Stores; базовые safety-тесты зелёные; tests green.

### Phase 4 — LLM access (гибрид) + de-risk

**Tasks:** config `[llm]` (auth_mode/base_url/model/timeout/max_tool_iterations); `.env` loading + redaction; режим A — интеграция с `hermes proxy` (адрес из конфига, инструкция запуска в docs); режим B — OpenAI-compatible URL провайдера (LiteLLM только для мульти-провайдера); провайдер-тесты на mocked HTTP. **Fallback зафиксировать:** если `hermes proxy` недоступен/изменился — переключаемся на api_key mode.
**De-risk (обязательно здесь):** одноразовый ручной spike с РЕАЛЬНОЙ моделью — проверить, что NL вроде «вес 84.2», «завтрак омлет и кофе» надёжно превращаются в правильные tool calls. **Spike включает ED/symptom smoke-кейсы** (агрессивный дефицит, тревожный симптом) — не подключать реальную модель без хотя бы дымовой проверки safety. **Не коммитить реальные ключи и логи запросов.**
**Acceptance:** unit-тесты не ходят в live LLM; missing creds → понятная ошибка; секреты не печатаются; spike подтверждает NL→tool-calls и базовое safety-поведение на рекомендованной модели.

### Phase 5 — Telegram gateway (aiogram)

**Tasks:** добавить dep `aiogram>=3`; `gateway/telegram.py` на aiogram; owner-allowlist по `OWNER_TELEGRAM_USER_ID` (внешний Telegram id), затем резолв в internal `user_id` через `gateway_accounts`; normal text → AgentRuntime → pydantic-ai; slash-команды → tools (`/summary`, `/today`, `/week`, `/undo`, `/profile`, `/reminders`); `/start`,`/help` минуют модель; Telegram-safe форматирование; **offset держит сам aiogram — свой offset-manager НЕ строить** (см. раздел 5); e2e-тесты с mocked transport + fake model.
**Acceptance:** «вес 84.2» → tool call (не parser); «дай сводку за неделю» → summary tool; `/week` использует тот же summary-путь; рестарт не реобрабатывает старые updates; токен не логируется.

### Phase 6 — Config, doctor, backup, export, onboarding

**Tasks:** `config.toml` support; `.env.example`; `pulsekeeper config`; `pulsekeeper doctor` (storage writable, миграции OK, telegram token, llm base_url достижим, no unsafe config); redacted diagnostics; `pulsekeeper backup` — **online-safe** (SQLite Online Backup API или `VACUUM INTO`, НЕ голый `cp`; при WAL — корректный checkpoint/копирование, чтобы снапшот не был битым); **export:** `pulsekeeper export jsonl|csv|markdown` (health entries) + экспорт profile/memory/reminders, с опцией redaction (вырезать заметки/симптомы при шаринге); first-run onboarding в Telegram — захват timezone, **цели (`GoalProfile`)** и базового профиля ДО включения reminders; **first-run owner setup:** пока `OWNER_TELEGRAM_USER_ID` не задан, `/start` от любого отвечает его собственным Telegram id + подсказкой прописать переменную; после того как owner задан — не-owner молча игнорируется.
**Acceptance:** новый пользователь запускает doctor и понимает next action; doctor не течёт секретами; backup создаёт восстановимый (не битый) снапшот даже в WAL; export даёт jsonl/csv/markdown + redaction работает; timezone захвачен до scheduler; owner-id настраивается без внешних инструментов.

### Phase 7 — Corrections & undo

**Tasks:** `update_last_entry`, `delete_last_entry`/soft delete, `/undo`; NL-коррекции («не 84.2, а 83.9», «удали последнюю», «это был обед, не завтрак»); conversation state при неоднозначной цели.
**Acceptance:** последняя запись корректируется; удаление обратимо/аудируемо; неоднозначные коррекции → уточнение.

### Phase 8 — Summaries & insights

**Tasks:** deterministic summary builder; no-LLM fallback; optional LLM-проза; блоки (вес/еда/сон/тренировки/симптомы-лекарства/заметки); pattern detection (тренды/стрики/заметные изменения/missing data); durable weekly/monthly observations в summary memory.
**Acceptance:** daily/weekly сводки работают без LLM; LLM-сводка не диагностирует; durable паттерны сохраняются как summary memory.

### Phase 9 — Reminders & scheduler

**Tasks:** reminder model/store; asyncio scheduler loop; Telegram-доставка; tools `schedule_reminder`/list/cancel; команды `/remind weight daily 09:00`, `/reminders`, `/reminder off`; timezone из профиля.
**Catch-up алгоритм (явно):** на старте сравнить `next_due_at` с now; пропущенные за downtime НЕ слать пачкой — либо тихо проскипать с пересчётом `next_due_at` на следующий слот, либо один консолидированный «пока меня не было». Политику зафиксировать в коде.
**Acceptance:** reminders срабатывают в локальном времени; downtime не вызывает spam-шторм; список/отмена работают.

### Phase 10 — Health protocols & safety

**Tasks:** закодировать протоколы в prompt/описаниях tools — weight (тренд, не оверреагировать на шум), sleep (осторожные связи, no diagnosis), workout (тип/длительность/интенсивность), food (контекст приёма, без ложной точности калорий), weekly review (изменения + missing data + одно маленькое следующее действие), medication/symptom caution (логировать факты, осторожно с urgent-языком, советовать профпомощь, НЕ давать лечение).
**Safety-тесты (расширенный suite поверх базовых из Phase 3):** symptom/medication кейсы; **goal-driven рельсы (9.1):** цель `lose` → дефицит показывается; запрос слишком агрессивной скорости/интейка → флагуется (не молча клампится и не молча исполняется); недовес → не поддерживаем дальнейшее похудение; беременность/ED-история/clinical_supervision → override-режим и деференция; «наказывающий» фрейминг не воспроизводится.
**Acceptance:** протоколы зашиты; safety-тесты зелёные; сводки консервативны.

### Phase 11 — Imports & integrations

Только после рабочего Telegram+LLM loop. Apple Health (XML export: вес/сон/тренировки/шаги); Whoop (если API/export практичен: recovery/sleep/workouts); позже Oura/Garmin/Google Fit. Правила: все импорты идемпотентны (external_id в `import_items`); у событий `source` и metadata.

### Phase 12 — Food image logging

Только после text-flow. Telegram photo handling; локальное media-хранилище; optional vision-провайдер через тот же LLM-фасад; image→entry; уточнение при необходимости. **Guardrail:** не заявлять точные калории по фото.

### Phase 13 — Packaging & deploy

`.env.example`; Dockerfile; **docker-compose с двумя сервисами — pulsekeeper + (опционально) hermes proxy сайдкар**; persistent volume для `~/.pulsekeeper`; systemd example; GitHub Actions (tests/ruff/build/docker publish); позже PyPI (`pipx install pulsekeeper-ai`).

### Phase 14 — OSS polish

`LICENSE`, `CONTRIBUTING.md`, issue/PR templates; architecture docs (gateway/tools/storage/llm-access+proxy/reminders/integrations); скриншоты/GIF; **quickstart с двумя путями:** (1) **Easy — api_key mode** (OpenAI-compatible provider URL + ключ) как путь по умолчанию для широкой OSS-аудитории; (2) **Advanced — subscription mode** (`hermes proxy` сайдкар). `hermes proxy` НЕ обязателен как первый путь для всех. Цель quickstart (easy-путь) < 3 минут.

-----

## 8. Engineering rules

### TDD

failing test → запустить таргетный тест (убедиться, что падает) → минимальный код → таргетный тест → полный прогон → рефактор только на зелёном.

### Quality gates (перед каждым коммитом)

```bash
uv run pytest -q
uv run ruff check .
```

### Secrets

Не коммитить `.env`; не логировать токены/ключи/OAuth; redaction в doctor/errors/logs.

### Observability

Structured **redacted** tool-traces: какой tool вызван, с какими (без секретов) аргументами, какой результат. Нужно для дебага и для OSS-контрибьюторов.

### Usage awareness

Логировать число tool-итераций и LLM-вызовов на turn. В subscription-режиме это про лимиты плана, в api_key — про стоимость. Опционально — мягкий per-day лимит вызовов, чтобы chatty loop не упирался молча.

-----

## 9. Health safety (обязательно)

Зашить в system prompt и проверять post-check:

- **no diagnosis**, **no treatment instructions**.
- **Goal-driven personalization within safety rails (first-class):** см. раздел 9.1. Поведение строится от цели пользователя; ED-safety реализована как рельсы, а не как блок всего, что связано с дефицитом.
- **secrets redaction**, no token leakage.
- **clear provider boundaries** + явное проговаривание пользователю (Privacy-honest).
- **symptom/medication caution:** логировать факты; осторожно с urgent-языком; советовать профессиональную/экстренную помощь когда уместно; не назначать лечение.

Safety-тесты: базовые в Phase 3, smoke-кейсы в Phase 4 spike, расширенный suite в Phase 10.

### 9.1 Goal-driven personalization within safety rails

**Принцип (зафиксирован):** отталкиваемся от цели пользователя; рельсы кусаются только на краях.

1. **Цель — first-class факт профиля** (`goal`, см. ниже). Все таргеты, сводки, фрейминг, показ нетто-ккал/дефицита строятся от неё. Для `lose` дефицит показывается и это by design.
1. **Направление честим, величину ограничиваем (настраиваемые дефолты):**
- скорость изменения веса ~0.25–1.0% массы тела/неделю;
- дефицит/профицит умеренный (мягкий потолок ~20–25% от оценочного TDEE);
- не одобрять интейк ниже консервативного floor (конфиг; дефолт не ниже BMR на длительном горизонте без клинического наблюдения);
- запрос за пределами безопасной полосы НЕ исполняем молча и НЕ молча клампим — сообщаем пользователю и предлагаем безопасный диапазон.
1. **Детект тревожных признаков — всегда, независимо от цели:** устойчиво очень низкий интейк, потеря быстрее безопасной, недовес/тренд в недовес, «наказывающий»/обсессивный фрейминг, просьбы пробить floor → тон смещается к заботе + предложение профпомощи (без «целей по ограничению»).
1. **Жёсткие override — цель НЕ перебивает:**
- недовес (напр. BMI < 18.5 или тренд туда) → не поддерживаем дальнейшее похудение, флагуем;
- беременность → не ведём weight-loss дефицит;
- заявленная ED-история / клиническое наблюдение → сильная деференция к профпомощи, консервативный режим;
- никогда не подаём ограничение как наказание.
1. **Нетто-ккал/дефицит** показываем когда релевантно цели, нейтрально и как **approximate**; не геймифицировать, не катастрофизировать. Любую оценку расхода (BMR/TDEE) помечать `estimated`.

**Goal как факт профиля** (через `set_user_profile_fact` / onboarding; хранится локально):

```python
class GoalProfile(BaseModel):
    goal_type: Literal["lose","maintain","gain","recomp","performance","medical_managed","unspecified"] = "unspecified"
    target_rate_kg_per_week: float | None = None   # валидируется в безопасную полосу по goal_type
    target_weight_kg: float | None = None
    flags: list[Literal["pregnancy","ed_history","clinical_supervision"]] = []  # драйвят override-режимы
```

Это design-level правила продукта, не медицинские назначения; PulseKeeper не клиницист (consistent с no-diagnosis).

-----

## 10. Success criteria (MVP)

Пользователь может:

1. self-host бота локально (single-user);
1. сконфигурировать Telegram token и BYO-LLM (subscription через прокси ИЛИ api key);
1. слать сообщения: «вес 84.2», «завтрак омлет и кофе», «тренировка 45 минут зона 2», «дай сводку за неделю», «напомни взвешиваться по утрам»;
1. получать concise полезные подтверждения/сводки;
1. корректировать/удалять последнюю запись;
1. экспортировать данные и бэкапить БД;
1. понимать, где хранятся данные и что уходит LLM-провайдеру.

-----

## 11. Reuse-vs-build (резюме для Codex)

|Возможность                                     |Решение                                                                                   |
|------------------------------------------------|------------------------------------------------------------------------------------------|
|Agent loop, tool-calling, провайдер-абстракция  |**Buy** — pydantic-ai (за фасадом `llm/agent.py`)                                         |
|Subscription/OAuth → OpenAI-compatible          |**Reuse** — `hermes proxy` сайдкар                                                        |
|Multi-provider api_key                          |**Buy** — LiteLLM как локальный OpenAI-compatible прокси (один провайдер — просто его URL)|
|Telegram транспорт                              |**Buy** — aiogram                                                                         |
|Health tools, протоколы, сводки, КБЖУ/нетто-ккал|**Build** — это домен                                                                     |
|Stores, схема, миграции, FTS5                   |**Build** — это домен                                                                     |
|PolicyLayer / ED-safety                         |**Build** — это домен                                                                     |
|Scheduler + catch-up                            |**Build** (тонко)                                                                         |
|Свой ModelRuntime/ToolExecutor/tool-parser      |**НЕ строить**                                                                            |
|Свой Telegram long-polling на httpx             |**НЕ строить**                                                                            |
|Multi-tenant / key-management                   |**НЕ строить**                                                                            |

-----

## 12. Strategic positioning (для README)

> «Self-hosted Telegram-first health memory agent. Bring your own LLM (подписка через OAuth-прокси или API-ключ), local SQLite memory, typed health tools, careful summaries, reminders.»

Долгосрочная ставка — LLM-доступ станет базовым, как интернет; подписочные agent-транспорты (Codex/OAuth) делают это уже частично реальным. MVP сознательно сужен до single-user self-host для tech-аудитории — это та аудитория, которую продукт обслуживает сегодня. «Health-агент для каждого» — направление, а не обещание MVP.

-----

## 13. Interface contracts (швы, без реализации)

> Это **контракт**, а не код. Описаны формы типов, сигнатуры ключевых швов и поток одного turn. Реализация (точные вызовы pydantic-ai, `RunContext`, декораторы, ORM/SQL) — на Codex против установленных версий. Типы можно уточнять, но публичные границы между слоями должны соответствовать этим формам — об них строится остальной код. Сигнатуры async там, где задействован I/O.

### 13.1 Данные turn’а

```python
@dataclass
class MessageContext:
    user_id: int                # internal user id владельца (резолвится из Telegram id)
    chat_id: int                # Telegram chat для ответа
    text: str
    attachments: list[Attachment]   # фото и т.п.; может быть пустым
    now: datetime                   # tz-aware, в timezone профиля
    timezone: str                   # IANA, напр. "Europe/Moscow"
    message_id: int
    source: Literal["telegram", "cli"]

@dataclass
class AgentDeps:                # прокидывается в tools через pydantic-ai deps
    stores: Stores             # бандл репозиториев (13.4)
    profile: ProfileSnapshot   # факты/goal/constraints, прочитанные на старте turn
    preferences: dict
    recent_memory: list[MemoryItem]
    now: datetime
    timezone: str
    user_id: int               # internal user id (тот же, что в MessageContext)

@dataclass
class AgentReply:
    text: str                              # готовый Telegram-friendly ответ
    tool_trace: list[ToolTraceItem]        # redacted: name, args(без секретов), ok
    used_iterations: int
    finished_reason: Literal["completed", "max_iterations", "model_error", "policy_blocked"]
```

### 13.2 LLM facade (`llm/agent.py`)

```python
@dataclass
class LLMConfig:
    auth_mode: Literal["subscription", "api_key"]
    base_url: str
    model: str
    timeout: int = 60
    max_tool_iterations: int = 4

def build_agent(config: LLMConfig, policy_prompt: str) -> Agent: ...
    # конструирует pydantic-ai Agent: модель → base_url, system prompt
    # включает protocols+safety (policy_prompt), регистрирует health-tools, deps_type=AgentDeps

async def run_turn(agent: Agent, context: MessageContext, deps: AgentDeps) -> AgentReply: ...
    # гоняет agent loop, ограниченный config.max_tool_iterations
    # при упоре в лимит → finished_reason="max_iterations" + graceful текст
    # при ошибке модели → finished_reason="model_error", без краша процесса
```

Остальной код зависит **только** от `build_agent` / `run_turn` / `AgentReply`, не от внутренностей pydantic-ai.

### 13.3 Tool contract

Каждый health-tool:

- принимает свою Pydantic input-модель (раздел 3) + доступ к `AgentDeps`;
- пишет/читает **только** через `deps.stores`;
- возвращает structured-результат формы `ToolResult`;
- при невалидном состоянии (нет target для коррекции и т.п.) — поднимает контролируемую ошибку, которую loop отдаёт модели как tool-error, **не** роняя процесс.

```python
class ToolResult(BaseModel):
    ok: bool
    summary: str                 # короткое человекочитаемое (для финального ответа)
    data: dict | None = None     # structured payload для модели/последующих шагов

# форма tool-функции (точный декоратор/сигнатуру pydantic-ai подставит Codex):
# async def log_health_entry(ctx: <deps=AgentDeps>, args: LogHealthEntryInput) -> ToolResult
```

### 13.4 Stores (минимальные контракты)

Только методы, от которых зависят tools/runtime. Возвращаемые типы — доменные модели (`HealthEntry`, и т.п.).

```python
class HealthEntryStore:
    async def append(self, user_id: int, entry: HealthEntryDraft) -> HealthEntry: ...
    async def list(self, user_id: int, *, start: datetime, end: datetime,
                   kinds: list[str] | None = None) -> list[HealthEntry]: ...
    async def get_last(self, user_id: int, *, kind: str | None = None) -> HealthEntry | None: ...
    async def update(self, entry_id: int, patch: HealthEntryPatch) -> HealthEntry: ...
    async def soft_delete(self, entry_id: int) -> None: ...        # ставит deleted_at
    async def search(self, user_id: int, query: str, *, limit: int = 20) -> list[HealthEntry]: ...  # FTS5

class ProfileStore:
    async def get_fact(self, user_id: int, key: str) -> Any | None: ...
    async def set_fact(self, user_id: int, key: str, value: Any, *, source: str) -> None: ...
    async def get_timezone(self, user_id: int) -> str | None: ...

class ConversationStateStore:
    async def put(self, user_id: int, state_type: str, payload: dict, *, ttl_seconds: int) -> None: ...
    async def get(self, user_id: int, state_type: str) -> dict | None: ...   # None если истёк

class SummaryMemoryStore:
    async def write(self, user_id: int, item: SummaryMemoryDraft) -> None: ...
    async def search(self, user_id: int, query: str, *, limit: int = 10) -> list[SummaryMemory]: ...

class ReminderStore:
    async def schedule(self, user_id: int, reminder: ReminderDraft) -> Reminder: ...
    async def list(self, user_id: int) -> list[Reminder]: ...
    async def cancel(self, reminder_id: int) -> None: ...
    async def due(self, *, at: datetime) -> list[Reminder]: ...    # для scheduler

class Stores:   # бандл, прокидывается в AgentDeps
    health: HealthEntryStore
    profile: ProfileStore
    preferences: PreferenceStore
    conversation: ConversationStateStore
    summary: SummaryMemoryStore
    reminders: ReminderStore
```

### 13.5 PolicyLayer

```python
class PolicyResult(BaseModel):
    allowed: bool
    replacement_text: str | None = None   # если нужно заменить/смягчить ответ
    reason: str | None = None

class PolicyLayer:
    def prompt_fragment(self) -> str: ...                      # вшивается в system prompt (раздел 9)
    def check_reply(self, reply: AgentReply, context: MessageContext) -> PolicyResult: ...
```

`AgentRuntime` вызывает `check_reply` после `run_turn`; при `allowed=False` отдаёт `replacement_text`.

### 13.6 Поток одного turn (контракт оркестрации)

1. Gateway получает update, проверяет Telegram id отправителя против `OWNER_TELEGRAM_USER_ID` (чужих игнор), резолвит в internal `user_id` через `gateway_accounts`, собирает `MessageContext`.
1. `AgentRuntime` берёт DB-**connection/сессию** (НЕ открывает длинную транзакцию), грузит `ProfileSnapshot`, timezone, recent memory → собирает `AgentDeps`.
1. `AgentRuntime` → `run_turn(agent, context, deps)`.
1. Внутри loop tools мутируют состояние через `deps.stores`; **каждый tool делает свою короткую транзакцию на свои записи** (`Database.transaction()` внутри store-метода); tool-ошибки возвращаются модели контролируемо; loop ограничен `max_tool_iterations`.
1. На финише/лимите → `AgentReply` (text + redacted `tool_trace` + `used_iterations` + `finished_reason`).
1. `AgentRuntime` → `PolicyLayer.check_reply`; при блоке подменяет текст.
1. Gateway форматирует и отправляет; usage/iterations логируются (раздел 8).

> **Транзакционная модель (зафиксирована):** НЕ держать SQLite-транзакцию открытой вокруг всего LLM-loop — между tool-calls есть model latency/await/network, и длинная транзакция держала бы DB-lock. Транзакции короткие, внутри store-методов/tools, атомарны per-операция.
> **Следствие (осознанное решение):** turn НЕ атомарен между несколькими tools. Если tool-2 упал после коммита tool-1, запись tool-1 остаётся. Для дневника здоровья это корректно — каждый залогированный факт самостоятелен, модель/пользователь доисправят следующим ходом. Если когда-то понадобится мульти-tool атомарность — это явный отдельный механизм, не дефолт.

> Конкретные имена pydantic-ai (`Agent`, `RunContext`, декораторы tools) и способ прокидывания `deps` Codex подставляет под установленную версию. Контракт фиксирует **формы и поток**, а не точки вызова библиотеки.

-----

## Приложение A — реальная структура Hermes (референс для Codex)

> Источник: официальные доки Hermes, страница релизов и DeepWiki-индекс репозитория `NousResearch/hermes-agent` (снапшот ~6 апреля 2026, commit `d3d5b8`). **Hermes развивается очень быстро** — перед использованием конкретных имён/команд Codex обязан сверяться с установленной версией. Это референс «как у них устроено», а не спецификация для копирования один-в-один. Ядро Hermes на Python (3.11, `uv`); TUI — отдельный React/Ink. Лицензия MIT.

### A.1 Ключевые модули/директории (подтверждённые)

|Модуль                              |Назначение                                                                                                                                                                                                                                                      |
|------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|`hermes_cli/`                       |CLI-команды (`hermes`, `model`, `tools`, `config`, `gateway`, `doctor`, `proxy`, …). Конфиг env-переменных, в т.ч. `OPTIONAL_ENV_VARS`                                                                                                                          |
|`run_agent.py` + `AIAgent`          |Conversation/agent loop. На нём остаются streaming, retries, prompt cache, credential refresh                                                                                                                                                                   |
|`agent/transports/`                 |**Transport-слой за `ProviderTransport` ABC.** Конкретные транспорты: `AnthropicTransport`, `ChatCompletionsTransport`, `ResponsesApiTransport`, `BedrockTransport`. Каждый владеет message conversion, tool conversion, kwargs assembly, response normalization|
|`tools/` + `toolsets.py`            |Реестр built-in tools и группировка в toolsets; `tools/lazy_deps.py` — ленивая доустановка провайдер-пакетов                                                                                                                                                    |
|плагины (plugin route)              |Кастомные/project-local tools БЕЗ правки ядра — рекомендованный путь для своих инструментов                                                                                                                                                                     |
|messaging gateway                   |Единый gateway-процесс + platform adapters (Telegram/Discord/Slack/…), session/media management, pairing/security                                                                                                                                               |
|skills system                       |Skills + Skills Hub; `agentskills.io`-совместимый формат                                                                                                                                                                                                        |
|`optional-mcps/<name>/manifest.yaml`|Каталог одобренных MCP-серверов                                                                                                                                                                                                                                 |
|context files                       |`SOUL.md` (identity, из `HERMES_HOME`), `AGENTS.md`/`.hermes.md`/`CLAUDE.md`/`.cursorrules` (project context)                                                                                                                                                   |
|cron                                |Built-in планировщик с доставкой в любой канал                                                                                                                                                                                                                  |
|`~/.hermes/`                        |Вся пользовательская конфигурация/данные/runtime-state (вне репо)                                                                                                                                                                                               |

Полная карта — DeepWiki (`deepwiki.com/NousResearch/hermes-agent`), разделы 4 (Core Agent), 5 (Tool System), 7 (Messaging Gateway), 8 (Skills), 10.2 (Provider Runtime Resolution), 2.3 (Authentication and Providers).

### A.2 Transport-паттерн (главный референс)

Hermes абстрагировал format conversion + HTTP transport в `agent/transports/` за `ProviderTransport` ABC; конкретные транспорты нормализуют ответы каждого провайдера, а общий цикл (`AIAgent`) их не знает. Провайдер/модель переключаются конфигом (`hermes model`) **без изменений кода**.

**Вывод для нас:** этот же эффект мы получаем «бесплатно» от `pydantic-ai` — не реализуем `ProviderTransport`-аналог руками. А подписочную авторизацию (Codex OAuth / GPT-5.5 и т.п.), которую Hermes решает на уровне provider-runtime + `hermes proxy`, мы выносим в сайдкар-прокси (раздел 4), чтобы наше ядро видело только один OpenAI-compatible эндпоинт.

### A.3 Tool-registry паттерн (референс)

Built-in tool регистрируется централизованно (упрощённо):

```python
registry.register(
    name="weather",
    toolset="weather",
    schema=WEATHER_SCHEMA,          # JSON schema аргументов
    handler=lambda args, **kw: weather_tool_async(args.get("location", "")),
    check_fn=check_weather_requirements,  # доступность (ключи/условия)
    is_async=True,
)
```

Идеи, которые забираем (не код): (1) **schema-first** объявление tool; (2) `check_fn` — проверка доступности до вызова; (3) группировка в **toolsets**. У нас это ложится на `pydantic-ai @agent.tool` + Pydantic-схемы: schema-first уже есть, `check_fn` → проверки внутри tool/в `deps`, toolset → логическая группировка health-tools.

> Важно: Hermes явно советует для кастомных инструментов **plugin route**, а не правку `tools/` ядра. Мы и так делаем отдельный продукт, так что аналог «правки ядра» нам не грозит — но если в какой-то момент захочется жить плагином внутри Hermes, целиться надо именно в plugin-интерфейс.

### A.4 Маппинг Hermes → PulseKeeper

|В Hermes                                      |В PulseKeeper                                       |Решение                                                    |
|----------------------------------------------|----------------------------------------------------|-----------------------------------------------------------|
|`agent/transports/` + `ProviderTransport` ABC |`llm/agent.py` поверх pydantic-ai                   |**не реплицируем**, берём библиотекой                      |
|`hermes proxy` (OAuth → OpenAI-compatible)    |тот же `hermes proxy` как сайдкар                   |**reuse как процесс**                                      |
|provider runtime resolution / `hermes model`  |поле `llm.model` + `llm.base_url` в `config.toml`   |конфиг, не код                                             |
|`tools/` + `toolsets.py` + `registry.register`|health-tools как `@agent.tool` (раздел 3)           |**build** (домен), паттерн schema-first/check_fn заимствуем|
|messaging gateway + platform adapters         |`gateway/telegram.py` на aiogram                    |**build** (тонко), один канал                              |
|skills system / `SOUL.md` / context files     |system prompt с протоколами + safety (раздел 9)     |**build** (домен)                                          |
|cron                                          |`scheduler/` asyncio-loop + catch-up                |**build** (тонко)                                          |
|`~/.hermes/`                                  |`~/.pulsekeeper/`                                   |свой layout (раздел 5)                                     |
|`tools/lazy_deps.py`                          |extras в `pyproject.toml` для провайдеров/интеграций|по необходимости                                           |

### A.5 Что проверить против установленной версии Hermes (TODO для Codex)

1. Точная команда и порт `hermes proxy`; какие OAuth-провайдеры он отдаёт в этой версии → прописать в `config.toml.llm.base_url`.
1. Имя модели для subscription-режима (может отличаться от API-строк, напр. `gpt-5.5` через Codex-catalog).
1. Жив ли `hermes proxy` как способ авторизации в текущем релизе (если Nous переименует/изменит — fallback на api_key режим, раздел 4).