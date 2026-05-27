import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import patch
import orchestrate

def test_load_devices_returns_android_and_ios(tmp_path):
    cfg = tmp_path / "devices.yaml"
    cfg.write_text("""
default:
  android:
    - udid: "a1"
      name: "dev1"
    - udid: "a2"
      name: "dev2"
  ios:
    - udid: "i1"
      name: "idev1"
""")
    result = orchestrate.load_devices("gaotu", config_path=str(cfg))
    assert result["android"] == [{"udid": "a1", "name": "dev1"},
                                   {"udid": "a2", "name": "dev2"}]
    assert result["ios"] == [{"udid": "i1", "name": "idev1"}]

@patch("orchestrate.subprocess.run")
def test_extract_version_android(mock_run):
    mock_run.return_value.stdout = "versionName=5.91.51\n"
    version = orchestrate.extract_version_android("com.gaotu100.superclass")
    assert version == "5.91.51"

@patch("orchestrate.subprocess.run")
def test_install_android_calls_adb(mock_run):
    mock_run.return_value.returncode = 0
    orchestrate.install_android("/tmp/app.apk", "a1")
    mock_run.assert_called()
    args = mock_run.call_args[0][0]
    assert "adb" in args[0]
    assert "a1" in args
