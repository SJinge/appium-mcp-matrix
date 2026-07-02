import sys, os, json, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import patch, MagicMock
import wda_proxy


def _fake_urlopen(payload):
    cm = MagicMock()
    cm.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return cm


def test_discover_tunnel_host_list_shape():
    payload = {"00008101-001E28D436E0001E": [{"tunnel-address": "fd00::1"}]}
    with patch("wda_proxy.urllib.request.urlopen", return_value=_fake_urlopen(payload)):
        host = wda_proxy.discover_tunnel_host("http://127.0.0.1:49151/",
                                              "00008101-001E28D436E0001E")
    assert host == "fd00::1"


def test_discover_tunnel_host_dashless_key():
    payload = {"00008101001E28D436E0001E": {"address": "fd00::2"}}
    with patch("wda_proxy.urllib.request.urlopen", return_value=_fake_urlopen(payload)):
        host = wda_proxy.discover_tunnel_host("http://127.0.0.1:49151/",
                                              "00008101-001E28D436E0001E")
    assert host == "fd00::2"


def test_discover_tunnel_host_missing_returns_none():
    with patch("wda_proxy.urllib.request.urlopen", return_value=_fake_urlopen({})):
        host = wda_proxy.discover_tunnel_host("http://127.0.0.1:49151/", "unknown-udid")
    assert host is None
