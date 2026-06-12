from pulsekeeper.storage import JsonlHealthLog
from pulsekeeper.telegram_transport import TelegramOutboundMessage, handle_telegram_update


def test_telegram_update_routes_message_text_by_sender_id(tmp_path):
    storage_dir = tmp_path / "pulsekeeper"
    update = {
        "update_id": 1000,
        "message": {
            "message_id": 10,
            "chat": {"id": 555, "type": "private"},
            "from": {"id": 111, "is_bot": False, "first_name": "Anton"},
            "text": "вес 84.2 кг",
        },
    }

    outbound = handle_telegram_update(update, storage_dir=storage_dir)

    assert outbound == TelegramOutboundMessage(chat_id=555, text="Записал: weight — вес 84.2 кг")
    entries = JsonlHealthLog(storage_dir / "users" / "111" / "health.jsonl").read_all()
    assert entries[0].kind == "weight"


def test_telegram_update_returns_none_for_non_text_message(tmp_path):
    update = {
        "message": {
            "chat": {"id": 555, "type": "private"},
            "from": {"id": 111, "is_bot": False},
            "photo": [{"file_id": "abc"}],
        }
    }

    assert handle_telegram_update(update, storage_dir=tmp_path) is None


def test_telegram_update_returns_none_without_sender_or_chat(tmp_path):
    update = {"message": {"text": "вес 84.2 кг"}}

    assert handle_telegram_update(update, storage_dir=tmp_path) is None
