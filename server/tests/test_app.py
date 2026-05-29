import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import patch
from app import parse_message, parse_card, receive_card, app as flask_app
import app as app_module

# ── parse_message（文本格式） ──────────────────────────────────────────────────

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
    assert parse_message(msg)["app_id"] == "gaotu"

def test_parse_invalid_returns_none():
    assert parse_message("hello world") is None
    assert parse_message("gaotu 5.91 android:https://a.apk") is None

def test_parse_all_app_ids():
    for app in ["tutu", "jingpin", "gongkao", "xinli", "ketang"]:
        msg = f"{app} 1.0.0 android:https://a.apk ios:https://b.ipa"
        assert parse_message(msg)["app_id"] == app

# ── parse_card（卡片格式） ────────────────────────────────────────────────────

def _make_card(app_id, platform, version, url):
    ext = ".apk" if platform == "android" else ".ipa"
    card = {
        "header": {"title": {"content": f"【{app_id}-{platform}】构建完成！"}},
        "body": {
            "elements": [
                {"tag": "div", "text": {"content": f"版本号\n{version}"}},
                {"tag": "action", "actions": [
                    {"tag": "button", "text": {"content": "下载链接"},
                     "url": f"{url}{ext}"}
                ]}
            ]
        }
    }
    import json
    return json.dumps(card)

def test_parse_card_android():
    content = _make_card("gaotu", "android", "5.91.60", "https://cdn.example.com/gaotu")
    result = parse_card(content)
    assert result == {
        "app_id": "gaotu", "platform": "android",
        "version": "5.91.60", "url": "https://cdn.example.com/gaotu.apk"
    }

def test_parse_card_ios():
    content = _make_card("gaotu", "ios", "5.91.60", "https://cdn.example.com/gaotu")
    result = parse_card(content)
    assert result["platform"] == "ios"
    assert result["url"].endswith(".ipa")

def test_parse_card_unknown_app_returns_none():
    import json
    card = {"header": {"title": {"content": "【unknown-android】构建完成！"}}}
    assert parse_card(json.dumps(card)) is None

def test_parse_card_no_title_returns_none():
    import json
    assert parse_card(json.dumps({"body": {}})) is None

# ── receive_card 配对逻辑 ─────────────────────────────────────────────────────

def test_receive_card_waits_for_both_platforms():
    # 重置状态
    app_module._pending_pairs.clear()

    android_content = _make_card("gaotu", "android", "5.91.60", "https://cdn.example.com/a")
    ios_content     = _make_card("gaotu", "ios",     "5.91.60", "https://cdn.example.com/b")

    assert receive_card(android_content) is None   # 只有 Android，还不触发
    result = receive_card(ios_content)             # iOS 到齐，触发
    assert result is not None
    app_id, version, apk_url, ipa_url = result
    assert app_id == "gaotu"
    assert version == "5.91.60"
    assert apk_url.endswith(".apk")
    assert ipa_url.endswith(".ipa")

def test_receive_card_clears_after_trigger():
    app_module._pending_pairs.clear()
    android_content = _make_card("gaotu", "android", "5.91.60", "https://cdn.example.com/a")
    ios_content     = _make_card("gaotu", "ios",     "5.91.60", "https://cdn.example.com/b")
    receive_card(android_content)
    receive_card(ios_content)
    assert "gaotu_5.91.60" not in app_module._pending_pairs

# ── Flask 路由 ────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    app_module._pending_pairs.clear()
    return flask_app.test_client()

def test_url_verification(client):
    resp = client.post("/webhook/feishu",
        json={"type": "url_verification", "challenge": "abc123"})
    assert resp.status_code == 200
    assert resp.get_json()["challenge"] == "abc123"

def test_non_text_non_card_ignored(client):
    payload = {"event": {"message": {"message_type": "image"}, "sender": {}}}
    resp = client.post("/webhook/feishu", json=payload)
    assert resp.status_code == 200

@patch("app._do_trigger")
def test_card_android_alone_no_trigger(mock_trigger, client):
    android_content = _make_card("gaotu", "android", "5.91.60", "https://cdn.example.com/a")
    payload = {"event": {"message": {"message_type": "interactive",
                                      "content": android_content}}}
    client.post("/webhook/feishu", json=payload)
    mock_trigger.assert_not_called()

@patch("app._do_trigger")
def test_card_both_platforms_trigger(mock_trigger, client):
    android_content = _make_card("gaotu", "android", "5.91.60", "https://cdn.example.com/a")
    ios_content     = _make_card("gaotu", "ios",     "5.91.60", "https://cdn.example.com/b")
    client.post("/webhook/feishu",
                json={"event": {"message": {"message_type": "interactive",
                                             "content": android_content}}})
    client.post("/webhook/feishu",
                json={"event": {"message": {"message_type": "interactive",
                                             "content": ios_content}}})
    mock_trigger.assert_called_once_with(
        "gaotu", "5.91.60",
        "https://cdn.example.com/a.apk",
        "https://cdn.example.com/b.ipa"
    )

@patch("app.ssh_trigger")
@patch("app.is_running", return_value=False)
def test_text_message_triggers_ssh(mock_running, mock_ssh, client):
    mock_ssh.return_value = True
    payload = {"event": {"message": {
        "message_type": "text",
        "content": '{"text":"gaotu 5.91 android:https://a.apk ios:https://b.ipa"}'
    }}}
    client.post("/webhook/feishu", json=payload)
    mock_ssh.assert_called_once_with("gaotu", "5.91", "https://a.apk", "https://b.ipa")
