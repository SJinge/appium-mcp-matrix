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

# ── receive_card：单端即返回（不再配对等待） ──────────────────────────────────

def test_receive_card_returns_single_platform():
    android_content = _make_card("gaotu", "android", "5.91.60", "https://cdn.example.com/a")
    result = receive_card(android_content)
    assert result == {
        "app_id": "gaotu", "platform": "android",
        "version": "5.91.60", "url": "https://cdn.example.com/a.apk"
    }

# ── parse_template（轻舟格式） ────────────────────────────────────────────────

def _make_template(app_product, version, url):
    return {
        "type": "template",
        "data": {"template_variable": {
            "appProduct": app_product, "appVersion": version, "downloadUrl": url
        }},
    }

def test_parse_template_android():
    data = _make_template("gaotu-android", "5.91.80", "https://x/app1-gaotu-release.apk")
    assert app_module.parse_template(data) == {
        "app_id": "gaotu", "platform": "android",
        "version": "5.91.80", "url": "https://x/app1-gaotu-release.apk"
    }

def test_parse_template_ios():
    data = _make_template("gaotu-ios", "5.91.80", "https://x/gaotu-release.ipa")
    assert app_module.parse_template(data)["platform"] == "ios"

def test_parse_template_unknown_app_returns_none():
    data = _make_template("unknown-android", "1.0", "https://x/a.apk")
    assert app_module.parse_template(data) is None

# ── Flask 路由 ────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
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
def test_card_android_alone_triggers(mock_trigger, client):
    android_content = _make_card("gaotu", "android", "5.91.60", "https://cdn.example.com/a")
    payload = {"event": {"message": {"message_type": "interactive",
                                      "content": android_content}}}
    client.post("/webhook/feishu", json=payload)
    mock_trigger.assert_called_once_with(
        "gaotu", "5.91.60", "android", "https://cdn.example.com/a.apk")

@patch("app._do_trigger")
def test_template_triggers_per_platform(mock_trigger, client):
    client.post("/webhook",
                json=_make_template("gaotu-android", "5.91.80", "https://x/a.apk"))
    client.post("/webhook",
                json=_make_template("gaotu-ios", "5.91.80", "https://x/b.ipa"))
    assert mock_trigger.call_count == 2
    mock_trigger.assert_any_call("gaotu", "5.91.80", "android", "https://x/a.apk")
    mock_trigger.assert_any_call("gaotu", "5.91.80", "ios", "https://x/b.ipa")

@patch("app.local_trigger")
@patch("app.is_running", return_value=False)
def test_text_message_triggers_both(mock_running, mock_trigger, client):
    mock_trigger.return_value = True
    payload = {"event": {"message": {
        "message_type": "text",
        "content": '{"text":"gaotu 5.91 android:https://a.apk ios:https://b.ipa"}'
    }}}
    client.post("/webhook/feishu", json=payload)
    assert mock_trigger.call_count == 2
    mock_trigger.assert_any_call("gaotu", "5.91", "android", "https://a.apk")
    mock_trigger.assert_any_call("gaotu", "5.91", "ios", "https://b.ipa")
