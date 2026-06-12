# Repository Guidelines

## Development style

Use strict TDD for production code:

1. Write a failing test first.
2. Run the specific test and verify it fails for the expected reason.
3. Implement the smallest code that passes.
4. Run the specific test and full suite.
5. Refactor only while tests stay green.

## Product guardrails

- Telegram-first capture UX.
- BYOK by default: users provide their own LLM key.
- Privacy-first and self-host friendly.
- Health advice should be careful: summarize patterns, do not diagnose.
- Keep the MVP boring and useful before adding integrations.
