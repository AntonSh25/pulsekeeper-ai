# PulseKeeper LLM access

PulseKeeper talks to language models through an OpenAI-compatible `base_url` only. The core application does not implement OAuth or provider-specific SDK clients.

Secrets belong in `.env` or the process environment, not in `config.toml`. Do not set `llm.api_key` directly except in disposable local experiments; prefer `llm.api_key_env` so secrets stay out of configuration files, logs, and reviews. Unit tests must use mocked config/env values and must not call live LLMs.

## Configuration

Example `config.toml`:

```toml
[llm]
auth_mode = "api_key"          # "api_key" or "subscription"
base_url = "https://llm-provider.example/v1"
model = "provider-model-name"  # choose a model supported by the endpoint
api_key_env = "LLM_API_KEY"    # api_key mode only
timeout = 60
max_tool_iterations = 4
```

Example `.env`:

```dotenv
LLM_API_KEY=provider-secret-value
```

`api_key_env` names the environment variable to read. Values from the process environment override values from `.env`, and loading config does not mutate the process environment. If `env_path` is not supplied, PulseKeeper automatically reads a `.env` file beside `config.toml` when one exists.

## Mode A: subscription via Hermes proxy

Use Hermes as a sidecar that exposes an OAuth/subscription-backed OpenAI-compatible local endpoint.

Discovered with Hermes v0.14.0:

- `hermes proxy --help` provides subcommands: `start`, `status`, `providers`.
- `hermes proxy start [--provider PROVIDER] [--host HOST] [--port PORT]`
- Defaults: provider `nous`, host `127.0.0.1`, port `8645`.
- Available providers on this machine: `nous` (Nous Portal), `xai` (xAI Grok OAuth).

Start the proxy separately, for example:

```bash
hermes proxy start --provider nous --host 127.0.0.1 --port 8645
```

Then configure PulseKeeper:

```toml
[llm]
auth_mode = "subscription"
base_url = "http://127.0.0.1:8645/v1"
model = "model-name-from-hermes-provider"
timeout = 60
max_tool_iterations = 4
```

If `base_url` is omitted in subscription mode, PulseKeeper defaults to `http://127.0.0.1:8645/v1`. The `/v1` suffix is intentional: pydantic-ai's OpenAI-compatible provider expects an OpenAI API root URL. No real API key is required by PulseKeeper in subscription mode; authentication is handled by the proxy process. PulseKeeper passes a fixed non-secret bearer placeholder to the OpenAI-compatible client to prevent accidental fallback to `OPENAI_API_KEY` from the process environment.

Model names depend on the selected Hermes provider and account. Check the proxy/provider documentation and set `llm.model` explicitly.

## Mode B: API key OpenAI-compatible provider

Use this for direct OpenAI-compatible providers or for a local compatibility proxy such as LiteLLM:

```toml
[llm]
auth_mode = "api_key"
base_url = "https://llm-provider.example/v1"
model = "provider-model-name"
api_key_env = "LLM_API_KEY"
```

PulseKeeper passes the resolved key to pydantic-ai's OpenAI provider. Missing or empty credentials raise a clear configuration error. Secret values are redacted from config representations and redaction helpers.

## Fallback

If `hermes proxy` is unavailable, changes behavior, or the subscription provider is not logged in, switch to `auth_mode = "api_key"` and point `base_url` at an OpenAI-compatible provider endpoint. The PulseKeeper core code remains unchanged because both modes use the same OpenAI-compatible interface.
