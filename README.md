# PulseKeeper

Open-source Telegram-first health agent with BYOK LLM support.

## Product direction

PulseKeeper is a privacy-first personal health memory agent. It starts as a Telegram bot that can log food, weight, workouts, sleep notes, and health context, then produce daily and weekly summaries.

Core principles:

- **Telegram-first**: fastest possible capture UX.
- **BYOK**: users bring their own LLM API key.
- **Self-host friendly**: local files/database first, no mandatory cloud.
- **Privacy-first**: explicit data ownership and export.
- **Agentic summaries**: not just calorie tracking; it should notice patterns over time.

## MVP scope

- Parse free-text Telegram-style health logs into structured entries.
- Store entries locally as JSONL.
- Produce daily/weekly summaries.
- Support BYOK LLM provider configuration.
- Later: Apple Health / Whoop imports, image food logging, charts.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run pulsekeeper --help
```

## CLI MVP

Parse one message without writing it:

```bash
uv run pulsekeeper parse "вес 84.2 кг"
```

Append a Telegram-style health log to local JSONL storage:

```bash
uv run pulsekeeper log "завтрак: омлет 3 яйца, кофе"
```

Print a daily or weekly markdown summary:

```bash
uv run pulsekeeper summary --date 2026-06-12
uv run pulsekeeper summary --date 2026-06-12 --period week
```

By default data is stored in `~/.pulsekeeper/health.jsonl`. Use `--file path/to/health.jsonl` for tests or custom storage.
