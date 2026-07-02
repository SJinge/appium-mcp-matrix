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

def test_parse_bitable_record():
    record = {
        "record_id": "rec001",
        "fields": {
            "用例编号": 1,
            "用例名称": [{"text": "测试登录", "type": "text"}],
            "测试步骤": [{"text": "1. 点击登录按钮\n2. 输入手机号", "type": "text"}],
            "预期结果": [{"text": "进入首页", "type": "text"}],
            "验证点":   [{"text": "显示用户头像", "type": "text"}],
            "预置条件": [{"text": "当前在登录页", "type": "text"}],
            # 真实 Bitable 列名 + 选项格式「名称：UDID」，_extract_udid 取冒号后 UDID
            "android执行设备": [{"text": "华为nova12pro：26KUT24202013751", "type": "text"}],
            "ios执行设备":    [{"text": "iphone12:00008101-001E28D436E0001E", "type": "text"}],
            "是否执行自动化": True,
        }
    }
    entry = orchestrate.parse_record(record)
    assert entry["record_id"] == "rec001"
    assert entry["name"] == "1 测试登录"
    assert any(s["type"] == "PRECOND" for s in entry["steps"])
    assert any(s["type"] == "ACTION"  for s in entry["steps"])
    assert any(s["type"] == "ASSERT"  for s in entry["steps"])
    assert entry["android_device"] == "26KUT24202013751"
    assert entry["ios_device"] == "00008101-001E28D436E0001E"

def test_group_by_device():
    entries = [
        {"record_id": "r1", "android_device": "a1", "ios_device": "i1",
         "name": "case1", "steps": []},
        {"record_id": "r2", "android_device": "a2", "ios_device": "",
         "name": "case2", "steps": []},
    ]
    groups = orchestrate.group_by_device(entries)
    assert "a1" in groups
    assert groups["a1"]["platform"] == "Android"
    assert "i1" in groups
    assert groups["i1"]["platform"] == "iOS"
    assert "a2" in groups
    assert "" not in groups  # empty device not grouped

import tempfile
import json as _json

def test_collect_results_reads_json(tmp_path):
    udid = "test_device"
    result_file = tmp_path / f"result_{udid}.json"
    cases = [{"name": "case1", "platform": "Android", "device": udid,
               "module": "首页", "passed": True, "duration": 30, "steps": []}]
    result_file.write_text(_json.dumps(cases))

    results = orchestrate.collect_results(
        {udid: None},
        result_dir=str(tmp_path),
        timeout=5
    )
    assert udid in results
    assert results[udid][0]["passed"] is True

def test_collect_results_timeout_marks_failure(tmp_path):
    results = orchestrate.collect_results(
        {"missing_device": None},
        result_dir=str(tmp_path),
        timeout=1
    )
    assert results["missing_device"] == "timeout"


def test_build_prompt_ios_injects_wda_url():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "i1", "iOS", entries, wda_port=8100)
    assert "webDriverAgentUrl" in prompt
    assert "http://127.0.0.1:8100" in prompt


def test_build_prompt_android_no_wda_url():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "webDriverAgentUrl" not in prompt
