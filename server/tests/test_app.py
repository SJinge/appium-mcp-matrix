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
