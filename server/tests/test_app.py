import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import parse_message

def test_parse_valid_message():
    msg = "gaotu 5.91.51 android:https://example.com/a.apk ios:https://example.com/a.ipa"
    result = parse_message(msg)
    assert result == {
        "app_id": "gaotu",
        "version": "5.91.51",
        "apk_url": "https://example.com/a.apk",
        "ipa_url": "https://example.com/a.ipa",
    }

def test_parse_case_insensitive():
    msg = "GAOTU 5.91 android:https://a.apk ios:https://a.ipa"
    result = parse_message(msg)
    assert result["app_id"] == "gaotu"

def test_parse_invalid_returns_none():
    assert parse_message("hello world") is None
    assert parse_message("gaotu 5.91 android:https://a.apk") is None  # ios missing

def test_parse_all_app_ids():
    for app in ["tutu", "jingpin", "gongkao", "xinli", "ketang"]:
        msg = f"{app} 1.0.0 android:https://a.apk ios:https://b.ipa"
        assert parse_message(msg)["app_id"] == app

from unittest.mock import patch
from app import app as flask_app

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    return flask_app.test_client()

def test_url_verification(client):
    resp = client.post("/webhook/feishu",
        json={"type": "url_verification", "challenge": "abc123"},
        content_type="application/json")
    assert resp.status_code == 200
    assert resp.get_json()["challenge"] == "abc123"

def test_non_text_message_ignored(client):
    payload = {"event": {"message": {"message_type": "image"}, "sender": {}}}
    resp = client.post("/webhook/feishu", json=payload)
    assert resp.status_code == 200

def test_bot_message_ignored(client):
    payload = {"event": {
        "message": {"message_type": "text", "content": '{"text":"gaotu 1.0 android:https://a.apk ios:https://b.ipa"}'},
        "sender": {"sender_type": "app"}
    }}
    resp = client.post("/webhook/feishu", json=payload)
    assert resp.status_code == 200

@patch("app.ssh_trigger")
@patch("app.is_running", return_value=False)
def test_valid_message_triggers_ssh(mock_running, mock_ssh, client):
    mock_ssh.return_value = True
    payload = {"event": {
        "message": {"message_type": "text",
                    "content": '{"text":"gaotu 5.91 android:https://a.apk ios:https://b.ipa"}'},
        "sender": {"sender_type": "user"}
    }}
    resp = client.post("/webhook/feishu", json=payload)
    assert resp.status_code == 200
    mock_ssh.assert_called_once_with("gaotu", "5.91",
                                      "https://a.apk", "https://b.ipa")

@patch("app.ssh_trigger")
@patch("app.is_running", return_value=True)
def test_duplicate_trigger_rejected(mock_running, mock_ssh, client):
    payload = {"event": {
        "message": {"message_type": "text",
                    "content": '{"text":"gaotu 5.91 android:https://a.apk ios:https://b.ipa"}'},
        "sender": {"sender_type": "user"}
    }}
    client.post("/webhook/feishu", json=payload)
    mock_ssh.assert_not_called()
