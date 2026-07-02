import sys, os, io, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import patch, MagicMock
import ios_wda


def _urlopen_ok():
    cm = MagicMock()
    resp = MagicMock()
    resp.status = 200
    cm.__enter__.return_value = resp
    return cm


def test_health_check_true_when_status_ok():
    with patch("ios_wda.urllib.request.urlopen", return_value=_urlopen_ok()):
        assert ios_wda.health_check(8100) is True


def test_health_check_false_on_error():
    with patch("ios_wda.urllib.request.urlopen", side_effect=OSError("refused")):
        assert ios_wda.health_check(8100) is False


def test_tunnel_ready_true_when_udid_present():
    payload = {"00008101-001E28D436E0001E": [{"tunnel-address": "fd00::1"}]}
    cm = MagicMock(); cm.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    with patch("ios_wda.urllib.request.urlopen", return_value=cm):
        assert ios_wda.tunnel_ready("00008101-001E28D436E0001E") is True


def test_tunnel_ready_false_when_absent():
    cm = MagicMock(); cm.__enter__.return_value = io.BytesIO(b'{}')
    with patch("ios_wda.urllib.request.urlopen", return_value=cm):
        assert ios_wda.tunnel_ready("nope") is False


def test_proxy_listening_uses_lsof():
    with patch("ios_wda.subprocess.run") as m:
        m.return_value.returncode = 0
        m.return_value.stdout = "12345\n"
        assert ios_wda.proxy_listening(8100) is True
        args = m.call_args[0][0]
        assert args[0] == "lsof"
        assert "-ti" in args


def test_wda_running_matches_udid():
    with patch("ios_wda.subprocess.run") as m:
        m.return_value.returncode = 0
        m.return_value.stdout = "999\n"
        assert ios_wda.wda_running("00008101-001E28D436E0001E") is True


def test_ensure_ready_returns_true_immediately_when_healthy():
    with patch("ios_wda.health_check", return_value=True):
        ok = ios_wda.ensure_wda_ready("udid", "TEAM", "bundle", 8100, timeout=5)
    assert ok is True


def test_ensure_ready_false_when_tunnel_missing():
    with patch("ios_wda.health_check", return_value=False), \
         patch("ios_wda.tunnel_ready", return_value=False):
        ok = ios_wda.ensure_wda_ready("udid", "TEAM", "bundle", 8100, timeout=5)
    assert ok is False


def test_ensure_ready_starts_procs_then_polls_healthy():
    health_seq = [False, True]
    with patch("ios_wda.health_check", side_effect=lambda p: health_seq.pop(0)), \
         patch("ios_wda.tunnel_ready", return_value=True), \
         patch("ios_wda.wda_running", return_value=False), \
         patch("ios_wda.proxy_listening", return_value=False), \
         patch("ios_wda.subprocess.Popen") as popen, \
         patch("ios_wda.time.sleep"):
        ok = ios_wda.ensure_wda_ready("udid", "TEAM", "bundle", 8100, timeout=30)
    assert ok is True
    assert popen.call_count == 2  # xcodebuild + proxy


def test_ensure_ready_times_out():
    with patch("ios_wda.health_check", return_value=False), \
         patch("ios_wda.tunnel_ready", return_value=True), \
         patch("ios_wda.wda_running", return_value=True), \
         patch("ios_wda.proxy_listening", return_value=True), \
         patch("ios_wda.subprocess.Popen"), \
         patch("ios_wda.time.sleep"), \
         patch("ios_wda.time.monotonic", side_effect=[0, 1, 200]):
        ok = ios_wda.ensure_wda_ready("udid", "TEAM", "bundle", 8100, timeout=180)
    assert ok is False
