## Summary

-

## TDD evidence

- RED targeted test and expected failure:
- GREEN targeted test result:
- Full suite: `uv run pytest -q`
- Lint: `uv run ruff check .`

## Privacy and secret safety

- [ ] No real Telegram tokens, API keys, chat IDs, or private health exports are committed
- [ ] New logs/diagnostics redact configured secrets
- [ ] Unit tests avoid live provider/network calls unless explicitly marked and opt-in

## Health safety

- [ ] Changes summarize patterns without diagnosing or prescribing
- [ ] Symptom/medication behavior is factual and cautious
- [ ] User-facing copy avoids fake precision and unsafe medical advice

## User path checked

Describe the CLI, Telegram, import, scheduler, or deployment path exercised.
