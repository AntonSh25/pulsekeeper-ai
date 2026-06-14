# Screenshots and GIFs

This page tracks demo artifacts for the public README. The current repository uses placeholder references until sanitized assets are captured from a local demo run.

## Planned assets

- `assets/demo-telegram-capture.gif` — Telegram-first capture flow showing a user logging weight/food/workout messages and receiving concise confirmations.
- `assets/demo-doctor.png` — `pulsekeeper doctor` output showing local storage, migrations, Telegram token, and BYOK provider checks with secrets redacted.

## Capture rules

- Do not use real health data, real chat IDs, real Telegram tokens, or real API keys.
- Use synthetic examples like `вес 84.2`, `завтрак омлет и кофе`, and placeholder tokens.
- Re-run `uv run pulsekeeper doctor` before recording so the demo reflects the documented setup path.
- Keep screenshots/GIFs small enough for GitHub rendering and store them under `docs/assets/`.
