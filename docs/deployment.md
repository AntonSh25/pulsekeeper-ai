# Deployment

PulseKeeper is self-host friendly: keep configuration in `config.toml`, keep secrets in `.env`, and persist the local SQLite database on a Docker volume.

## Docker Compose quickstart

1. Copy the examples:

   ```bash
   cp config.toml.example config.toml
   cp .env.example .env
   ```

2. Edit `.env` locally and fill `TELEGRAM_BOT_TOKEN` plus your BYOK LLM key such as `OPENAI_API_KEY`. Do not commit real secrets.

3. If needed, edit `config.toml` so `[llm].base_url`, `[llm].model`, and `[llm].api_key_env` match your provider. Keep inline `api_key` fields out of `config.toml`.

4. Start the bot from the repository root:

   ```bash
   docker compose -f docker-compose.example.yml up --build
   ```

The example runs `pulsekeeper telegram-run --config /config/config.toml` and stores runtime data in the named Docker volume `pulsekeeper-data`, mounted at `/data` in the container. This keeps `state.db`, media, exports, and logs outside the image.

## Doctor checks

Before enabling long-running polling, run the same diagnostics manually:

```bash
docker compose -f docker-compose.example.yml run --rm pulsekeeper-ai doctor --config /config/config.toml
```

`pulsekeeper doctor` verifies storage writability, DB migrations, Telegram token presence when Telegram is enabled, provider configuration, optional provider reachability, and unsafe inline-secret patterns. Output is redacted.

## Persistent data

The Compose file defines:

```yaml
volumes:
  pulsekeeper-data:
```

Back up this volume if you care about the local health memory. To inspect its location or export it, use Docker's volume tooling rather than copying secrets into the repository.
