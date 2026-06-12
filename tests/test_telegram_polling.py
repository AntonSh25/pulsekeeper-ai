from pulsekeeper.telegram_polling import TelegramBotApiClient, poll_once


class FakeHttpClient:
    def __init__(self):
        self.calls = []
        self.responses = []

    def get_json(self, url, params):
        self.calls.append((url, params))
        return self.responses.pop(0)

    def post_json(self, url, payload):
        self.calls.append((url, payload))
        return {"ok": True, "result": True}


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

    next_offset = poll_once(client, storage_dir=tmp_path, offset=41)

    assert next_offset == 43
    assert http.calls[-1] == (
        "https://api.telegram.org/botsecret-token/sendMessage",
        {"chat_id": 555, "text": "Записал: weight — вес 84.2 кг"},
    )


def test_poll_once_returns_same_offset_when_no_updates(tmp_path):
    http = FakeHttpClient()
    http.responses.append({"ok": True, "result": []})
    client = TelegramBotApiClient(token="secret-token", http_client=http)

    assert poll_once(client, storage_dir=tmp_path, offset=10) == 10
