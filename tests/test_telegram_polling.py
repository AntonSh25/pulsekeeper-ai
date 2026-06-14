import asyncio

from pulsekeeper.agent_runtime import MessageContext, ToolCall
from pulsekeeper.telegram_polling import TelegramBotApiClient, poll_once, run_polling_loop


class FakeHttpClient:
    def __init__(self):
        self.calls = []
        self.responses = []

    def get_json(self, url, params):
        self.calls.append((url, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post_json(self, url, payload):
        self.calls.append((url, payload))
        return {"ok": True, "result": True}


class FakeModelRuntime:
    def complete_with_tools(self, message: str, context: MessageContext) -> list[ToolCall]:
        return [
            ToolCall(
                name="log_health_entry",
                arguments={"kind": "weight", "note": message, "value": 84.2, "unit": "kg"},
            )
        ]


class FakeGatewayStateStore:
    def __init__(self, offset=None):
        self.offset = offset
        self.saved_offsets = []

    async def get_telegram_offset(self, bot_profile):
        assert bot_profile == "default"
        return self.offset

    async def set_telegram_offset(self, bot_profile, offset):
        assert bot_profile == "default"
        self.saved_offsets.append(offset)
        self.offset = offset


def test_bot_api_client_get_updates_uses_token_and_offset():
    http = FakeHttpClient()
    http.responses.append({"ok": True, "result": [{"update_id": 42}]})
    client = TelegramBotApiClient(token="secret-token", http_client=http)

    updates = client.get_updates(offset=41, timeout=0)

    assert updates == [{"update_id": 42}]
    assert http.calls == [
        (
            "https://api.telegram.org/botsecret-token/getUpdates",
            {"timeout": 0, "offset": 41},
        )
    ]


def test_bot_api_client_send_message_posts_chat_id_and_text():
    http = FakeHttpClient()
    client = TelegramBotApiClient(token="secret-token", http_client=http)

    client.send_message(chat_id=555, text="Записал: weight — вес 84.2 кг")

    assert http.calls == [
        (
            "https://api.telegram.org/botsecret-token/sendMessage",
            {"chat_id": 555, "text": "Записал: weight — вес 84.2 кг"},
        )
    ]


def test_poll_once_handles_updates_sends_replies_and_returns_next_offset(tmp_path):
    http = FakeHttpClient()
    http.responses.append(
        {
            "ok": True,
            "result": [
                {
                    "update_id": 42,
                    "message": {
                        "chat": {"id": 555},
                        "from": {"id": 111},
                        "text": "вес 84.2 кг",
                    },
                }
            ],
        }
    )
    client = TelegramBotApiClient(token="secret-token", http_client=http)

    next_offset = poll_once(
        client,
        storage_dir=tmp_path,
        offset=41,
        model_runtime=FakeModelRuntime(),
    )

    assert next_offset == 43
    assert http.calls[-1] == (
        "https://api.telegram.org/botsecret-token/sendMessage",
        {"chat_id": 555, "text": "Записал: weight — вес 84.2 кг"},
    )


def test_poll_once_without_model_does_not_parse_user_text(tmp_path):
    http = FakeHttpClient()
    http.responses.append(
        {
            "ok": True,
            "result": [
                {
                    "update_id": 42,
                    "message": {
                        "chat": {"id": 555},
                        "from": {"id": 111},
                        "text": "вес 84.2 кг",
                    },
                }
            ],
        }
    )
    client = TelegramBotApiClient(token="secret-token", http_client=http)

    next_offset = poll_once(client, storage_dir=tmp_path, offset=41)

    assert next_offset == 43
    assert "Нужен BYOK LLM provider" in http.calls[-1][1]["text"]


def test_poll_once_returns_same_offset_when_no_updates(tmp_path):
    http = FakeHttpClient()
    http.responses.append({"ok": True, "result": []})
    client = TelegramBotApiClient(token="secret-token", http_client=http)

    assert poll_once(client, storage_dir=tmp_path, offset=10) == 10


def test_polling_loop_loads_and_persists_offsets_between_iterations(tmp_path):
    http = FakeHttpClient()
    http.responses.append(
        {
            "ok": True,
            "result": [
                {
                    "update_id": 42,
                    "message": {
                        "chat": {"id": 555},
                        "from": {"id": 111},
                        "text": "вес 84.2 кг",
                    },
                }
            ],
        }
    )
    http.responses.append({"ok": True, "result": []})
    state = FakeGatewayStateStore(offset=41)
    client = TelegramBotApiClient(token="secret-token", http_client=http)

    asyncio.run(
        run_polling_loop(
            client,
            storage_dir=tmp_path,
            gateway_state=state,
            bot_profile="default",
            timeout=0,
            max_iterations=2,
            model_runtime=FakeModelRuntime(),
        )
    )

    assert http.calls[0] == (
        "https://api.telegram.org/botsecret-token/getUpdates",
        {"timeout": 0, "offset": 41},
    )
    assert http.calls[2] == (
        "https://api.telegram.org/botsecret-token/getUpdates",
        {"timeout": 0, "offset": 43},
    )
    assert state.saved_offsets == [43]


def test_polling_loop_leaves_offset_unchanged_when_no_updates(tmp_path):
    http = FakeHttpClient()
    http.responses.append({"ok": True, "result": []})
    state = FakeGatewayStateStore(offset=10)
    client = TelegramBotApiClient(token="secret-token", http_client=http)

    asyncio.run(
        run_polling_loop(
            client,
            storage_dir=tmp_path,
            gateway_state=state,
            bot_profile="default",
            timeout=0,
            max_iterations=1,
        )
    )

    assert state.saved_offsets == []


def test_polling_loop_backs_off_and_recovers_after_transient_network_error(tmp_path):
    http = FakeHttpClient()
    http.responses.append(RuntimeError("temporary network failure"))
    http.responses.append(
        {
            "ok": True,
            "result": [
                {
                    "update_id": 42,
                    "message": {
                        "chat": {"id": 555},
                        "from": {"id": 111},
                        "text": "вес 84.2 кг",
                    },
                }
            ],
        }
    )
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    state = FakeGatewayStateStore(offset=41)
    client = TelegramBotApiClient(token="secret-token", http_client=http)

    asyncio.run(
        run_polling_loop(
            client,
            storage_dir=tmp_path,
            gateway_state=state,
            bot_profile="default",
            timeout=0,
            max_iterations=2,
            model_runtime=FakeModelRuntime(),
            error_backoff_seconds=3.5,
            sleep=fake_sleep,
        )
    )

    assert sleeps == [3.5]
    assert state.saved_offsets == [43]
    assert http.calls[0] == (
        "https://api.telegram.org/botsecret-token/getUpdates",
        {"timeout": 0, "offset": 41},
    )
    assert http.calls[1] == (
        "https://api.telegram.org/botsecret-token/getUpdates",
        {"timeout": 0, "offset": 41},
    )
