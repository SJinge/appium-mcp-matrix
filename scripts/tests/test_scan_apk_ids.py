import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scan_apk_ids as s


def test_parse_ids_from_dump_extracts_id_type_only():
    dump = """
    resource 0x7f010000 anim/abc_fade_in
    resource 0x7f0a0001 id/account_sign_btn
    resource 0x7f0a0002 id/tab_title
    resource 0x7f0b0000 layout/activity_main
    resource 0x7f0a0001 id/account_sign_btn
    """
    assert s.parse_ids_from_dump(dump) == ["account_sign_btn", "tab_title"]


def test_parse_ids_handles_dotted_names():
    dump = "    resource 0x7f0a0009 id/some.lib_view\n"
    assert s.parse_ids_from_dump(dump) == ["some.lib_view"]


def test_is_noise():
    assert s.is_noise("abc_action_bar") is True
    assert s.is_noise("mtrl_card") is True
    assert s.is_noise("account_sign_btn") is False
    assert s.is_noise("tab_title") is False


def test_version_key_orders_correctly():
    assert s.version_key("5.91.80") < s.version_key("5.91.81")
    assert s.version_key("5.91.9") < s.version_key("5.91.80")
    assert s.version_key("5.9.0") < s.version_key("5.91.0")


def test_pick_previous_version():
    versions = ["5.91.80", "5.91.51", "5.90.0"]
    assert s.pick_previous_version(versions, "5.91.80") == "5.91.51"


def test_pick_previous_version_none_when_lowest():
    assert s.pick_previous_version(["5.91.80"], "5.91.80") is None
    assert s.pick_previous_version(["5.92.0"], "5.91.80") is None


def test_diff_ids():
    old = ["a", "b", "c"]
    new = ["b", "c", "d", "e"]
    assert s.diff_ids(old, new) == {"added": ["d", "e"], "removed": ["a"]}


def test_diff_ids_no_change():
    assert s.diff_ids(["a", "b"], ["b", "a"]) == {"added": [], "removed": []}
