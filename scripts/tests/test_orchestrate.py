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


class _FakeProc:
    """poll() 依次返回 poll_seq 的值(最后一个值粘住);None=存活,int=已退出。"""
    def __init__(self, poll_seq, returncode=0):
        self._seq = list(poll_seq)
        self.returncode = returncode
    def poll(self):
        v = self._seq[0] if len(self._seq) == 1 else self._seq.pop(0)
        return v
    def kill(self):
        pass


def test_collect_results_alive_empty_not_done(tmp_path):
    """回归 bug：进程仍存活时,即便结果文件是空 [] 也不能提前判完成。"""
    udid = "dev_alive"
    (tmp_path / f"result_{udid}.json").write_text("[]")
    proc = _FakeProc([None])  # 永远存活
    results = orchestrate.collect_results(
        {udid: proc}, result_dir=str(tmp_path), timeout=1, poll_interval=0.02)
    # 存活+空文件 → 不判 done/0，最终因 proc 未退出走超时
    assert results[udid] == "timeout"


def test_collect_results_reads_only_after_exit(tmp_path):
    """进程退出后才读取最终结果文件。"""
    udid = "dev_exit"
    cases = [{"name": "c1", "platform": "Android", "passed": True}]
    (tmp_path / f"result_{udid}.json").write_text(_json.dumps(cases))
    proc = _FakeProc([0])  # 已退出
    results = orchestrate.collect_results(
        {udid: proc}, result_dir=str(tmp_path), timeout=1, poll_interval=0.02)
    assert results[udid][0]["passed"] is True


def test_collect_results_exit_no_file_is_failed(tmp_path):
    """进程退出却没写结果文件 → 判失败(非提前完成)。"""
    udid = "dev_crash"
    proc = _FakeProc([1], returncode=1)
    results = orchestrate.collect_results(
        {udid: proc}, result_dir=str(tmp_path), timeout=1, poll_interval=0.02)
    assert results[udid] == "failed"


@pytest.fixture(autouse=True)
def _reset_inflight():
    orchestrate._INFLIGHT = {}
    orchestrate._FINALIZED = False
    yield
    orchestrate._INFLIGHT = {}
    orchestrate._FINALIZED = False


def _seed_inflight(tmp_path, device_totals):
    orchestrate._INFLIGHT = {
        "run_id": "r_test", "app_id": "gaotu", "version": "9.9.9",
        "start_time": orchestrate.time.time() - 5, "start_time_str": "00:00:00",
        "device_totals": device_totals, "result_dir": str(tmp_path),
    }
    orchestrate._FINALIZED = False


def test_finalize_idempotent(tmp_path):
    _seed_inflight(tmp_path, {"a1": {"total": 3, "platform": "Android"}})
    with patch("orchestrate.generate_reports") as gr, \
         patch("orchestrate.run_status") as rs:
        assert orchestrate.finalize(results={"a1": []}) is True
        assert orchestrate.finalize(results={"a1": []}) is False  # 第二次幂等空转
        assert gr.call_count == 1
        assert rs.finish.call_count == 1


def test_finalize_interrupt_reads_partial_from_disk(tmp_path):
    # a1 写了 2 条结果，b1(计划 5 条)没写 → 部分结果场景
    (tmp_path / "result_a1.json").write_text(_json.dumps(
        [{"platform": "Android", "passed": True},
         {"platform": "Android", "passed": False}]))
    _seed_inflight(tmp_path, {"a1": {"total": 4, "platform": "Android"},
                              "b1": {"total": 5, "platform": "Android"}})
    with patch("orchestrate.generate_reports") as gr, \
         patch("orchestrate.run_status") as rs:
        orchestrate.finalize(reason="⚠️ 中断")
        # 从磁盘读到 a1 的 2 条；b1 无文件
        args, kwargs = gr.call_args
        results = args[2]
        assert len(results["a1"]) == 2
        assert kwargs["interrupted"] is True
        assert kwargs["device_totals"]["b1"]["total"] == 5
        # 中断态 finish
        assert rs.finish.call_args[0][1] == "interrupted"


def test_generate_reports_notifies_unexecuted_and_interrupt_prefix():
    results = {"a1": [{"platform": "Android", "passed": True},
                      {"platform": "Android", "passed": False}]}
    device_totals = {"a1": {"total": 10, "platform": "Android"}}
    with patch("orchestrate._notify") as notify, \
         patch("orchestrate.write_results_to_table"), \
         patch("orchestrate.subprocess.run") as sr:
        sr.return_value.stdout = ""
        orchestrate.generate_reports("gaotu", "9.9.9", results, 120,
                                     start_time_str="00:00:00",
                                     device_totals=device_totals, interrupted=True)
        body = notify.call_args[0][2]
        assert "⚠️" in body            # 中断前缀
        assert "8 未执行" in body       # 10 计划 - 2 完成
        assert "1/10 通过" in body      # passed/planned


def test_generate_reports_zero_completion_still_notifies():
    """一条都没跑完(设备全崩)也要发群通知。"""
    with patch("orchestrate._notify") as notify, \
         patch("orchestrate.write_results_to_table"), \
         patch("orchestrate.subprocess.run") as sr:
        sr.return_value.stdout = ""
        orchestrate.generate_reports("gaotu", "9.9.9", {}, 30,
                                     device_totals={"a1": {"total": 7, "platform": "Android"}},
                                     interrupted=True)
        assert notify.called
        body = notify.call_args[0][2]
        assert "7 未执行" in body


def test_load_devices_parses_ios_wda(tmp_path):
    cfg = tmp_path / "devices.yaml"
    cfg.write_text("""
default:
  android: []
  ios:
    - udid: "i1"
      name: "iphone"
      wda:
        team: "TEAMX"
        bundle_id: "com.x.WDA"
        port: 8101
""")
    result = orchestrate.load_devices("gaotu", config_path=str(cfg))
    assert result["ios"][0]["wda"] == {"team": "TEAMX",
                                        "bundle_id": "com.x.WDA", "port": 8101}
