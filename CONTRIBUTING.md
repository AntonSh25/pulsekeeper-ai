# Contributing to PulseKeeper

Thanks for helping make PulseKeeper a boring, useful, privacy-first health agent.

## Local setup

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run pulsekeeper --help
```

Use a local temporary `--storage-dir` or `PULSEKEEPER_HOME` while testing. Do not point development runs at a user's real health database unless you intentionally want to operate on it.

## Development rules

- Follow strict TDD for production, docs-as-artifacts, packaging, and workflow changes: write a failing test first, watch it fail for the expected reason, implement the smallest passing change, then run the targeted test and the full suite.
- Keep the Telegram-first capture UX simple and reliable.
- Keep BYOK as the default: users provide their own LLM key and can self-host the rest.
- Prefer local SQLite and explicit exports over hidden cloud state.
- Do not add live network calls to unit tests. Use fixtures, seams, or mocked HTTP.

## Quality gate before a PR

```bash
uv run pytest -q
uv run ruff check .
```

Include the targeted RED/GREEN test evidence in the pull request when behavior changes.

## Secrets and privacy

Do not include real Telegram tokens, OpenAI/API keys, health exports, chat IDs, or user-identifying health data in issues, tests, logs, screenshots, or commits. Use placeholders such as `example-token` and verify diagnostics redact configured secrets.

## Health-safety expectations

PulseKeeper may summarize logged patterns, ask clarifying questions, and suggest one small next action for review flows. It must not diagnose, prescribe, or infer medical causes from sparse data. Urgent symptom language should be handled carefully and direct users toward professional or emergency care when appropriate.
