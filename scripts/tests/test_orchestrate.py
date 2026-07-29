import pytest, sys, os, glob, json as _json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import patch
import orchestrate

# 捕获真实实现，供 prune 专测在隔离前缀上验证；其余测试一律 no-op。
_REAL_PRUNE = orchestrate.prune_old_packages


@pytest.fixture(autouse=True)
def _guard_real_tmp_prune(monkeypatch):
    """任何测试都不得对真实 /tmp 执行生产 app 的 prune。

    历史事故:test_run_* 端到端测试调 _run(app_id="gaotu") → 内部 prune_old_packages
    打真实 /tmp,把线上 run 正在用的 gaotu_5.91.92.ipa 删掉,导致重装类用例找不到包。
    全局置为 no-op;prune 专测用 _REAL_PRUNE 在 prunetest* 隔离前缀上验证真实逻辑。
    """
    monkeypatch.setattr(orchestrate, "prune_old_packages", lambda *a, **k: None)


def _write_jsonl(path, cases):
    """把 cases 以 JSONL(一行一条)写入 path，模拟 subagent 的增量落盘。"""
    path.write_text("".join(_json.dumps(c, ensure_ascii=False) + "\n" for c in cases))

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
    assert mock_run.call_count == 2
    uninstall_args = mock_run.call_args_list[0][0][0]
    install_args = mock_run.call_args_list[1][0][0]
    assert uninstall_args == ["adb", "-s", "a1", "uninstall", "com.gaotu100.superclass"]
    assert install_args == ["adb", "-s", "a1", "install", "-r", "/tmp/app.apk"]


@patch("orchestrate.subprocess.run")
def test_install_ios_uninstalls_before_install(mock_run):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "Complete"
    assert orchestrate.install_ios("/tmp/app.ipa", "i1") is True
    assert mock_run.call_count == 2
    uninstall_args = mock_run.call_args_list[0][0][0]
    install_args = mock_run.call_args_list[1][0][0]
    assert uninstall_args == [sys.executable, "-m", "tidevice", "-u", "i1",
                              "uninstall", "com.gaotu100.superclass"]
    assert install_args == [sys.executable, "-m", "tidevice", "-u", "i1",
                            "install", "/tmp/app.ipa"]


@patch("orchestrate.subprocess.run")
def test_download_file_accepts_nonzero_curl_when_file_is_valid(mock_run, tmp_path):
    dest = tmp_path / "app.apk"
    dest.write_bytes(b"x" * 1_200_000)
    mock_run.return_value.returncode = 56
    mock_run.return_value.stderr = b"curl: (56) Failure when receiving data from the peer"
    mock_run.return_value.stdout = b""

    assert orchestrate.download_file("https://example.com/app.apk", str(dest)) is True


@patch("orchestrate.subprocess.run")
def test_download_file_rejects_small_file_even_when_present(mock_run, tmp_path):
    dest = tmp_path / "app.apk"
    dest.write_bytes(b"x" * 512)
    mock_run.return_value.returncode = 0
    mock_run.return_value.stderr = b""
    mock_run.return_value.stdout = b""

    assert orchestrate.download_file("https://example.com/app.apk", str(dest)) is False


def test_notify_can_be_silenced_by_env(monkeypatch):
    monkeypatch.setenv("ORCH_NO_NOTIFY", "1")
    with patch("orchestrate._feishu_post") as post:
        orchestrate._notify("gaotu", "5.91.80", "hello")
    post.assert_not_called()


def test_parse_bitable_record():
    record = {
        "record_id": "rec001",
        "fields": {
            "编号": "A-02",
            "用例编号": 1,
            "用例名称": [{"text": "测试登录", "type": "text"}],
            "所属页面": [{"text": "登录页", "type": "text"}],
            "状态组": [{"text": "login_flow", "type": "text"}],
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
    assert entry["order"] == "A-02"
    assert entry["module"] == "登录页"
    assert entry["page"] == "登录页"
    assert entry["state_group"] == "login_flow"
    assert any(s["type"] == "PRECOND" for s in entry["steps"])
    assert any(s["type"] == "ACTION"  for s in entry["steps"])
    assert any(s["type"] == "ASSERT"  for s in entry["steps"])
    assert entry["android_device"] == "26KUT24202013751"
    assert entry["ios_device"] == "00008101-001E28D436E0001E"


def test_parse_bitable_record_falls_back_to_legacy_module():
    record = {
        "record_id": "rec002",
        "fields": {
            "编号": "2",
            "用例名称": [{"text": "旧结构用例", "type": "text"}],
            "模块": [{"text": "首页", "type": "text"}],
        }
    }
    entry = orchestrate.parse_record(record)
    assert entry["module"] == "首页"
    assert entry["page"] == ""
    assert entry["state_group"] == ""


def test_case_order_key_sorts_naturally():
    values = ["A-10", "A-2", "B-1", "", "A-02"]
    sorted_values = sorted(values, key=orchestrate._case_order_key)
    assert sorted_values == ["A-2", "A-02", "A-10", "B-1", ""]


def test_fetch_cases_sorts_by_order_stably(monkeypatch):
    payload = {
        "data": {
            "items": [
                {"record_id": "r3", "fields": {"编号": "A-10", "用例名称": "c3"}},
                {"record_id": "r1", "fields": {"编号": "A-2", "用例名称": "c1"}},
                {"record_id": "r2", "fields": {"编号": "A-02", "用例名称": "c2"}},
            ]
        }
    }

    class _Resp:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return _json.dumps(payload, ensure_ascii=False).encode()

    monkeypatch.setattr(orchestrate, "_get_token", lambda: "token")
    monkeypatch.setattr(orchestrate.urllib.request, "urlopen", lambda req: _Resp())

    entries = orchestrate.fetch_cases("gaotu")
    assert [e["record_id"] for e in entries] == ["r1", "r2", "r3"]

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


def test_group_by_device_keeps_multiple_entries_per_same_device():
    entries = [
        {"record_id": "r1", "android_device": "a1", "ios_device": "", "name": "case1", "steps": []},
        {"record_id": "r2", "android_device": "a1", "ios_device": "", "name": "case2", "steps": []},
    ]

    groups = orchestrate.group_by_device(entries)

    assert [entry["record_id"] for entry in groups["a1"]["entries"]] == ["r1", "r2"]


def test_resolve_agent_runner_defaults_to_codex(monkeypatch):
    monkeypatch.delenv("ORCH_AGENT_CLI", raising=False)
    assert orchestrate.resolve_agent_runner() == "codex"


def test_resolve_agent_runner_accepts_claude(monkeypatch):
    monkeypatch.setenv("ORCH_AGENT_CLI", "claude")
    assert orchestrate.resolve_agent_runner() == "claude"


def test_resolve_agent_runner_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("ORCH_AGENT_CLI", "unknown")
    with pytest.raises(ValueError, match="ORCH_AGENT_CLI"):
        orchestrate.resolve_agent_runner()


def test_load_runner_secrets_injects_into_environ(tmp_path):
    import orch_config
    secrets = tmp_path / "runner.env"
    secrets.write_text(
        "# headless claude 凭据\n"
        'ANTHROPIC_API_KEY="sk-test-123"\n'
        "\n"
        "FOO=bar\n"
    )
    env = {"ORCH_SECRETS_FILE": str(secrets)}
    loaded = orch_config.load_runner_secrets(environ=env)
    assert loaded == ["ANTHROPIC_API_KEY", "FOO"]
    assert env["ANTHROPIC_API_KEY"] == "sk-test-123"  # 引号被剥掉
    assert env["FOO"] == "bar"


def test_load_runner_secrets_missing_file_is_noop(tmp_path):
    import orch_config
    env = {"ORCH_SECRETS_FILE": str(tmp_path / "nope.env")}
    assert orch_config.load_runner_secrets(environ=env) == []


def test_load_runner_secrets_ignores_comments_and_blank_lines(tmp_path):
    import orch_config
    secrets = tmp_path / "runner.env"
    secrets.write_text("# just a comment\n\n   \nKEY=value\n")
    env = {"ORCH_SECRETS_FILE": str(secrets)}
    assert orch_config.load_runner_secrets(environ=env) == ["KEY"]
    assert env["KEY"] == "value"


def test_agent_failure_503_no_available_accounts_is_retryable():
    tail = "API Error: 503 No available accounts: this group only allows Claude Code clients"
    assert orchestrate._agent_failure_is_retryable_503(tail) is True


def test_agent_failure_503_overloaded_is_retryable():
    assert orchestrate._agent_failure_is_retryable_503("Error 503: Overloaded") is True


def test_agent_failure_429_quota_is_not_retryable():
    assert orchestrate._agent_failure_is_retryable_503("429 api key 日限额已用完") is False
    assert orchestrate._agent_failure_is_retryable_503("Too Many Requests") is False


def test_agent_failure_empty_or_generic_is_not_retryable():
    assert orchestrate._agent_failure_is_retryable_503("") is False
    assert orchestrate._agent_failure_is_retryable_503(None) is False
    assert orchestrate._agent_failure_is_retryable_503("timeout killing device") is False


def test_execute_case_via_agent_retries_on_503_then_succeeds(monkeypatch):
    entry = {"record_id": "rec1", "name": "用例A", "module": "m"}
    calls = {"n": 0}

    monkeypatch.setattr(orchestrate, "launch_agent_batch", lambda *a, **k: object())
    monkeypatch.setattr(orchestrate, "_batch_result_dir", lambda *a, **k: "/tmp/x")
    monkeypatch.setattr(orchestrate, "_batch_result_path", lambda *a, **k: "/tmp/x/r.jsonl")
    monkeypatch.setattr(orchestrate, "_batch_account_path", lambda *a, **k: "/tmp/x/acc")
    monkeypatch.setattr(orchestrate, "_read_account_state", lambda *a, **k: "12300000000")
    monkeypatch.setattr(orchestrate.shutil, "rmtree", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate.time, "sleep", lambda *a, **k: None)

    def fake_collect(procs, **kwargs):
        calls["n"] += 1
        # 前两次无结果(将被判 503 重试),第三次成功
        return {list(procs)[0]: [{"passed": True, "record_id": "rec1"}] if calls["n"] == 3 else "failed"}

    monkeypatch.setattr(orchestrate, "collect_results", fake_collect)
    # 503 崩溃时 agent 未落盘 → jsonl 为空,兜底读取拿不到结果才会触发重试;
    # 第 3 次(与 fake_collect 同步)才写出通过结果。
    monkeypatch.setattr(orchestrate, "_load_jsonl",
                        lambda *a, **k: [{"passed": True, "record_id": "rec1"}] if calls["n"] == 3 else [])
    monkeypatch.setattr(orchestrate, "_tail_file", lambda *a, **k: "503 No available accounts")

    result = orchestrate.execute_case_via_agent("gaotu", "android", "dev1", entry)
    assert result["passed"] is True
    assert calls["n"] == 3


def test_execute_case_via_agent_no_retry_on_429(monkeypatch):
    entry = {"record_id": "rec1", "name": "用例A", "module": "m"}
    calls = {"n": 0}
    notified = []

    monkeypatch.setattr(orchestrate, "launch_agent_batch", lambda *a, **k: object())
    monkeypatch.setattr(orchestrate, "_batch_result_dir", lambda *a, **k: "/tmp/x")
    monkeypatch.setattr(orchestrate, "_batch_result_path", lambda *a, **k: "/tmp/x/r.jsonl")
    monkeypatch.setattr(orchestrate, "_batch_account_path", lambda *a, **k: "/tmp/x/acc")
    monkeypatch.setattr(orchestrate.shutil, "rmtree", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate, "_notify", lambda *a, **k: notified.append(a))

    def fake_collect(procs, **kwargs):
        calls["n"] += 1
        return {list(procs)[0]: "failed"}

    monkeypatch.setattr(orchestrate, "collect_results", fake_collect)
    monkeypatch.setattr(orchestrate, "_tail_file", lambda *a, **k: "429 api key 日限额已用完")

    result = orchestrate.execute_case_via_agent("gaotu", "android", "dev1", entry, version="1.0")
    assert result["passed"] is False
    assert calls["n"] == 1  # 429 不重试,只跑一次
    assert len(notified) == 1  # 最终失败统一报警一次


def test_execute_case_via_agent_backfills_record_id_from_entry(monkeypatch):
    # agent 结果 schema 不含 record_id;单条路径必须从 entry 回填,否则固化被跳过
    entry = {"record_id": "recX", "name": "用例B", "module": "登录", "order": "3", "state_group": "已登录"}

    monkeypatch.setattr(orchestrate, "launch_agent_batch", lambda *a, **k: object())
    monkeypatch.setattr(orchestrate, "_batch_result_dir", lambda *a, **k: "/tmp/x")
    monkeypatch.setattr(orchestrate, "_batch_result_path", lambda *a, **k: "/tmp/x/r.jsonl")
    monkeypatch.setattr(orchestrate, "_batch_account_path", lambda *a, **k: "/tmp/x/acc")
    monkeypatch.setattr(orchestrate, "_read_account_state", lambda *a, **k: "")
    monkeypatch.setattr(orchestrate.shutil, "rmtree", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate.os, "makedirs", lambda *a, **k: None)
    # agent 只写 passed/steps,无 record_id/name/module
    monkeypatch.setattr(orchestrate, "collect_results",
                        lambda procs, **k: {list(procs)[0]: [{"passed": True, "steps": []}]})
    monkeypatch.setattr(orchestrate, "_load_jsonl", lambda *a, **k: [{"passed": True, "steps": []}])

    result = orchestrate.execute_case_via_agent("gaotu", "android", "dev1", entry)
    assert result["record_id"] == "recX"
    assert result["name"] == "用例B"
    assert result["module"] == "登录"
    assert result["order"] == "3"
    assert result["state_group"] == "已登录"


def test_resolve_max_concurrent_agent_procs_defaults_to_20(monkeypatch):
    monkeypatch.delenv("ORCH_MAX_CONCURRENT_AGENT_PROCS", raising=False)
    assert orchestrate.resolve_max_concurrent_agent_procs() == 20


def test_resolve_max_concurrent_agent_procs_reads_env(monkeypatch):
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_AGENT_PROCS", "8")
    assert orchestrate.resolve_max_concurrent_agent_procs() == 8


def test_resolve_max_concurrent_agent_procs_rejects_non_positive(monkeypatch):
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_AGENT_PROCS", "0")
    with pytest.raises(ValueError, match="ORCH_MAX_CONCURRENT_AGENT_PROCS"):
        orchestrate.resolve_max_concurrent_agent_procs()


def test_resolve_max_batch_prompt_chars_defaults_to_24000(monkeypatch):
    monkeypatch.delenv("ORCH_MAX_BATCH_PROMPT_CHARS", raising=False)
    assert orchestrate.resolve_max_batch_prompt_chars() == 24000


def test_resolve_max_batch_prompt_chars_reads_env(monkeypatch):
    monkeypatch.setenv("ORCH_MAX_BATCH_PROMPT_CHARS", "4096")
    assert orchestrate.resolve_max_batch_prompt_chars() == 4096


def test_resolve_max_batch_prompt_chars_rejects_non_positive(monkeypatch):
    monkeypatch.setenv("ORCH_MAX_BATCH_PROMPT_CHARS", "0")
    with pytest.raises(ValueError, match="ORCH_MAX_BATCH_PROMPT_CHARS"):
        orchestrate.resolve_max_batch_prompt_chars()


def test_resolve_ui_audit_enabled_defaults_to_true(monkeypatch):
    monkeypatch.delenv("ORCH_ENABLE_UI_AUDIT", raising=False)
    assert orchestrate.resolve_ui_audit_enabled() is True


def test_resolve_ui_audit_enabled_accepts_false_values(monkeypatch):
    monkeypatch.setenv("ORCH_ENABLE_UI_AUDIT", "false")
    assert orchestrate.resolve_ui_audit_enabled() is False


def test_agent_log_path_uses_neutral_name():
    assert orchestrate.agent_log_path("device1") == "/tmp/agent_device1.log"


def test_build_agent_command_for_claude_includes_add_dir(tmp_path):
    skill_dir = str(tmp_path / "skills")
    common_dir = str(tmp_path / "common")
    cmd = orchestrate.build_agent_command(
        runner="claude",
        prompt="run cases",
        skill_dir=skill_dir,
        common_dir=common_dir,
    )
    assert cmd[0] == "claude"
    assert cmd[1] == "--dangerously-skip-permissions"
    assert cmd[2:6] == ["--add-dir", skill_dir, "--add-dir", common_dir]
    assert cmd[-2:] == ["--print", "run cases"]


def test_build_agent_command_for_codex_does_not_use_add_dir(tmp_path):
    cmd = orchestrate.build_agent_command(
        runner="codex",
        prompt="run cases",
        skill_dir=str(tmp_path / "skills"),
        common_dir=str(tmp_path / "common"),
    )
    assert cmd[0] == "codex"
    assert "--add-dir" not in cmd


def test_build_shared_execution_context_contains_common_rules():
    context = orchestrate.build_shared_execution_context("gaotu")
    assert "common/elements/login.md" in context
    assert "common/device.md" in context
    assert "/tmp/result_<udid>.jsonl" not in context


def test_build_prompt_includes_shared_execution_context(monkeypatch):
    monkeypatch.setattr(orchestrate, "build_shared_execution_context", lambda app_id: "共享上下文片段")
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: True)
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "共享上下文片段" in prompt


def test_build_prompt_includes_ui_audit_rules_when_enabled(monkeypatch):
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: True)
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "UI 规范自动检查" in prompt
    assert "文本是否截断" in prompt


def test_build_prompt_prevents_codex_mcp_session_spin(monkeypatch):
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: False)
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "Appium MCP 调用纪律" in prompt
    assert "不得用 `true`、空 shell" in prompt
    assert "`pwd/date/echo`" in prompt
    assert "MCP session 创建未发起" in prompt
    assert "MCP 工具调用未发起" in prompt


def test_build_prompt_for_batch_forbids_legacy_result_path(monkeypatch):
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: False)
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt(
        "gaotu",
        "a1",
        "Android",
        entries,
        result_path="/tmp/case_results/a1/r1/batch_results/batch_a1_0/result_a1.jsonl",
    )
    assert "本批只允许写入 /tmp/case_results/a1/r1/batch_results/batch_a1_0/result_a1.jsonl" in prompt
    assert "不得另写 /tmp/result_a1.jsonl" in prompt


def test_build_agent_command_codex_enables_noninteractive_mcp_tools():
    cmd = orchestrate.build_agent_command("codex", "prompt", "/tmp/skill", "/tmp/common")
    assert cmd[:3] == ["codex", "exec", "--ignore-user-config"]
    assert "--ephemeral" in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "model_provider=\"custom\"" in cmd
    assert "mcp_servers.appium-mcp.type=\"stdio\"" in cmd
    assert "mcp_servers.appium-mcp.command=\"appium-mcp\"" in cmd
    assert "mcp_servers.feishu.enabled=false" not in cmd
    assert "mcp_servers.feishu-docx-blocks.enabled=false" not in cmd
    assert cmd[-1] == "prompt"


def test_launch_agent_per_device_uses_resolved_runner(monkeypatch, tmp_path):
    entries = {"a1": {"platform": "Android", "entries": []}}
    popen_calls = []

    class _Proc:
        pid = 123
        def poll(self):
            return None

    def fake_popen(cmd, stdout=None, stderr=None):
        popen_calls.append(cmd)
        return _Proc()

    monkeypatch.setattr(orchestrate, "resolve_agent_runner", lambda: "codex")
    monkeypatch.setattr(orchestrate, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(orchestrate, "agent_log_path", lambda udid: str(tmp_path / f"agent_{udid}.log"))
    monkeypatch.setattr(orchestrate.subprocess, "Popen", fake_popen)
    orchestrate.launch_agent_per_device("gaotu", entries, version="5.91.90")
    assert popen_calls[0][0] == "codex"
    assert "--dangerously-bypass-approvals-and-sandbox" in popen_calls[0]
    assert "--ignore-user-config" in popen_calls[0]
    assert "mcp_servers.appium-mcp.command=\"appium-mcp\"" in popen_calls[0]


def test_launch_agent_per_device_preserves_claude_add_dir(monkeypatch, tmp_path):
    entries = {"a1": {"platform": "Android", "entries": []}}
    popen_calls = []

    class _Proc:
        pid = 123
        def poll(self):
            return None

    def fake_popen(cmd, stdout=None, stderr=None):
        popen_calls.append(cmd)
        return _Proc()

    monkeypatch.setattr(orchestrate, "resolve_agent_runner", lambda: "claude")
    monkeypatch.setattr(orchestrate, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(orchestrate, "agent_log_path", lambda udid: str(tmp_path / f"agent_{udid}.log"))
    monkeypatch.setattr(orchestrate.subprocess, "Popen", fake_popen)
    orchestrate.launch_agent_per_device("gaotu", entries, version="5.91.90")
    assert "--add-dir" in popen_calls[0]


def test_run_exploration_uses_resolved_runner(monkeypatch, tmp_path):
    run_calls = []

    class _Result:
        returncode = 1

    def fake_run(cmd, stdout=None, stderr=None, timeout=None):
        run_calls.append(cmd)
        return _Result()

    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(orchestrate, "resolve_agent_runner", lambda: "codex")
    monkeypatch.setattr(orchestrate, "build_agent_command",
                        lambda runner, prompt, skill_dir, common_dir: ["codex", "exec", prompt])
    monkeypatch.setattr(orchestrate.subprocess, "run", fake_run)

    orchestrate.run_exploration("gaotu", "5.91.90", "a1")

    assert run_calls[0][0] == "codex"
    assert run_calls[0][1] == "exec"


def test_run_exploration_writes_to_app_root_not_version_dir(monkeypatch, tmp_path):
    run_calls = []

    class _Result:
        returncode = 1

    def fake_run(cmd, stdout=None, stderr=None, timeout=None):
        run_calls.append(cmd)
        return _Result()

    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(orchestrate, "resolve_agent_runner", lambda: "codex")
    monkeypatch.setattr(orchestrate, "build_agent_command",
                        lambda runner, prompt, skill_dir, common_dir: ["codex", "exec", prompt])
    monkeypatch.setattr(orchestrate.subprocess, "run", fake_run)

    orchestrate.run_exploration("gaotu", "5.91.90", "a1")

    assert (tmp_path / "apps" / "gaotu").is_dir()
    assert not (tmp_path / "apps" / "gaotu" / "5.91.90").exists()
    assert "生成 apps/gaotu/index.md 和 pages/*.md" in run_calls[0][2]


def test_run_exploration_skips_when_index_exists(monkeypatch, tmp_path):
    run_calls = []

    class _Result:
        returncode = 1

    app_dir = tmp_path / "apps" / "gaotu"
    app_dir.mkdir(parents=True)
    (app_dir / "index.md").write_text("old map")

    def fake_run(cmd, stdout=None, stderr=None, timeout=None):
        run_calls.append(cmd)
        return _Result()

    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(orchestrate, "resolve_agent_runner", lambda: "codex")
    monkeypatch.setattr(orchestrate, "build_agent_command",
                        lambda runner, prompt, skill_dir, common_dir: ["codex", "exec", prompt])
    monkeypatch.setattr(orchestrate.subprocess, "run", fake_run)

    orchestrate.run_exploration("gaotu", "5.91.90", "a1")

    assert run_calls == []


def test_run_exploration_force_reruns_when_index_exists(monkeypatch, tmp_path):
    run_calls = []

    class _Result:
        returncode = 1

    app_dir = tmp_path / "apps" / "gaotu"
    app_dir.mkdir(parents=True)
    (app_dir / "index.md").write_text("old map")

    def fake_run(cmd, stdout=None, stderr=None, timeout=None):
        run_calls.append(cmd)
        return _Result()

    monkeypatch.setenv("ORCH_FORCE_EXPLORE", "1")
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(orchestrate, "resolve_agent_runner", lambda: "codex")
    monkeypatch.setattr(orchestrate, "build_agent_command",
                        lambda runner, prompt, skill_dir, common_dir: ["codex", "exec", prompt])
    monkeypatch.setattr(orchestrate.subprocess, "run", fake_run)

    orchestrate.run_exploration("gaotu", "5.91.90", "a1")

    assert run_calls, "expected forced exploration to rerun when index.md already exists"


def test_reset_apps_after_exploration_calls_platform_stoppers(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrate, "_stop_android_app",
                        lambda udid, pkg: calls.append(("android", udid, pkg)) or True)
    monkeypatch.setattr(orchestrate, "_stop_ios_app",
                        lambda udid, bundle_id: calls.append(("ios", udid, bundle_id)) or False)

    orchestrate.reset_apps_after_exploration("gaotu", ["a1"], ["i1"])

    assert calls == [
        ("android", "a1", "com.gaotu100.superclass"),
        ("ios", "i1", "com.gaotu100.superclass"),
    ]

import tempfile
import json as _json

def test_collect_results_reads_json(tmp_path):
    udid = "test_device"
    cases = [{"name": "case1", "platform": "Android", "device": udid,
               "module": "首页", "passed": True, "duration": 30, "steps": []}]
    _write_jsonl(tmp_path / f"result_{udid}.jsonl", cases)

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


def test_build_prompt_ios_avoids_manual_wda_url():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "i1", "iOS", entries, wda_port=8100)
    assert "不要手工传 appium:webDriverAgentUrl=http://127.0.0.1:8100" in prompt
    assert "ECONNREFUSED" in prompt


def test_build_prompt_android_no_wda_url():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "webDriverAgentUrl" not in prompt


def test_build_prompt_forbids_midrun_summary_output():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "不要输出阶段性总结" in prompt
    assert "除非全部用例都已执行完成" in prompt


def test_build_prompt_allows_safe_dismissal_buttons_for_prod_popups():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "仅当遇到【非预期内】的线上业务弹窗" in prompt
    assert "关闭" in prompt
    assert "取消" in prompt
    assert "放弃讲义" in prompt
    assert "生产不可达-弹窗阻断" in prompt


def test_build_prompt_requires_structured_action_trace_for_script_generation():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "ACTION/PRECOND 步也要写结构化轨迹字段" in prompt
    assert "script_action" in prompt
    assert "locator" in prompt
    assert "input_value" in prompt


def test_build_prompt_ios_requires_ios_locator_priority():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "i1", "iOS", entries)
    assert "by=accessibility_id" in prompt
    assert "by=name" in prompt
    assert "by=label" in prompt
    assert "by=predicate" in prompt
    assert "by=xpath" in prompt


def test_build_prompt_requires_finishing_startup_for_non_launch_popup_batches():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "state_group": "首页", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "若执行前发现 App 还停留在首次启动流程" in prompt
    assert "先主动完成启动流程" in prompt
    assert "启动弹窗批次除外" in prompt


def test_build_prompt_skips_startup_completion_note_for_launch_popup_batches():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "state_group": "启动弹窗", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "若执行前发现 App 还停留在首次启动流程" not in prompt


def test_generate_case_script_for_passed_high_confidence_case(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec1",
        "name": "case one",
        "module": "首页",
        "platform": "Android",
        "device": "a1",
        "passed": True,
        "steps": [
            {"type": "PRECOND", "text": "账号：12345679000"},
            {"type": "ASSERT", "text": "打开首页", "verify_method": "id",
             "evidence": "com.gaotu100.superclass:id/home", "confidence": "high", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case)

    assert path is not None
    content = (tmp_path / "apps" / "gaotu" / "cases" / "android" / "rec1.py").read_text()
    assert "META" in content
    assert "rec1" in content
    assert "com.gaotu100.superclass:id/home" in content


def test_generate_case_script_adds_assert_ui_when_ui_audit_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: True)
    case = {
        "record_id": "rec_ui",
        "name": "ui audit case",
        "module": "首页",
        "platform": "iOS",
        "device": "i1",
        "passed": True,
        "steps": [
            {"type": "ASSERT", "text": "打开首页", "verify_method": "text",
             "evidence": "首页", "confidence": "high", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "ios", case)

    content = open(path).read()
    assert "'type': 'assert_text'" in content
    assert "'type': 'assert_ui'" in content
    assert "'rules': ['no_blank', 'no_overlap', 'no_occlusion', 'no_truncation', 'safe_area']" in content


def test_generate_case_script_outputs_flow_format(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_flow",
        "name": "flow case",
        "module": "首页",
        "platform": "Android",
        "device": "a1",
        "passed": True,
        "steps": [
            {"type": "PRECOND", "text": "账号未登录"},
            {"type": "ACTION", "text": "点击登录按钮", "script_action": "tap",
             "locator": {"by": "text", "value": "点击登录"}},
            {"type": "ASSERT", "text": "打开首页", "verify_method": "id",
             "evidence": "com.gaotu100.superclass:id/home", "confidence": "high", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case, version="5.91.93")

    content = open(path).read()
    assert "'app_id': 'gaotu'" in content
    assert "'app_version': '5.91.93'" in content
    assert "FLOW = [" in content
    assert "'type': 'prepare_state'" in content
    assert "'type': 'tap'" in content
    assert 'ctx["run_flow"]' in content


def test_generate_case_script_accepts_string_locators_and_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_string_flow",
        "name": "flow case",
        "module": "首页",
        "platform": "Android",
        "device": "a1",
        "passed": True,
        "steps": [
            {
                "type": "ACTION",
                "text": "点击登录按钮",
                "script_action": "tap",
                "locator": "by=id,value=com.gaotu100.superclass:id/account_sign_btn",
                "locator_fallbacks": [
                    "by=xpath,value=//*[@text='登录']",
                    "com.gaotu100.superclass:id/account_sign_btn",
                ],
            },
            {"type": "ASSERT", "text": "打开首页", "verify_method": "id",
             "evidence": "com.gaotu100.superclass:id/home", "confidence": "high", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case)

    content = open(path).read()
    assert "'by': 'id'" in content
    assert "'value': 'com.gaotu100.superclass:id/account_sign_btn'" in content
    assert "'fallbacks': [{'by': 'xpath'" in content


def test_generate_case_script_normalizes_ios_locator_priority(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_ios_flow",
        "name": "ios flow case",
        "module": "首页",
        "platform": "iOS",
        "device": "i1",
        "passed": True,
        "steps": [
            {
                "type": "ACTION",
                "text": "点击首页按钮",
                "script_action": "tap",
                "locator": {"strategy": "accessibility_id", "selector": "首页"},
                "locator_fallbacks": [
                    {"name": "首页"},
                    {"label": "首页"},
                    "predicate=label == '首页'",
                    "//*[@name='首页']",
                ],
            },
            {"type": "ASSERT", "text": "打开首页", "verify_method": "text",
             "evidence": "首页", "confidence": "high", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "ios", case)

    content = open(path).read()
    assert "'by': 'accessibility_id'" in content
    assert "'value': '首页'" in content
    assert "'by': 'name'" in content
    assert "'by': 'label'" in content
    assert "'by': 'predicate'" in content
    assert "'value': \"label == '首页'\"" in content


def test_generate_case_script_infers_prepare_state_from_preconditions(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_precond",
        "name": "precond case",
        "module": "启动登录",
        "platform": "Android",
        "device": "a1",
        "passed": True,
        "steps": [
            {"type": "PRECOND", "text": "账号未登录"},
            {"type": "PRECOND", "text": "当前在我的tab"},
            {"type": "ASSERT", "text": "打开首页", "verify_method": "id",
             "evidence": "com.gaotu100.superclass:id/home", "confidence": "high", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case)

    content = open(path).read()
    assert "'type': 'prepare_state'" in content
    assert "'target': 'my_tab'" in content
    assert "'account': '<UNLOGIN>'" in content


def test_generate_case_script_adds_reinstall_for_startup_preconditions(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_reinstall",
        "name": "startup case",
        "module": "启动弹窗",
        "platform": "Android",
        "device": "a1",
        "passed": True,
        "steps": [
            {"type": "PRECOND", "text": "卸载重装APP，未启动"},
            {"type": "PRECOND", "text": "当前在登录页"},
            {"type": "ASSERT", "text": "看到首启弹窗", "verify_method": "text",
             "evidence": "隐私政策", "confidence": "high", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case)

    content = open(path).read()
    assert content.index("'type': 'reinstall_app'") < content.index("'type': 'prepare_state'")
    assert "'target': 'login'" in content


def test_generate_case_script_inserts_dismiss_system_alert_before_first_assert(tmp_path, monkeypatch):
    # 重装(冷启)用例:生成侧应自动在首个断言前补幂等的 dismiss_system_alert,
    # 清系统网络权限弹窗,免手动插入被重新生成覆盖。
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_alert",
        "name": "首启隐私弹窗",
        "module": "启动弹窗",
        "platform": "iOS",
        "device": "i1",
        "passed": True,
        "steps": [
            {"type": "PRECOND", "text": "卸载重装APP，未启动"},
            {"type": "ACTION", "text": "打开app", "action": "route", "by": "bundleId",
             "value": "com.gaotu100.superclass"},
            {"type": "ASSERT", "text": "隐私弹窗正常弹出", "verify_method": "id",
             "evidence": "同意", "confidence": "high", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "ios", case)

    ns = {}
    exec(open(path).read().split("def execute")[0], ns)
    flow = ns["FLOW"]
    types = [s.get("type") for s in flow]
    assert types.count("dismiss_system_alert") == 1
    dismiss_at = types.index("dismiss_system_alert")
    first_assert = next(i for i, t in enumerate(types) if str(t).startswith("assert_"))
    # 紧邻首个断言之前,且位于 app 拉起动作(reinstall_app/route)之后
    assert dismiss_at == first_assert - 1
    assert types[:dismiss_at] and all(t != "dismiss_system_alert" for t in types[:dismiss_at])
    assert "reinstall_app" in types[:dismiss_at]


def test_generate_case_script_no_dismiss_alert_when_no_reinstall(tmp_path, monkeypatch):
    # 非重装用例:app 已授权网络权限,不会弹系统框,不该插 dismiss_system_alert。
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_noalert",
        "name": "普通用例",
        "module": "首页",
        "platform": "iOS",
        "device": "i1",
        "passed": True,
        "steps": [
            {"type": "PRECOND", "text": "当前在首页"},
            {"type": "ASSERT", "text": "看到首页", "verify_method": "id",
             "evidence": "首页", "confidence": "high", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "ios", case)

    ns = {}
    exec(open(path).read().split("def execute")[0], ns)
    types = [s.get("type") for s in ns["FLOW"]]
    assert "dismiss_system_alert" not in types


def test_generate_case_script_accepts_assert_pass_field_from_result_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_pass_field",
        "name": "result replay case",
        "module": "启动登录",
        "platform": "Android",
        "passed": True,
        "steps": [
            {"type": "ASSERT", "text": "看到隐私弹窗", "pass": True, "verify_method": "id",
             "evidence": "com.gaotu100.superclass:id/tvMessage", "confidence": "high"},
            {"type": "ASSERT", "text": "低置信不生成", "pass": True, "verify_method": "text",
             "evidence": "温馨提示", "confidence": "low"},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case, version="5.91.93")

    content = open(path).read()
    assert "'type': 'assert_id'" in content
    assert "com.gaotu100.superclass:id/tvMessage" in content
    assert "低置信不生成" not in content


def test_generate_case_script_interleaves_numbered_asserts_after_matching_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_interleave",
        "name": "interleave case",
        "module": "启动登录",
        "platform": "Android",
        "passed": True,
        "steps": [
            {"type": "ACTION", "text": "1. 打开高途 APP", "script_action": "route",
             "locator": "by=id,value=com.gaotu100.superclass/.ui.activity.SplashActivity"},
            {"type": "ACTION", "text": "2. 点击不同意", "script_action": "tap",
             "locator": "by=id,value=com.gaotu100.superclass:id/tvCancel"},
            {"type": "ASSERT", "text": "1. app成功启动，隐私弹窗正常弹出", "pass": True,
             "verify_method": "id", "evidence": "com.gaotu100.superclass:id/tvMessage", "confidence": "high"},
            {"type": "ASSERT", "text": "2. 隐私弹窗切换为温馨提示弹窗", "pass": True,
             "verify_method": "text", "evidence": "温馨提示", "confidence": "high"},
            {"type": "ASSERT", "text": "链路汇总断言", "pass": True,
             "verify_method": "text", "evidence": "不同意 -> 温馨提示", "confidence": "high"},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case, version="5.91.93")
    content = open(path).read()
    assert content.index("SplashActivity") < content.index("com.gaotu100.superclass:id/tvMessage")
    assert content.index("com.gaotu100.superclass:id/tvMessage") < content.index("com.gaotu100.superclass:id/tvCancel")
    assert content.index("com.gaotu100.superclass:id/tvCancel") < content.index("'text': '2. 隐私弹窗切换为温馨提示弹窗'")


def test_generate_case_script_normalizes_android_route_locator(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_route_android",
        "name": "android route case",
        "module": "启动登录",
        "platform": "Android",
        "passed": True,
        "steps": [
            {"type": "ACTION", "text": "1. 打开高途 APP", "script_action": "route",
             "locator": "appPackage=com.gaotu100.superclass, appActivity=.ui.activity.SplashActivity"},
            {"type": "ASSERT", "text": "1. app成功启动", "pass": True,
             "verify_method": "id", "evidence": "com.gaotu100.superclass:id/tvMessage", "confidence": "high"},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case, version="5.91.93")
    content = open(path).read()

    assert "com.gaotu100.superclass/.ui.activity.SplashActivity" in content
    assert "appPackage=com.gaotu100.superclass, appActivity=.ui.activity.SplashActivity" not in content


def test_generate_case_script_converts_dialog_text_asserts_to_neighbor_id_asserts(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_dialog_id",
        "name": "dialog assert case",
        "module": "启动登录",
        "platform": "Android",
        "passed": True,
        "steps": [
            {"type": "ACTION", "text": "2. 点击不同意", "script_action": "tap",
             "locator": "by=id,value=com.gaotu100.superclass:id/tvCancel"},
            {"type": "ASSERT", "text": "2. 隐私弹窗切换为温馨提示弹窗", "pass": True,
             "verify_method": "text", "evidence": "温馨提示", "confidence": "high"},
            {"type": "ACTION", "text": "3. 查看温馨提示弹窗", "script_action": "prepare_state",
             "locator": "by=id,value=com.gaotu100.superclass:id/tvTitle|tvMessage|tvCancel|tvConfirm"},
            {"type": "ASSERT", "text": "3. 温馨提示弹窗文案内容布局完整", "pass": True,
             "verify_method": "text", "evidence": "标题：温馨提示", "confidence": "high"},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case, version="5.91.93")

    content = open(path).read()
    assert "'type': 'assert_id'" in content
    assert "com.gaotu100.superclass:id/tvCancel" in content
    assert "com.gaotu100.superclass:id/tvTitle|tvMessage|tvCancel|tvConfirm" in content
    assert "'aux_text': '温馨提示'" in content
    assert "'value': '温馨提示'" not in content
    assert content.index("com.gaotu100.superclass:id/tvCancel") < content.index("com.gaotu100.superclass:id/tvTitle|tvMessage|tvCancel|tvConfirm")


def test_generate_case_script_skips_auto_handled_android_permission_taps_and_filters_neighbor_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_auto_dialog_skip",
        "name": "auto dialog skip case",
        "module": "启动登录",
        "platform": "Android",
        "passed": True,
        "steps": [
            {"type": "ACTION", "text": "1. 允许系统权限", "script_action": "tap",
             "locator": "by=id,value=com.android.permissioncontroller:id/permission_allow_button"},
            {"type": "ASSERT", "text": "1. 隐私弹窗正常展示", "pass": True,
             "verify_method": "text", "evidence": "文案：感谢您下载并使用高途", "confidence": "high"},
            {"type": "ACTION", "text": "2. 点击同意", "script_action": "tap",
             "locator": "by=id,value=com.gaotu100.superclass:id/tvConfirm"},
            {"type": "ASSERT", "text": "2. 进入青少年守护弹窗", "pass": True,
             "verify_method": "text", "evidence": "标题：青少年守护", "confidence": "high"},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case, version="5.91.93")

    content = open(path).read()
    assert "com.android.permissioncontroller:id/permission_allow_button" not in content
    assert "'aux_text': '文案：感谢您下载并使用高途'" in content
    assert "com.gaotu100.superclass:id/tvConfirm" in content


def test_generate_case_script_skips_summary_chain_asserts(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_summary_skip",
        "name": "summary skip case",
        "module": "启动登录",
        "platform": "Android",
        "passed": True,
        "steps": [
            {"type": "ACTION", "text": "1. 点击同意", "script_action": "tap",
             "locator": "by=id,value=com.gaotu100.superclass:id/tvConfirm"},
            {"type": "ASSERT", "text": "1. 青少年守护弹窗出现", "pass": True,
             "verify_method": "text", "evidence": "青少年守护", "confidence": "high"},
            {"type": "ASSERT", "text": "点击「不同意」后隐私弹窗直接切换为温馨提示弹窗，无需关闭再打开\n温馨提示弹窗包含「同意」「简单浏览模式」按钮及三个协议链接\n点击「同意」后跳转至青少年守护弹窗", "pass": True,
             "verify_method": "text", "evidence": "链路：不同意 -> 温馨提示 -> 同意 -> 青少年守护", "confidence": "high"},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case, version="5.91.93")
    content = open(path).read()

    assert "链路：不同意 -> 温馨提示 -> 同意 -> 青少年守护" not in content


def test_is_toast_like_assert_detects_toast_text_step():
    assert orchestrate.is_toast_like_assert({
        "type": "ASSERT",
        "text": "[TOAST] 显示课程已置顶",
        "verify_method": "text",
        "evidence": "课程已置顶",
    }) is True


def test_generate_case_script_skips_low_confidence_case(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec2",
        "name": "case two",
        "module": "首页",
        "platform": "Android",
        "device": "a1",
        "passed": True,
        "steps": [
            {"type": "ASSERT", "text": "视觉判断", "verify_method": "vision",
             "evidence": "/tmp/shot.png", "confidence": "low", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case)

    assert path is None


def test_generated_case_script_softens_toast_assert(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_toast",
        "name": "toast case",
        "module": "首页",
        "platform": "Android",
        "device": "a1",
        "passed": True,
        "steps": [
            {"type": "ASSERT", "text": "[TOAST] 课程已置顶", "verify_method": "text",
             "evidence": "课程已置顶", "confidence": "high", "passed": True},
            {"type": "ASSERT", "text": "菜单变成取消置顶", "verify_method": "id",
             "evidence": "com.gaotu100.superclass:id/menu_cancel_top", "confidence": "high", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case)
    result = orchestrate.run_case_script(
        "gaotu", "android", "a1", path
    )

    assert result["passed"] is False


def test_generated_case_script_passes_when_only_toast_assert_misses(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_toast_only",
        "name": "toast only",
        "module": "首页",
        "platform": "Android",
        "device": "a1",
        "passed": True,
        "steps": [
            {"type": "ASSERT", "text": "[TOAST] 课程已置顶", "verify_method": "text",
             "evidence": "课程已置顶", "confidence": "high", "passed": True},
        ],
    }
    path = orchestrate.generate_case_script("gaotu", "android", case)
    monkeypatch.setattr(orchestrate, "_script_runtime_context",
                        lambda udid: {"assert_evidence_present": lambda method, evidence: False})

    result = orchestrate.run_case_script("gaotu", "android", "a1", path)

    assert result["passed"] is True
    assert "toast/snackbar辅助断言未命中" in result["note"]


def test_run_case_script_prefers_flow_runtime(monkeypatch, tmp_path):
    script = tmp_path / "flow_case.py"
    script.write_text(
        "META={'record_id':'rec1'}\n"
        "FLOW=[{'type':'assert_text','value':'首页'}]\n"
        "def execute(ctx):\n"
        "    return ctx['run_flow'](META, FLOW)\n"
    )
    calls = []
    monkeypatch.setattr(
        orchestrate,
        "_script_runtime_context",
        lambda udid: {"run_flow": lambda meta, flow: calls.append((meta, flow)) or {"passed": True}},
    )
    monkeypatch.setattr(
        orchestrate,
        "_script_runtime_context_for",
        lambda app_id, platform, udid, script_meta=None: {"run_flow": lambda meta, flow: calls.append((meta, flow)) or {"passed": True}},
    )

    result = orchestrate.run_case_script("gaotu", "android", "a1", str(script))

    assert result["passed"] is True
    assert calls and calls[0][0]["record_id"] == "rec1"


def test_run_case_script_ios_uses_platform_runtime_and_closes(monkeypatch, tmp_path):
    script = tmp_path / "ios_flow_case.py"
    script.write_text(
        "META={'record_id':'rec_ios'}\n"
        "FLOW=[{'type':'assert_text','value':'首页'}]\n"
        "def execute(ctx):\n"
        "    return ctx['run_flow'](META, FLOW)\n"
    )
    closed = []
    monkeypatch.setattr(
        orchestrate,
        "_script_runtime_context_for",
        lambda app_id, platform, udid, script_meta=None: {
            "run_flow": lambda meta, flow: {"passed": True, "record_id": meta["record_id"]},
            "close": lambda: closed.append((app_id, platform, udid)) or True,
        },
    )

    result = orchestrate.run_case_script("gaotu", "ios", "i1", str(script))

    assert result["passed"] is True
    assert closed == [("gaotu", "ios", "i1")]


def test_run_case_script_appends_version_mismatch_note(monkeypatch, tmp_path):
    script = tmp_path / "flow_case.py"
    script.write_text(
        "META={'record_id':'rec1','app_version':'5.91.93'}\n"
        "FLOW=[]\n"
        "def execute(ctx):\n"
        "    return {'passed': True, 'note': 'ok'}\n"
    )
    monkeypatch.setattr(
        orchestrate,
        "_script_runtime_context_for",
        lambda app_id, platform, udid, script_meta=None: {
            "installed_app_version": "5.91.90",
            "close": lambda: True,
        },
    )

    result = orchestrate.run_case_script("gaotu", "android", "a1", str(script))

    assert result["passed"] is True
    assert "version mismatch: expected 5.91.93, actual 5.91.90" in result["note"]
    assert result["script_app_version"] == "5.91.93"
    assert result["actual_app_version"] == "5.91.90"


def test_run_flow_dispatches_prepare_tap_input_and_assert():
    calls = []
    runtime = {
        "reinstall_app": lambda step: calls.append(("reinstall_app", step)) or True,
        "route": lambda step: calls.append(("route", step)) or True,
        "prepare_state": lambda step: calls.append(("prepare_state", step)) or True,
        "handle_known_dialogs": lambda step: calls.append(("handle_known_dialogs", step)) or True,
        "tap": lambda step: calls.append(("tap", step)) or True,
        "input": lambda step: calls.append(("input", step)) or True,
        "assert_evidence_present": lambda method, evidence: method == "id" and evidence == "home_id",
    }
    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "首页"},
        [
            {"type": "reinstall_app"},
            {"type": "route", "value": "com.gaotu100.superclass/.ui.activity.SplashActivity"},
            {"type": "prepare_state", "target": "home", "account": "12345679000"},
            {"type": "handle_known_dialogs"},
            {"type": "tap", "by": "id", "value": "tab_home"},
            {"type": "input", "by": "id", "value": "phone", "text": "12345679000"},
            {"type": "assert_id", "value": "home_id", "text": "看到首页"},
        ],
        runtime,
    )

    assert result["passed"] is True
    assert [name for name, _ in calls] == [
        "reinstall_app",
        "route",
        "prepare_state",
        "handle_known_dialogs",
        "tap",
        "input",
        "handle_known_dialogs",
    ]


def test_run_flow_dispatches_appium_lifecycle_activate_string():
    calls = []
    runtime = {
        "appium_app_lifecycle": lambda step: calls.append(step) or step.get("action") == "activate",
    }

    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "首页"},
        [{"type": "appium_app_lifecycle activate com.gaotu100.superclass"}],
        runtime,
    )

    assert result["passed"] is True
    assert calls[0]["type"] == "appium_app_lifecycle"
    assert calls[0]["action"] == "activate"
    assert calls[0]["value"] == "com.gaotu100.superclass"


def test_run_flow_appium_lifecycle_overrides_placeholder_value():
    calls = []
    runtime = {
        "appium_app_lifecycle": lambda step: calls.append(step) or step.get("value") == "com.gaotu100.superclass",
    }

    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "首页"},
        [{"type": "appium_app_lifecycle activate com.gaotu100.superclass", "value": "-"}],
        runtime,
    )

    assert result["passed"] is True
    assert calls[0]["value"] == "com.gaotu100.superclass"


def test_run_flow_normalizes_legacy_tap_id_action():
    calls = []
    runtime = {
        "tap": lambda step: calls.append(step) or step.get("value") == "com.gaotu100.superclass:id/tvConfirm",
    }

    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "首页", "bundle_id": "com.gaotu100.superclass"},
        [{"type": "tap tvConfirm(同意)", "by": "text", "value": "id/tvConfirm"}],
        runtime,
    )

    assert result["passed"] is True
    assert calls[0]["type"] == "tap"
    assert calls[0]["by"] == "id"


def test_run_flow_skips_legacy_clickable_span_action():
    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "首页"},
        [{"type": "clickable-span 坐标点击", "value": "coordinate(clickable span)"}],
        {},
    )

    assert result["passed"] is True
    assert "legacy clickable-span action skipped" in result["steps"][0]["note"]


def test_run_flow_dispatches_assert_ui_and_preserves_structured_result():
    runtime = {
        "assert_ui": lambda step: {
            "passed": True,
            "note": "UI无明显异常",
            "verify_method": "vision",
            "evidence": "/tmp/ui.png",
            "confidence": "low",
            "checkpoint_index": 2,
        },
    }

    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "首页"},
        [{"type": "assert_ui", "text": "UI规范检查"}],
        runtime,
    )

    assert result["passed"] is True
    assert result["steps"][0]["type"] == "ASSERT_UI"
    assert result["steps"][0]["verify_method"] == "vision"
    assert result["steps"][0]["evidence"] == "/tmp/ui.png"
    assert result["steps"][0]["confidence"] == "low"
    assert result["steps"][0]["checkpoint_index"] == 2


def test_run_flow_fails_on_unsupported_action_step():
    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "首页"},
        [{"type": "tap", "by": "id", "value": "tab_home"}],
        {"assert_evidence_present": lambda *args, **kwargs: True},
    )

    assert result["passed"] is False
    assert "unsupported flow step" in result["note"]


def test_run_prepare_state_noop_when_already_on_target():
    runtime = {
        "read_page_source": lambda force_refresh=False: 'text="首页" text="我的"',
        "handle_known_dialogs": lambda step=None: True,
        "tap_text": lambda text: (_ for _ in ()).throw(AssertionError("should not tap")),
    }

    assert orchestrate._run_prepare_state("a1", {"target": "home"}, runtime) is True


def test_run_prepare_state_routes_to_my_tab_when_needed(monkeypatch):
    monkeypatch.setattr(orchestrate.time, "sleep", lambda *_: None)
    taps = []
    page_sources = iter([
        'text="首页" text="上课"',
        'text="我的" content-desc="点击登录, 欢迎来到高途"',
    ])
    runtime = {
        "read_page_source": lambda force_refresh=False: next(page_sources),
        "handle_known_dialogs": lambda step=None: True,
        "tap_text": lambda text: taps.append(text) or True,
    }

    assert orchestrate._run_prepare_state("a1", {"target": "my_tab"}, runtime) is True
    assert taps == ["我的"]


def test_run_prepare_state_polls_until_target_settles(monkeypatch):
    # 冷启后前几次读页还没渲染出目标态,poll 到 settle 才命中(不再单次误判失败回退 agent)。
    monkeypatch.setattr(orchestrate.time, "sleep", lambda *_: None)
    reads = []
    page_sources = iter([
        "启动中...",
        "启动中...",
        'text="首页" text="发现"',
    ])

    def read(force_refresh=False):
        s = next(page_sources)
        reads.append(s)
        return s

    runtime = {
        "read_page_source": read,
        "handle_known_dialogs": lambda step=None: True,
        "tap_text": lambda text: True,
    }

    assert orchestrate._run_prepare_state("a1", {"target": "home"}, runtime) is True
    assert len(reads) == 3  # 前两次未 settle,第三次命中


def test_run_prepare_state_fails_after_exhausting_polls(monkeypatch):
    monkeypatch.setattr(orchestrate.time, "sleep", lambda *_: None)
    attempts = {"n": 0}

    def read(force_refresh=False):
        attempts["n"] += 1
        return "白屏加载中"

    runtime = {
        "read_page_source": read,
        "handle_known_dialogs": lambda step=None: True,
        "tap_text": lambda text: True,
    }

    assert orchestrate._run_prepare_state("a1", {"target": "home"}, runtime) is False
    assert attempts["n"] == orchestrate.PREPARE_STATE_POLL_ATTEMPTS


def test_run_prepare_state_login_target_matches_on_poll(monkeypatch):
    # target=login 无 route,靠 poll 等登录页渲染出"手机号登录/获取验证码"即命中。
    monkeypatch.setattr(orchestrate.time, "sleep", lambda *_: None)
    page_sources = iter([
        "启动中...",
        'text="手机号登录" text="获取验证码"',
    ])
    runtime = {
        "read_page_source": lambda force_refresh=False: next(page_sources),
        "handle_known_dialogs": lambda step=None: True,
        "tap_text": lambda text: (_ for _ in ()).throw(AssertionError("login 不应 route")),
    }

    assert orchestrate._run_prepare_state("a1", {"target": "login"}, runtime) is True


def test_resolve_route_component_prefers_explicit_component():
    component = orchestrate.orch_case_runtime.resolve_route_component(
        "a1",
        {"value": "com.gaotu100.superclass/.ui.activity.SplashActivity"},
        orchestrate.subprocess,
    )

    assert component == "com.gaotu100.superclass/.ui.activity.SplashActivity"


def test_resolve_route_component_uses_resolve_activity_fallback(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        return type("Result", (), {
            "returncode": 0,
            "stdout": "priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\ncom.gaotu100.superclass/.ui.activity.SplashActivity\n",
        })()

    fake_subprocess = type("FakeSubprocess", (), {
        "run": staticmethod(fake_run),
        "TimeoutExpired": TimeoutError,
    })

    component = orchestrate.orch_case_runtime.resolve_route_component(
        "a1",
        {
            "fallbacks": [
                {"by": "text", "value": "adb shell cmd package resolve-activity --brief com.gaotu100.superclass"}
            ]
        },
        fake_subprocess,
    )

    assert component == "com.gaotu100.superclass/.ui.activity.SplashActivity"
    assert calls == [[
        "adb", "-s", "a1", "shell", "cmd", "package", "resolve-activity", "--brief", "com.gaotu100.superclass"
    ]]


def test_find_bounds_by_locator_supports_xpath_text():
    center = orchestrate.orch_case_runtime.find_bounds_by_locator(
        '<node text="不同意" bounds="[10,20][110,220]" />',
        "xpath",
        "//*[@text='不同意']",
    )

    assert center == (60, 120)


def test_android_runtime_handle_known_dialogs_prefers_system_allow_button():
    page_sources = iter([
        '<node resource-id="com.android.permissioncontroller:id/permission_allow_button" bounds="[10,20][110,220]" />',
        '<node text="手机号登录" bounds="[0,0][10,10]" />',
    ])
    taps = []
    class FakeSubprocess:
        TimeoutExpired = TimeoutError

        @staticmethod
        def run(cmd, capture_output, text, timeout):
            return type("Result", (), {"stdout": next(page_sources), "returncode": 0})()

    runtime = orchestrate.orch_case_runtime.script_runtime_context(
        udid="a1",
        subprocess_module=FakeSubprocess,
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        tap_with_locator_fn=lambda udid, step, source: True,
        adb_input_text_fn=lambda udid, text: True,
        tap_by_text_fn=lambda udid, text: False,
        run_flow_fn=lambda meta, flow, runtime: {"passed": True},
        known_dialog_text_actions=(),
    )
    original_adb_tap = orchestrate.orch_case_runtime.adb_tap
    try:
        orchestrate.orch_case_runtime.adb_tap = lambda udid, x, y, subprocess_module: taps.append((udid, x, y)) or True
        assert runtime["handle_known_dialogs"]({}) is True
    finally:
        orchestrate.orch_case_runtime.adb_tap = original_adb_tap

    assert taps == [("a1", 60, 120)]


def test_android_runtime_tap_retries_after_handling_known_dialogs(monkeypatch):
    monkeypatch.setattr(orchestrate.orch_case_runtime.time, "sleep", lambda _: None)
    scripted = [
        '<node resource-id="com.android.permissioncontroller:id/permission_allow_button" bounds="[10,20][110,220]" />',
        '<node text="不同意" bounds="[20,30][120,230]" />',
    ]
    source_box = {"i": 0}

    def next_source():
        # 脚本化前若干次读,之后稳定停在最后一屏(点后无变化→触发重放逻辑,不会耗尽)
        idx = min(source_box["i"], len(scripted) - 1)
        source_box["i"] += 1
        return scripted[idx]

    tap_attempts = []
    text_taps = []
    class FakeSubprocess:
        TimeoutExpired = TimeoutError

        @staticmethod
        def run(cmd, capture_output, text, timeout):
            return type("Result", (), {"stdout": next_source(), "returncode": 0})()

    runtime = orchestrate.orch_case_runtime.script_runtime_context(
        udid="a1",
        subprocess_module=FakeSubprocess,
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        tap_with_locator_fn=lambda udid, step, source: tap_attempts.append(source) or ("permissioncontroller" not in source),
        adb_input_text_fn=lambda udid, text: True,
        tap_by_text_fn=lambda udid, text: text_taps.append(text) or True,
        run_flow_fn=lambda meta, flow, runtime: {"passed": True},
        known_dialog_text_actions=(),
    )
    original_adb_tap = orchestrate.orch_case_runtime.adb_tap
    try:
        orchestrate.orch_case_runtime.adb_tap = lambda udid, x, y, subprocess_module: True
        assert runtime["tap"]({"by": "xpath", "value": "//*[@text='不同意']"}) is True
    finally:
        orchestrate.orch_case_runtime.adb_tap = original_adb_tap

    assert len(tap_attempts) >= 1
    assert text_taps == []


@pytest.mark.parametrize("step,expected", [
    ({"by": "text", "value": "同意"}, False),
    ({"by": "id", "value": "tab_home"}, False),
    ({"by": "text", "value": "提交订单"}, True),
    ({"by": "text", "value": "确认支付"}, True),
    ({"by": "id", "value": "btn", "text": "立即下单"}, True),
    ({"by": "id", "value": "btn", "fallbacks": [{"by": "text", "value": "领取优惠券"}]}, True),
    ({"by": "text", "value": "关闭"}, False),
])
def test_is_write_action_classification(step, expected):
    assert orchestrate.orch_case_runtime.is_write_action(step) is expected


def _android_tap_runtime(sources, tap_ok, subprocess_stub=None):
    """构造安卓脚本 runtime,read_page_source 依次返回 sources(耗尽后停在最后一屏)。"""
    box = {"i": 0}

    def next_source():
        idx = min(box["i"], len(sources) - 1)
        box["i"] += 1
        return sources[idx]

    class FakeSubprocess:
        TimeoutExpired = TimeoutError

        @staticmethod
        def run(cmd, capture_output, text, timeout):
            return type("Result", (), {"stdout": next_source(), "returncode": 0})()

    return orchestrate.orch_case_runtime.script_runtime_context(
        udid="a1",
        subprocess_module=FakeSubprocess,
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        tap_with_locator_fn=tap_ok,
        adb_input_text_fn=lambda udid, text: True,
        tap_by_text_fn=lambda udid, text: True,
        run_flow_fn=lambda meta, flow, runtime: {"passed": True},
        known_dialog_text_actions=(),
    )


def test_android_tap_replays_when_ui_unchanged(monkeypatch):
    """导航类点击点后 UI 无变化 → 重放该点击(最多 2 次)。"""
    monkeypatch.setattr(orchestrate.orch_case_runtime.time, "sleep", lambda _: None)
    taps = []
    runtime = _android_tap_runtime(
        sources=["<node text='首页'/>"],  # 恒定不变 → 触发重放
        tap_ok=lambda udid, step, source: taps.append(source) or True,
    )
    assert runtime["tap"]({"by": "text", "value": "同意"}) is True
    # 初次 1 次 + 重放 2 次 = 3 次点击
    assert len(taps) == 3


def test_android_tap_stops_replay_when_ui_changes(monkeypatch):
    """点后 UI 变化 → 不再重放。"""
    monkeypatch.setattr(orchestrate.orch_case_runtime.time, "sleep", lambda _: None)
    taps = []
    # 读序:handle_known_dialogs 预读 1 次 + before 1 次(均"首页"),点后读到"详情页"已变化
    runtime = _android_tap_runtime(
        sources=["<node text='首页'/>", "<node text='首页'/>", "<node text='详情页'/>"],
        tap_ok=lambda udid, step, source: taps.append(source) or True,
    )
    assert runtime["tap"]({"by": "text", "value": "同意"}) is True
    assert len(taps) == 1  # 只点了一次,UI 已变化不重放


def test_android_tap_write_action_never_replays(monkeypatch):
    """写操作(下单/支付…)点后即便 UI 无变化也不重放,防重复写线上数据。"""
    monkeypatch.setattr(orchestrate.orch_case_runtime.time, "sleep", lambda _: None)
    taps = []
    runtime = _android_tap_runtime(
        sources=["<node text='结算页'/>"],  # 恒定不变
        tap_ok=lambda udid, step, source: taps.append(source) or True,
    )
    assert runtime["tap"]({"by": "text", "value": "提交订单"}) is True
    assert len(taps) == 1  # 写操作只点一次


def test_android_tap_polls_until_element_appears(monkeypatch):
    """页面加载中目标元素尚未出现:动作步短轮询等它渲染,命中即点,不一次 miss 就失败。"""
    monkeypatch.setattr(orchestrate.orch_case_runtime.time, "sleep", lambda _: None)
    calls = {"n": 0}

    def tap_ok(udid, step, source):
        calls["n"] += 1
        return calls["n"] >= 3  # 前 2 次 miss(加载中),第 3 次命中

    # 用写操作用例避免点后重放干扰计数,只验证"定位轮询到第 3 次命中"
    runtime = _android_tap_runtime(sources=["<node/>"], tap_ok=tap_ok)
    assert runtime["tap"]({"by": "text", "value": "提交订单"}) is True
    assert calls["n"] == 3


def test_android_tap_fails_after_poll_budget_exhausted(monkeypatch):
    """元素始终不出现:轮询预算耗尽后才判失败(回退 agent),不无限等。"""
    monkeypatch.setattr(orchestrate.orch_case_runtime.time, "sleep", lambda _: None)
    calls = {"n": 0}

    def tap_ok(udid, step, source):
        calls["n"] += 1
        return False

    runtime = _android_tap_runtime(sources=["<node/>"], tap_ok=tap_ok)
    assert runtime["tap"]({"by": "text", "value": "同意"}) is False
    # 初次 1 次 + 轮询 TAP_POLL_ATTEMPTS 次
    assert calls["n"] == 1 + orchestrate.orch_case_runtime.TAP_POLL_ATTEMPTS


def test_android_input_polls_until_element_appears(monkeypatch):
    """input 走同一套定位轮询:输入框未渲染时等它出现再输入。"""
    monkeypatch.setattr(orchestrate.orch_case_runtime.time, "sleep", lambda _: None)
    calls = {"n": 0}

    def tap_ok(udid, step, source):
        calls["n"] += 1
        return calls["n"] >= 2

    runtime = _android_tap_runtime(sources=["<node/>"], tap_ok=tap_ok)
    assert runtime["input"]({"by": "id", "value": "phone", "text": "12300000000"}) is True
    assert calls["n"] == 2


def test_ios_tap_replays_when_ui_unchanged(monkeypatch):
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios.time, "sleep", lambda _: None)
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_create_session", lambda port, bundle_id: "sid")
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_get_source", lambda port, sid: "<App/>")  # 恒定
    clicks = []
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_tap_with_locator",
                        lambda port, sid, step: clicks.append(step.get("value")) or True)
    runtime = orchestrate.orch_case_runtime_ios.script_runtime_context(
        "i1", 8100, "com.gaotu100.superclass",
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        run_flow_fn=orchestrate._run_flow,
        known_dialog_text_actions=(),
    )
    assert runtime["tap"]({"by": "accessibility_id", "value": "同意"}) is True
    assert len(clicks) == 3  # 初次 + 重放 2 次


def test_ios_tap_write_action_never_replays(monkeypatch):
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios.time, "sleep", lambda _: None)
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_create_session", lambda port, bundle_id: "sid")
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_get_source", lambda port, sid: "<App/>")
    clicks = []
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_tap_with_locator",
                        lambda port, sid, step: clicks.append(step.get("value")) or True)
    runtime = orchestrate.orch_case_runtime_ios.script_runtime_context(
        "i1", 8100, "com.gaotu100.superclass",
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        run_flow_fn=orchestrate._run_flow,
        known_dialog_text_actions=(),
    )
    assert runtime["tap"]({"by": "accessibility_id", "value": "确认支付"}) is True
    assert len(clicks) == 1


def _ios_runtime_for_alert(monkeypatch, alerts):
    """构造只关心系统 alert 的 iOS runtime;alerts 为按序返回的 alert 文案列表。"""
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios.time, "sleep", lambda _: None)
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_create_session", lambda port, bundle_id: "sid")
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_get_source", lambda port, sid: "<App/>")
    seq = list(alerts)
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_alert_text",
                        lambda port, sid: seq.pop(0) if seq else "")
    accepts = []
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_accept_alert",
                        lambda port, sid, name=None: accepts.append(name) or True)
    runtime = orchestrate.orch_case_runtime_ios.script_runtime_context(
        "i1", 8100, "com.gaotu100.superclass",
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        run_flow_fn=orchestrate._run_flow,
        known_dialog_text_actions=(),
    )
    return runtime, accepts


def test_ios_dismiss_system_alert_accepts_network_alert(monkeypatch):
    # 冷启后网络权限弹窗遮挡隐私弹窗:该 step 幂等清掉它并返回 True。
    runtime, accepts = _ios_runtime_for_alert(
        monkeypatch, ['允许"高途"使用无线数据？\n关闭无线数据时…', ""])
    assert runtime["dismiss_system_alert"]({}) is True
    assert accepts == ["无线局域网与蜂窝网络"]


def test_ios_dismiss_system_alert_noop_when_no_alert(monkeypatch):
    # 无系统弹窗:跳过、不点任何按钮,仍返回 True(不中断 FLOW)。
    runtime, accepts = _ios_runtime_for_alert(monkeypatch, [""])
    assert runtime["dismiss_system_alert"]({}) is True
    assert accepts == []


def test_ios_dismiss_system_alert_true_when_session_unavailable(monkeypatch):
    # 建 session 失败(8100 proxy 挂)也视为已就绪返回 True,绝不因它判失败。
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios.time, "sleep", lambda _: None)
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_create_session", lambda port, bundle_id: "")
    runtime = orchestrate.orch_case_runtime_ios.script_runtime_context(
        "i1", 8100, "com.gaotu100.superclass",
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        run_flow_fn=orchestrate._run_flow,
        known_dialog_text_actions=(),
    )
    assert runtime["dismiss_system_alert"]({}) is True


def test_android_dismiss_system_alert_taps_allow_and_returns_true():
    source = ('<node resource-id="com.android.permissioncontroller:id/permission_allow_button" '
              'bounds="[10,20][110,220]" />')
    taps = []
    class FakeSubprocess:
        TimeoutExpired = TimeoutError

        @staticmethod
        def run(cmd, capture_output, text, timeout):
            return type("Result", (), {"stdout": source, "returncode": 0})()

    runtime = orchestrate.orch_case_runtime.script_runtime_context(
        udid="a1",
        subprocess_module=FakeSubprocess,
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        tap_with_locator_fn=lambda udid, step, source: True,
        adb_input_text_fn=lambda udid, text: True,
        tap_by_text_fn=lambda udid, text: False,
        run_flow_fn=lambda meta, flow, runtime: {"passed": True},
        known_dialog_text_actions=(),
    )
    original_adb_tap = orchestrate.orch_case_runtime.adb_tap
    try:
        orchestrate.orch_case_runtime.adb_tap = lambda udid, x, y, subprocess_module: taps.append((x, y)) or True
        assert runtime["dismiss_system_alert"]({}) is True
    finally:
        orchestrate.orch_case_runtime.adb_tap = original_adb_tap
    assert taps == [(60, 120)]


def test_resolve_latest_local_artifact_prefers_newest(tmp_path, monkeypatch):
    older = tmp_path / "gaotu_5.91.90.apk"
    newer = tmp_path / "gaotu_5.91.93.apk"
    older.write_text("old")
    newer.write_text("new")

    monkeypatch.setattr(orchestrate.glob, "glob", lambda pattern: [str(older), str(newer)])
    monkeypatch.setattr(orchestrate.os.path, "getmtime", lambda path: 1 if path == str(older) else 2)

    assert orchestrate._resolve_latest_local_artifact("gaotu", "android") == str(newer)


def test_reinstall_app_for_script_uses_android_installer(tmp_path, monkeypatch):
    apk = tmp_path / "gaotu_5.91.93.apk"
    apk.write_text("apk")
    closed = []
    invalidated = []

    monkeypatch.setattr(orchestrate, "_resolve_local_artifact_for_script", lambda app_id, platform, version='': str(apk))
    monkeypatch.setattr(orchestrate, "install_android", lambda path, udid: path == str(apk) and udid == "a1")
    monkeypatch.setattr(orchestrate, "_launch_app_after_reinstall_for_script", lambda app_id, platform, udid, ctx: True)

    ok = orchestrate._reinstall_app_for_script(
        "gaotu",
        "android",
        "a1",
        {
            "script_meta": {"app_version": "5.91.93"},
            "close": lambda: closed.append(True) or True,
            "invalidate_state": lambda: invalidated.append(True) or True,
        },
    )

    assert ok is True
    assert closed == [True]
    assert invalidated == [True]


def test_reinstall_app_for_script_uses_ios_installer(tmp_path, monkeypatch):
    ipa = tmp_path / "gaotu_5.91.93.ipa"
    ipa.write_text("ipa")
    closed = []
    invalidated = []
    install_calls = []
    launch_calls = []

    monkeypatch.setattr(orchestrate, "_resolve_local_artifact_for_script", lambda app_id, platform, version='': str(ipa))
    monkeypatch.setattr(
        orchestrate,
        "install_ios",
        lambda path, udid: install_calls.append((path, udid)) or (path == str(ipa) and udid == "i1"),
    )
    monkeypatch.setattr(
        orchestrate,
        "_launch_app_after_reinstall_for_script",
        lambda app_id, platform, udid, ctx: launch_calls.append((app_id, platform, udid)) or True,
    )
    monkeypatch.setattr(orchestrate.ios_wda, "ensure_wda_ready", lambda *args, **kwargs: True)

    ok = orchestrate._reinstall_app_for_script(
        "gaotu",
        "ios",
        "i1",
        {
            "script_meta": {"app_version": "5.91.93"},
            "close": lambda: closed.append(True) or True,
            "invalidate_state": lambda: invalidated.append(True) or True,
        },
    )

    assert ok is True
    assert install_calls == [(str(ipa), "i1")]
    assert launch_calls == []
    assert closed == [True]
    assert invalidated == [True]


def test_resolve_local_artifact_for_script_prefers_exact_version(tmp_path):
    original_exists = orchestrate.os.path.exists
    try:
        orchestrate.os.path.exists = lambda path: path == "/tmp/gaotu_5.91.93.apk" or original_exists(path)
        assert orchestrate._resolve_local_artifact_for_script("gaotu", "android", "5.91.93") == "/tmp/gaotu_5.91.93.apk"
    finally:
        orchestrate.os.path.exists = original_exists


def test_artifact_version_from_path_extracts_version():
    assert orchestrate._artifact_version_from_path("/tmp/gaotu_5.91.93.apk") == "5.91.93"
    assert orchestrate._artifact_version_from_path("/tmp/gaotu_5.91.93.ipa") == "5.91.93"
    assert orchestrate._artifact_version_from_path("/tmp/invalid-name.apk") == ""


def test_launch_app_after_reinstall_for_script_android_waits_and_invalidates(monkeypatch):
    invalidated = []
    route_calls = []
    sleep_calls = []

    monkeypatch.setattr(orchestrate, "_resolve_android_launch_component",
                        lambda udid, package_name: "com.gaotu100.superclass/.ui.activity.SplashActivity")
    monkeypatch.setattr(orchestrate.orch_case_runtime, "adb_route",
                        lambda udid, step, subprocess_module: route_calls.append((udid, step["value"])) or True)
    monkeypatch.setattr(orchestrate.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    ok = orchestrate._launch_app_after_reinstall_for_script(
        "gaotu",
        "android",
        "a1",
        {"script_meta": {"bundle_id": "com.gaotu100.superclass"}, "invalidate_state": lambda: invalidated.append(True) or True},
    )

    assert ok is True
    assert route_calls == [("a1", "com.gaotu100.superclass/.ui.activity.SplashActivity")]
    assert sleep_calls == [4]
    assert invalidated == [True]


@patch("orchestrate.subprocess.run")
def test_launch_app_after_reinstall_for_script_ios_ensures_network_and_launches(mock_run, monkeypatch):
    invalidated = []
    sleep_calls = []
    ensures = []
    mock_run.return_value.returncode = 0

    monkeypatch.setattr(orchestrate, "_resolve_ios_device_wda_config",
                        lambda app_id, udid: {"port": 8101})
    monkeypatch.setattr(orchestrate, "ensure_ios_network_permission_ready",
                        lambda app_id, udid, bundle_id, port: ensures.append((app_id, udid, bundle_id, port)) or True)
    monkeypatch.setattr(orchestrate.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    ok = orchestrate._launch_app_after_reinstall_for_script(
        "gaotu",
        "ios",
        "i1",
        {"script_meta": {"bundle_id": "com.gaotu100.superclass"}, "invalidate_state": lambda: invalidated.append(True) or True},
    )

    assert ok is True
    assert ensures == [("gaotu", "i1", "com.gaotu100.superclass", 8101)]
    assert mock_run.call_args[0][0] == [
        sys.executable, "-m", "tidevice", "-u", "i1", "launch", "com.gaotu100.superclass"
    ]
    assert sleep_calls == [4]
    assert invalidated == [True]


def test_grant_ios_network_permission_skips_when_no_command_configured(monkeypatch):
    calls = []
    monkeypatch.delenv("ORCH_IOS_NETWORK_PERMISSION_CMD", raising=False)
    monkeypatch.setattr(orchestrate.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert orchestrate.grant_ios_network_permission("i1", "com.gaotu100.superclass") is True
    assert calls == []


def test_prepare_ios_network_permission_accepts_wireless_alert(monkeypatch):
    ios = orchestrate.orch_case_runtime_ios
    alerts = ['允许"高途"使用无线数据？\n关闭无线数据时…', ""]
    accepts = []
    stopped = []

    monkeypatch.setattr(orchestrate, "grant_ios_network_permission", lambda udid, bundle_id: True)
    monkeypatch.setattr(ios, "_create_session", lambda port, bundle_id: "sid")
    monkeypatch.setattr(ios, "_alert_text", lambda port, sid: alerts.pop(0) if alerts else "")
    monkeypatch.setattr(ios, "_accept_alert", lambda port, sid, name=None: accepts.append(name) or True)
    monkeypatch.setattr(ios, "_delete_session", lambda port, sid: True)
    monkeypatch.setattr(orchestrate, "_stop_ios_app", lambda udid, bundle_id: stopped.append((udid, bundle_id)) or True)

    assert orchestrate.prepare_ios_network_permission(
        "i1", "com.gaotu100.superclass", 8100, timeout=0.1, interval=0
    ) is True
    assert accepts == ["无线局域网与蜂窝网络"]
    assert stopped == [("i1", "com.gaotu100.superclass")]


def test_grant_ios_network_permission_in_settings_taps_app_wireless_data_path(monkeypatch):
    ios = orchestrate.orch_case_runtime_ios
    sources = iter(["设置", "App 列表 高途", "高途 无线数据", "无线局域网与蜂窝数据"])
    taps = []
    stopped = []

    monkeypatch.setattr(ios, "_create_session", lambda port, bundle_id: "settings-sid")
    monkeypatch.setattr(ios, "_get_source", lambda port, sid: next(sources))
    monkeypatch.setattr(orchestrate, "_ios_wda_scroll_down", lambda port, sid: True)
    monkeypatch.setattr(ios, "_find_element", lambda port, sid, by, value: f"el-{value}")
    monkeypatch.setattr(ios, "_click_element", lambda port, sid, element_id: taps.append(element_id[3:]) or True)
    monkeypatch.setattr(ios, "_delete_session", lambda port, sid: True)
    monkeypatch.setattr(orchestrate, "_stop_ios_app", lambda udid, bundle_id: stopped.append((udid, bundle_id)) or True)

    assert orchestrate.grant_ios_network_permission_in_settings("i1", "高途", 8100) is True
    assert taps == ["App", "高途", "无线数据", "无线局域网与蜂窝数据"]
    assert stopped == [("i1", "com.apple.Preferences")]


def test_create_ios_session_resilient_recovers_after_transient_failure(monkeypatch):
    # 8100 首次建 session 空(WDA 刚重启未 settle) → ensure_wda_ready 自愈 → 重试成功。
    ios = orchestrate.orch_case_runtime_ios
    results = iter(["", "sid-2"])
    recovered = []

    monkeypatch.setattr(ios, "_create_session", lambda port, bundle_id: next(results))
    monkeypatch.setattr(orchestrate.time, "sleep", lambda *_: None)

    session_id = orchestrate._create_ios_session_resilient(
        8100, "com.gaotu100.superclass",
        wda_recover=lambda: recovered.append(True) or True,
    )
    assert session_id == "sid-2"
    assert recovered == [True]  # 失败一次后自愈一次


def test_create_ios_session_resilient_returns_empty_after_all_attempts(monkeypatch):
    ios = orchestrate.orch_case_runtime_ios
    recovered = []

    monkeypatch.setattr(ios, "_create_session", lambda port, bundle_id: "")
    monkeypatch.setattr(orchestrate.time, "sleep", lambda *_: None)

    session_id = orchestrate._create_ios_session_resilient(
        8100, "com.apple.Preferences",
        wda_recover=lambda: recovered.append(True) or True,
        attempts=3,
    )
    assert session_id == ""
    assert recovered == [True, True]  # attempts=3 → 失败重试之间自愈 2 次,最后一次不再自愈


def test_create_ios_session_resilient_no_recover_when_first_attempt_ok(monkeypatch):
    ios = orchestrate.orch_case_runtime_ios
    recovered = []

    monkeypatch.setattr(ios, "_create_session", lambda port, bundle_id: "sid-1")

    session_id = orchestrate._create_ios_session_resilient(
        8100, "com.gaotu100.superclass",
        wda_recover=lambda: recovered.append(True) or True,
    )
    assert session_id == "sid-1"
    assert recovered == []  # 首次即成功,健康路径零自愈开销


def test_create_ios_session_resilient_swallows_recover_exception(monkeypatch):
    ios = orchestrate.orch_case_runtime_ios
    results = iter(["", "sid-2"])

    monkeypatch.setattr(ios, "_create_session", lambda port, bundle_id: next(results))
    monkeypatch.setattr(orchestrate.time, "sleep", lambda *_: None)

    def boom():
        raise RuntimeError("wda restart failed")

    # 自愈回调抛异常不应中断重试。
    session_id = orchestrate._create_ios_session_resilient(
        8100, "com.gaotu100.superclass", wda_recover=boom,
    )
    assert session_id == "sid-2"


def test_ensure_ios_network_permission_ready_threads_wda_recover(monkeypatch):
    # ensure_ios_network_permission_ready 须把可自愈的 wda_recover 传给 settings/prepare。
    seen = {}

    monkeypatch.setattr(
        orchestrate, "_resolve_ios_device_wda_config",
        lambda app_id, udid: {"team": "T", "bundle_id": "wda.b", "port": 8100},
    )
    monkeypatch.setattr(
        orchestrate, "grant_ios_network_permission_in_settings",
        lambda udid, app_name, port, wda_recover=None: seen.__setitem__("grant", wda_recover) or True,
    )
    monkeypatch.setattr(
        orchestrate, "prepare_ios_network_permission",
        lambda udid, bundle_id, port, wda_recover=None: seen.__setitem__("prepare", wda_recover) or True,
    )

    assert orchestrate.ensure_ios_network_permission_ready(
        "gaotu", "i1", "com.gaotu100.superclass", 8100
    ) is True
    assert callable(seen["grant"])
    assert callable(seen["prepare"])
    assert seen["grant"] is seen["prepare"]


def test_ensure_ios_network_permission_ready_grants_via_settings_first(monkeypatch):
    # 主动进设置授权:先跑设置授权,再做弹窗预热,不再依赖首启弹窗是否在窗口内出现。
    calls = []

    monkeypatch.setattr(
        orchestrate,
        "grant_ios_network_permission_in_settings",
        lambda udid, app_name, port, wda_recover=None: calls.append(("settings", udid, app_name, port)) or True,
    )
    monkeypatch.setattr(
        orchestrate,
        "prepare_ios_network_permission",
        lambda udid, bundle_id, port, wda_recover=None: calls.append(("prepare", udid, bundle_id, port)) or True,
    )

    assert orchestrate.ensure_ios_network_permission_ready(
        "gaotu", "i1", "com.gaotu100.superclass", 8100
    ) is True
    assert calls == [
        ("settings", "i1", "高途", 8100),
        ("prepare", "i1", "com.gaotu100.superclass", 8100),
    ]


def test_ensure_ios_network_permission_ready_prewarms_even_if_settings_fails(monkeypatch):
    # 设置授权没找到入口(失败)也不硬失败:仍做弹窗预热,设备可用性以 prepare 结果为准。
    calls = []

    monkeypatch.setattr(
        orchestrate,
        "grant_ios_network_permission_in_settings",
        lambda udid, app_name, port, wda_recover=None: calls.append("settings") or False,
    )
    monkeypatch.setattr(
        orchestrate,
        "prepare_ios_network_permission",
        lambda udid, bundle_id, port, wda_recover=None: calls.append("prepare") or True,
    )

    assert orchestrate.ensure_ios_network_permission_ready(
        "gaotu", "i1", "com.gaotu100.superclass", 8100
    ) is True
    assert calls == ["settings", "prepare"]


def test_ensure_ios_network_permission_ready_skips_device_when_prewarm_fails(monkeypatch):
    # prepare 建 session 失败 → 返回 False → 上层 _run 跳过该 iOS 设备。
    monkeypatch.setattr(
        orchestrate,
        "grant_ios_network_permission_in_settings",
        lambda udid, app_name, port, wda_recover=None: True,
    )
    monkeypatch.setattr(
        orchestrate,
        "prepare_ios_network_permission",
        lambda udid, bundle_id, port, wda_recover=None: False,
    )

    assert orchestrate.ensure_ios_network_permission_ready(
        "gaotu", "i1", "com.gaotu100.superclass", 8100
    ) is False


def test_ios_script_runtime_route_creates_session(monkeypatch):
    created = []

    monkeypatch.setattr(
        orchestrate.orch_case_runtime_ios,
        "_create_session",
        lambda port, bundle_id: created.append((port, bundle_id)) or "sid1",
    )

    runtime = orchestrate.orch_case_runtime_ios.script_runtime_context(
        "i1",
        8100,
        "com.gaotu100.superclass",
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        run_flow_fn=orchestrate._run_flow,
        known_dialog_text_actions=(),
    )

    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "启动"},
        [{"type": "route", "value": "com.gaotu100.superclass"}],
        runtime,
    )

    assert result["passed"] is True
    assert created == [(8100, "com.gaotu100.superclass")]


def test_ios_script_runtime_tap_recovers_transport_and_retries(monkeypatch):
    created = []
    recovered = []

    def fake_create_session(port, bundle_id):
        created.append((port, bundle_id))
        return "" if len(created) == 1 else "sid2"

    monkeypatch.setattr(orchestrate.orch_case_runtime_ios.time, "sleep", lambda _: None)
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_create_session", fake_create_session)
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_get_source", lambda port, session_id: "<App/>")
    monkeypatch.setattr(
        orchestrate.orch_case_runtime_ios,
        "_tap_with_locator",
        lambda port, session_id, step: session_id == "sid2",
    )

    runtime = orchestrate.orch_case_runtime_ios.script_runtime_context(
        "i1",
        8100,
        "com.gaotu100.superclass",
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        run_flow_fn=orchestrate._run_flow,
        known_dialog_text_actions=(),
        recover_transport_fn=lambda: recovered.append(True) or True,
    )

    assert runtime["tap"]({"by": "accessibility_id", "value": "未满14岁"}) is True
    assert created == [
        (8100, "com.gaotu100.superclass"),
        (8100, "com.gaotu100.superclass"),
    ]
    assert recovered == [True]


def test_assert_evidence_present_splits_compound_text_evidence():
    runtime = orchestrate._script_runtime_context("a1")
    runtime["read_page_source"] = lambda force_refresh=False: "温馨提示 同意 隐私政策"

    assert orchestrate._assert_evidence_present(runtime, "text", "实际标题：温馨提示；按钮：同意；文案含隐私政策") is True


def test_assert_evidence_present_requires_all_compound_tokens():
    runtime = orchestrate._script_runtime_context("a1")
    runtime["read_page_source"] = lambda force_refresh=False: "温馨提示 同意"

    assert orchestrate._assert_evidence_present(runtime, "text", "实际标题：温馨提示；按钮：同意；文案含隐私政策") is False


def test_assert_evidence_detail_reports_missing_tokens():
    runtime = orchestrate._script_runtime_context("a1")
    runtime["read_page_source"] = lambda force_refresh=False: "温馨提示 同意"

    detail = orchestrate._assert_evidence_detail(runtime, "text", "实际标题：温馨提示；按钮：同意；文案含隐私政策")

    assert detail["matched"] == ["温馨提示", "同意"]
    assert detail["missing"] == ["隐私政策"]


def test_assert_evidence_detail_uses_exact_resource_id_matching():
    runtime = orchestrate._script_runtime_context("a1")
    runtime["read_page_source"] = lambda force_refresh=False: (
        '<node resource-id="com.gaotu100.superclass:id/tvMessage" />'
        '<node resource-id="com.gaotu100.superclass:id/tvCancel" />'
        '<node resource-id="com.gaotu100.superclass:id/tvConfirm" />'
    )

    detail = orchestrate._assert_evidence_detail(
        runtime,
        "id",
        "com.gaotu100.superclass:id/tvTitle|tvMessage|tvCancel|tvConfirm",
    )

    assert detail["matched"] == [
        "com.gaotu100.superclass:id/tvMessage",
        "com.gaotu100.superclass:id/tvCancel",
        "com.gaotu100.superclass:id/tvConfirm",
    ]
    assert detail["missing"] == ["com.gaotu100.superclass:id/tvTitle"]


def test_assert_evidence_detail_expands_compound_id_suffixes():
    expanded = orchestrate._expand_compound_id_tokens(
        ["com.gaotu100.superclass:id/tvTitle|tvMessage|tvCancel|tvConfirm"]
    )

    assert expanded == [
        "com.gaotu100.superclass:id/tvTitle",
        "com.gaotu100.superclass:id/tvMessage",
        "com.gaotu100.superclass:id/tvCancel",
        "com.gaotu100.superclass:id/tvConfirm",
    ]


def test_normalize_evidence_token_strips_generic_prefixes():
    assert orchestrate._normalize_evidence_token("文案：高途用户服务协议") == "高途用户服务协议"
    assert orchestrate._normalize_evidence_token("提示：温馨提示") == "温馨提示"
    assert orchestrate._normalize_evidence_token("按钮：同意") == "同意"
    assert orchestrate._normalize_evidence_token("标题：青少年守护") == "青少年守护"


def test_run_flow_includes_assert_token_detail_in_failure_note():
    runtime = {
        "assert_evidence_present": lambda method, evidence: False,
        "assert_evidence_detail": lambda method, evidence: {
            "matched": ["简单浏览模式", "同意"],
            "missing": ["儿童隐私保护声明"],
        },
    }

    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "首页"},
        [{"type": "assert_text", "value": "按钮文本：简单浏览模式 / 同意；协议链接文案：儿童隐私保护声明", "text": "复合断言"}],
        runtime,
    )

    assert result["passed"] is False
    assert "missing=['儿童隐私保护声明']" in result["note"]
    assert "matched=['简单浏览模式', '同意']" in result["steps"][0]["note"]


def test_run_flow_assert_id_uses_aux_text_as_advisory_check():
    runtime = {
        "assert_evidence_present": lambda method, evidence: method == "id" and evidence == "dialog_left_button",
        "assert_evidence_detail": lambda method, evidence: (
            {"matched": ["dialog_left_button"], "missing": []}
            if method == "id"
            else {"matched": ["同意"], "missing": ["简单浏览模式"]}
        ),
    }

    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "首页"},
        [{
            "type": "assert_id",
            "value": "dialog_left_button",
            "aux_text": "按钮：简单浏览模式 / 同意",
            "text": "弹窗按钮可见",
        }],
        runtime,
    )

    assert result["passed"] is True
    assert "aux_missing=['简单浏览模式']" in result["steps"][0]["note"]
    assert "aux_matched=['同意']" in result["steps"][0]["note"]


def test_assert_id_accepts_id_text_contains_evidence():
    runtime = {
        "read_page_source": lambda force_refresh=False: (
            'resource-id="com.gaotu100.superclass:id/tvMessage" '
            "text='感谢您下载并使用高途！'"
        ),
    }

    detail = orchestrate._assert_evidence_detail(
        runtime,
        "id",
        "tvMessage text 含 '感谢您下载并使用高途！'",
    )

    assert detail["passed"] is True
    assert detail["matched"] == [":id/tvMessage", "感谢您下载并使用高途！"]


def test_assert_id_accepts_id_label_evidence():
    runtime = {
        "read_page_source": lambda force_refresh=False: (
            'resource-id="com.gaotu100.superclass:id/tvConfirm" text="同意" '
            'resource-id="com.gaotu100.superclass:id/tvCancel" text="不同意"'
        ),
    }

    detail = orchestrate._assert_evidence_detail(
        runtime,
        "id",
        "tvConfirm(同意) / tvCancel(不同意)",
    )

    assert detail["passed"] is True
    assert detail["matched"] == [":id/tvConfirm", "同意", ":id/tvCancel", "不同意"]


def test_assert_id_accepts_clickable_span_text_evidence():
    runtime = {
        "read_page_source": lambda force_refresh=False: (
            'resource-id="com.gaotu100.superclass:id/tvMessage" '
            "《高途用户服务协议》《高途隐私政策》《儿童隐私保护声明》"
        ),
    }

    detail = orchestrate._assert_evidence_detail(
        runtime,
        "id",
        "tvMessage text-has-clickable-span=true,含《高途用户服务协议》《高途隐私政策》《儿童隐私保护声明》",
    )

    assert detail["passed"] is True
    assert detail["matched"] == [
        ":id/tvMessage",
        "高途用户服务协议",
        "高途隐私政策",
        "儿童隐私保护声明",
    ]


def test_assert_id_accepts_id_text_equals_evidence():
    runtime = {
        "read_page_source": lambda force_refresh=False: (
            'resource-id="com.gaotu100.superclass:id/tvTitle" text="青少年守护"'
        ),
    }

    detail = orchestrate._assert_evidence_detail(runtime, "id", "tvTitle text='青少年守护'")

    assert detail["passed"] is True
    assert detail["matched"] == [":id/tvTitle", "青少年守护"]


def test_assert_id_accepts_semicolon_full_resource_ids():
    runtime = {
        "read_page_source": lambda force_refresh=False: (
            'resource-id="com.gaotu100.superclass:id/account_enter_et" '
            'resource-id="com.gaotu100.superclass:id/account_sign_btn"'
        ),
    }

    detail = orchestrate._assert_evidence_detail(
        runtime,
        "id",
        "com.gaotu100.superclass:id/account_enter_et; "
        "com.gaotu100.superclass:id/account_sign_btn; /tmp/gaotu_final2.xml",
    )

    assert detail["passed"] is True
    assert detail["matched"] == [
        "com.gaotu100.superclass:id/account_enter_et",
        "com.gaotu100.superclass:id/account_sign_btn",
    ]


def test_tap_with_locator_supports_coordinate(monkeypatch):
    taps = []
    monkeypatch.setattr(orchestrate, "_adb_tap", lambda udid, x, y: taps.append((udid, x, y)) or True)

    assert orchestrate._tap_with_locator("a1", {"by": "coordinate", "value": "612,2630"}, "") is True
    assert taps == [("a1", 612, 2630)]


def test_runtime_route_component_normalizes_activity_prefix():
    component = orchestrate.orch_case_runtime.resolve_route_component(
        "a1",
        {"value": "activity=com.gaotu100.superclass/.ui.activity.SplashActivity"},
        subprocess_module=orchestrate.subprocess,
    )

    assert component == "com.gaotu100.superclass/.ui.activity.SplashActivity"


def test_run_flow_polls_assertion_until_page_stabilizes(monkeypatch):
    page_sources = [
        '<node resource-id="com.gaotu100.superclass:id/tvMessage" />',
        '<node resource-id="com.gaotu100.superclass:id/tvTitle" />'
        '<node resource-id="com.gaotu100.superclass:id/tvMessage" />'
        '<node resource-id="com.gaotu100.superclass:id/tvCancel" />'
        '<node resource-id="com.gaotu100.superclass:id/tvConfirm" />温馨提示',
    ]
    state = {"index": 0}
    runtime = orchestrate._script_runtime_context("a1")
    def _read_page_source(force_refresh=False):
        idx = min(state["index"], len(page_sources) - 1)
        value = page_sources[idx]
        if force_refresh and state["index"] < len(page_sources) - 1:
            state["index"] += 1
        return value
    runtime["read_page_source"] = _read_page_source
    runtime["assert_evidence_present"] = lambda method, evidence: orchestrate._assert_evidence_present(runtime, method, evidence)
    runtime["assert_evidence_detail"] = lambda method, evidence: orchestrate._assert_evidence_detail(runtime, method, evidence)
    monkeypatch.setattr(orchestrate.orch_case_runtime.time, "sleep", lambda _: None)

    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "首页"},
        [{
            "type": "assert_id",
            "value": "com.gaotu100.superclass:id/tvTitle|tvMessage|tvCancel|tvConfirm",
            "aux_text": "温馨提示",
            "text": "温馨提示弹窗出现",
        }],
        runtime,
    )

    assert result["passed"] is True


def test_run_flow_assertion_handles_known_dialogs_before_final_judgement(monkeypatch):
    calls = []
    runtime = {
        "handle_known_dialogs": lambda step: calls.append("handle") or True,
        "read_page_source": lambda force_refresh=False: calls.append("read") or "",
        "assert_evidence_present": lambda method, evidence: calls.append(("assert", method, evidence)) or True,
        "assert_evidence_detail": lambda method, evidence: {"matched": [evidence], "missing": []},
    }
    monkeypatch.setattr(orchestrate.orch_case_runtime.time, "sleep", lambda _: None)

    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "首页"},
        [{"type": "assert_id", "value": "home_anchor", "text": "首页出现"}],
        runtime,
    )

    assert result["passed"] is True
    assert calls[:3] == ["handle", "read", ("assert", "id", "home_anchor")]


def _counting_assert_runtime():
    """runtime，断言恒失败并统计断言尝试次数，用于验证轮询预算。"""
    calls = {"n": 0}

    def _present(method, evidence):
        calls["n"] += 1
        return False

    runtime = {
        "reinstall_app": lambda step: True,
        "route": lambda step: True,
        "tap": lambda step: True,
        "read_page_source": lambda force_refresh=False: "",
        "handle_known_dialogs": lambda step: True,
        "assert_evidence_present": _present,
        "assert_evidence_detail": lambda method, evidence: {"matched": [], "missing": [evidence]},
    }
    return runtime, calls


def test_run_flow_first_launch_assert_gets_longer_poll_budget(monkeypatch):
    # reinstall_app 之后的首个断言(首启协议/隐私弹窗)应用加长轮询预算,覆盖冷启渲染。
    monkeypatch.setattr(orchestrate.orch_case_runtime.time, "sleep", lambda _: None)
    runtime, calls = _counting_assert_runtime()
    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "启动登录"},
        [{"type": "reinstall_app"},
         {"type": "assert_id", "value": "privacy_anchor", "text": "隐私弹窗"}],
        runtime,
    )
    assert result["passed"] is False
    assert calls["n"] == orchestrate.orch_case_runtime.FIRST_LAUNCH_POLL_ATTEMPTS


def test_run_flow_assert_after_tap_uses_default_poll_budget(monkeypatch):
    # 一旦发生交互(tap),就不再是首启态,断言回落到默认轮询预算。
    monkeypatch.setattr(orchestrate.orch_case_runtime.time, "sleep", lambda _: None)
    runtime, calls = _counting_assert_runtime()
    result = orchestrate._run_flow(
        {"record_id": "rec1", "name": "case", "module": "启动登录"},
        [{"type": "reinstall_app"},
         {"type": "tap", "by": "id", "value": "x"},
         {"type": "assert_id", "value": "anchor", "text": "断言"}],
        runtime,
    )
    assert result["passed"] is False
    assert calls["n"] == orchestrate.orch_case_runtime.ASSERT_POLL_ATTEMPTS


def test_xctestrun_path_prefers_pinned_over_default_derived(tmp_path, monkeypatch):
    ios_wda = orchestrate.ios_wda
    pinned_root = tmp_path / "pinned"
    default_dd = tmp_path / "DerivedData"
    # 固定路径产物
    pinned_products = pinned_root / "u1" / "Build" / "Products"
    pinned_products.mkdir(parents=True)
    (pinned_products / "WDA.xctestrun").write_text("x")
    # 默认 DerivedData 产物
    dd_products = default_dd / "WebDriverAgent-abc" / "Build" / "Products"
    dd_products.mkdir(parents=True)
    (dd_products / "WDA.xctestrun").write_text("y")
    monkeypatch.setattr(ios_wda, "DERIVED_DATA_ROOT", str(pinned_root))
    monkeypatch.setattr(ios_wda, "DEFAULT_DERIVED_DATA", str(default_dd))
    assert ios_wda._xctestrun_path("u1") == str(pinned_products / "WDA.xctestrun")


def test_xctestrun_path_falls_back_to_default_derived(tmp_path, monkeypatch):
    ios_wda = orchestrate.ios_wda
    pinned_root = tmp_path / "pinned"  # 不建产物 → 固定路径为空
    default_dd = tmp_path / "DerivedData"
    dd_products = default_dd / "WebDriverAgent-abc" / "Build" / "Products"
    dd_products.mkdir(parents=True)
    expected = dd_products / "WDA.xctestrun"
    expected.write_text("y")
    monkeypatch.setattr(ios_wda, "DERIVED_DATA_ROOT", str(pinned_root))
    monkeypatch.setattr(ios_wda, "DEFAULT_DERIVED_DATA", str(default_dd))
    # 有默认产物就复用,不该触发全量构建(返回非空)
    assert ios_wda._xctestrun_path("u1") == str(expected)


def test_xctestrun_path_empty_when_nothing_built(tmp_path, monkeypatch):
    ios_wda = orchestrate.ios_wda
    monkeypatch.setattr(ios_wda, "DERIVED_DATA_ROOT", str(tmp_path / "pinned"))
    monkeypatch.setattr(ios_wda, "DEFAULT_DERIVED_DATA", str(tmp_path / "DerivedData"))
    assert ios_wda._xctestrun_path("u1") == ""


def test_device_wda_port_reads_use_port_from_xctestrun(tmp_path):
    import plistlib
    ios_wda = orchestrate.ios_wda
    xctr = tmp_path / "WDA.xctestrun"
    with open(xctr, "wb") as f:
        plistlib.dump({"WebDriverAgentRunner": {
            "EnvironmentVariables": {"USE_PORT": "8102"}}}, f)
    assert ios_wda._device_wda_port(str(xctr)) == 8102


def test_device_wda_port_defaults_when_missing(tmp_path):
    import plistlib
    ios_wda = orchestrate.ios_wda
    xctr = tmp_path / "WDA.xctestrun"
    with open(xctr, "wb") as f:
        plistlib.dump({"WebDriverAgentRunner": {"EnvironmentVariables": {}}}, f)
    assert ios_wda._device_wda_port(str(xctr), default=8100) == 8100
    # 文件不存在也回退 default
    assert ios_wda._device_wda_port("/no/such.xctestrun", default=8100) == 8100


def test_ensure_wda_ready_passes_device_port_to_proxy(monkeypatch):
    ios_wda = orchestrate.ios_wda
    hc = {"n": 0}
    monkeypatch.setattr(ios_wda, "health_check", lambda port: hc.__setitem__("n", hc["n"] + 1) or hc["n"] > 1)
    monkeypatch.setattr(ios_wda, "tunnel_ready", lambda udid: True)
    monkeypatch.setattr(ios_wda, "wda_running", lambda udid: True)  # 已在跑,不重启
    monkeypatch.setattr(ios_wda, "_xctestrun_path", lambda udid: "/x/y.xctestrun")
    monkeypatch.setattr(ios_wda, "_device_wda_port", lambda xctr, default=8100: 8102)
    monkeypatch.setattr(ios_wda, "proxy_listening", lambda port: False)
    monkeypatch.setattr(ios_wda.time, "sleep", lambda _: None)
    got = {}
    monkeypatch.setattr(ios_wda, "_start_proxy",
                        lambda udid, port, device_port=8100: got.update(device_port=device_port))
    ok = ios_wda.ensure_wda_ready("u1", "T", "b", 8100, timeout=10)
    assert ok is True
    assert got["device_port"] == 8102


def test_ios_wda_start_full_build_when_no_product(monkeypatch):
    ios_wda = orchestrate.ios_wda
    monkeypatch.setattr(ios_wda, "_xctestrun_path", lambda udid: "")
    captured = []
    monkeypatch.setattr(ios_wda.subprocess, "Popen", lambda cmd, **kw: captured.append(cmd))
    ios_wda._start_wda("u1", "TEAMX", "com.b.wda", rebuild=True)
    assert captured[0][:2] == ["xcodebuild", "test"]
    assert "-derivedDataPath" in captured[0]
    assert "DEVELOPMENT_TEAM=TEAMX" in captured[0]


def test_ios_wda_relaunch_without_rebuild_when_product_exists(monkeypatch):
    ios_wda = orchestrate.ios_wda
    monkeypatch.setattr(ios_wda, "_xctestrun_path",
                        lambda udid: "/tmp/wda_derived/u1/Build/Products/x.xctestrun")
    captured = []
    monkeypatch.setattr(ios_wda.subprocess, "Popen", lambda cmd, **kw: captured.append(cmd))
    ios_wda._start_wda("u1", "TEAMX", "com.b.wda", rebuild=False)
    assert captured[0][:2] == ["xcodebuild", "test-without-building"]
    assert "-xctestrun" in captured[0]
    # 复用产物不得重新签名(否则免费证书信任又失效)
    assert "-allowProvisioningUpdates" not in captured[0]
    assert not any(str(a).startswith("DEVELOPMENT_TEAM=") for a in captured[0])


def test_ensure_wda_ready_relaunches_without_rebuild_when_product_exists(monkeypatch):
    ios_wda = orchestrate.ios_wda
    hc = {"n": 0}

    def _health(port):
        hc["n"] += 1
        return hc["n"] > 1  # 首次探测未就绪,启动后就绪

    monkeypatch.setattr(ios_wda, "health_check", _health)
    monkeypatch.setattr(ios_wda, "tunnel_ready", lambda udid: True)
    monkeypatch.setattr(ios_wda, "wda_running", lambda udid: False)
    monkeypatch.setattr(ios_wda, "_xctestrun_path", lambda udid: "/x/y.xctestrun")
    monkeypatch.setattr(ios_wda, "proxy_listening", lambda port: False)
    monkeypatch.setattr(ios_wda, "_start_proxy", lambda udid, port, device_port=8100: None)
    monkeypatch.setattr(ios_wda.time, "sleep", lambda _: None)
    started = {}
    monkeypatch.setattr(ios_wda, "_start_wda",
                        lambda udid, team, bundle_id, rebuild=True: started.update(rebuild=rebuild))
    ok = ios_wda.ensure_wda_ready("u1", "T", "b", 8100, timeout=10)
    assert ok is True
    assert started["rebuild"] is False


def test_ensure_wda_ready_full_build_when_no_product(monkeypatch):
    ios_wda = orchestrate.ios_wda
    hc = {"n": 0}

    def _health(port):
        hc["n"] += 1
        return hc["n"] > 1

    monkeypatch.setattr(ios_wda, "health_check", _health)
    monkeypatch.setattr(ios_wda, "tunnel_ready", lambda udid: True)
    monkeypatch.setattr(ios_wda, "wda_running", lambda udid: False)
    monkeypatch.setattr(ios_wda, "_xctestrun_path", lambda udid: "")
    monkeypatch.setattr(ios_wda, "proxy_listening", lambda port: False)
    monkeypatch.setattr(ios_wda, "_start_proxy", lambda udid, port, device_port=8100: None)
    monkeypatch.setattr(ios_wda.time, "sleep", lambda _: None)
    started = {}
    monkeypatch.setattr(ios_wda, "_start_wda",
                        lambda udid, team, bundle_id, rebuild=True: started.update(rebuild=rebuild))
    ok = ios_wda.ensure_wda_ready("u1", "T", "b", 8100, timeout=10)
    assert ok is True
    assert started["rebuild"] is True


def test_execute_case_with_fallback_prefers_existing_script(monkeypatch):
    entry = {"record_id": "rec1", "name": "case", "module": "首页", "steps": []}
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: False)
    monkeypatch.setattr(orchestrate, "find_case_script", lambda *args, **kwargs: "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: {"passed": True, "name": "case", "steps": [], "script_source": "script"})

    agent_called = []
    monkeypatch.setattr(orchestrate, "execute_case_via_agent",
                        lambda *args, **kwargs: agent_called.append(True))

    result = orchestrate.execute_case_with_fallback(
        app_id="gaotu",
        platform="android",
        udid="a1",
        entry=entry,
        version="5.91.90",
        current_account="12345679000",
        result_dir="/tmp",
    )

    assert result["passed"] is True
    assert result["script_source"] == "script"
    assert result["exec_source"] == "script"  # 脚本直接跑完,命中率分子
    assert agent_called == []


def test_execute_case_with_fallback_returns_failed_script_result_without_agent(monkeypatch):
    entry = {"record_id": "rec1", "name": "case", "module": "首页", "steps": []}
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: False)
    monkeypatch.setattr(orchestrate, "find_case_script", lambda *args, **kwargs: "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: {"passed": False, "note": "bad script", "steps": [], "script_source": "script"})

    monkeypatch.setattr(orchestrate, "generate_case_script",
                        lambda *args, **kwargs: pytest.fail("failed script result should not regenerate here"))
    monkeypatch.setattr(orchestrate, "execute_case_via_agent",
                        lambda *args, **kwargs: pytest.fail("failed script result should not fall back to agent"))

    result = orchestrate.execute_case_with_fallback(
        app_id="gaotu",
        platform="android",
        udid="a1",
        entry=entry,
        version="5.91.90",
        current_account="12345679000",
        result_dir="/tmp",
    )

    assert result["passed"] is False
    assert result["script_source"] == "script"
    assert result["note"] == "bad script"


def test_execute_case_with_fallback_falls_back_when_script_raises_and_regenerates(monkeypatch):
    entry = {"record_id": "rec1", "name": "case", "module": "首页", "steps": []}
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: False)
    monkeypatch.setattr(orchestrate, "find_case_script", lambda *args, **kwargs: "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("script crashed")))

    generated = []
    monkeypatch.setattr(orchestrate, "generate_case_script",
                        lambda *args, **kwargs: generated.append(True) or "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "execute_case_via_agent",
                        lambda *args, **kwargs: {"passed": True, "record_id": "rec1", "name": "case", "module": "首页", "platform": "Android", "device": "a1", "steps": []})

    result = orchestrate.execute_case_with_fallback(
        app_id="gaotu",
        platform="android",
        udid="a1",
        entry=entry,
        version="5.91.90",
        current_account="12345679000",
        result_dir="/tmp",
    )

    assert result["passed"] is True
    assert result["script_fallback"] is True
    assert result["script_error"] == "RuntimeError: script crashed"
    assert result["exec_source"] == "script_fallback"  # 有脚本但失效回退
    assert generated == [True]


@pytest.mark.parametrize("script_result,expected", [
    # 通过 → 非机制失败
    ({"passed": True, "steps": []}, False),
    # 无步骤明细的失败 → 保守视为真实失败(不回退)
    ({"passed": False, "note": "bad script", "steps": []}, False),
    # 动作步失败 → 机制类
    ({"passed": False, "note": "tap failed",
      "steps": [{"type": "TAP", "passed": False, "note": "tap failed"}]}, True),
    ({"passed": False, "note": "prepare_state failed",
      "steps": [{"type": "PREPARE_STATE", "passed": False, "note": "prepare_state failed"}]}, True),
    ({"passed": False, "note": "reinstall_app failed",
      "steps": [{"type": "REINSTALL_APP", "passed": False, "note": "reinstall_app failed"}]}, True),
    # 不支持步 → 机制类
    ({"passed": False, "note": "unsupported flow step: swipe",
      "steps": [{"type": "SWIPE", "passed": False, "note": "unsupported flow step: swipe"}]}, True),
    # 断言定位器全 miss(matched=[])→ 机制类(脚本失效)
    ({"passed": False, "note": "script assertion failed: 首页 | matched=[]; missing=['首页']",
      "steps": [{"type": "ASSERT", "passed": False, "note": "matched=[]; missing=['首页']"}]}, True),
    # 断言取到值但内容不匹配(matched 非空)→ 真实发现,不回退
    ({"passed": False, "note": "script assertion failed: 关注 | matched=['首页']; missing=['关注']",
      "steps": [{"type": "ASSERT", "passed": False, "note": "matched=['首页']; missing=['关注']"}]}, False),
    # 视觉断言判失败 → 真实 UI 发现,不回退
    ({"passed": False, "note": "assert_ui failed: 页面空白",
      "steps": [{"type": "ASSERT_UI", "passed": False, "note": "页面空白"}]}, False),
    # 先过动作步再断言全 miss → 取终态硬失败步(机制类)
    ({"passed": False, "note": "script assertion failed: x | matched=[]; missing=['x']",
      "steps": [
          {"type": "TAP", "passed": True, "note": ""},
          {"type": "ASSERT", "passed": False, "note": "matched=[]; missing=['x']"},
      ]}, True),
    # 仅 soft_assert 软失败(流程仍继续),终态无硬失败 → 非机制
    ({"passed": False, "note": "",
      "steps": [{"type": "ASSERT", "passed": False, "soft_assert": True,
                 "note": "matched=[]; missing=['toast']"}]}, False),
])
def test_is_script_mechanism_failure_classification(script_result, expected):
    assert orchestrate._is_script_mechanism_failure(script_result) is expected


def test_execute_case_with_fallback_mechanism_failure_falls_back_and_regenerates(monkeypatch):
    """脚本机制类失败(动作步 failed)→ 回退 agent;agent 通过则刷新脚本。"""
    entry = {"record_id": "rec1", "name": "case", "module": "首页", "steps": []}
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: False)
    monkeypatch.setattr(orchestrate, "find_case_script", lambda *args, **kwargs: "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: {"passed": False, "note": "tap failed",
                                                 "steps": [{"type": "TAP", "passed": False, "note": "tap failed"}],
                                                 "script_source": "script"})
    generated = []
    monkeypatch.setattr(orchestrate, "generate_case_script",
                        lambda *args, **kwargs: generated.append(True) or "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "execute_case_via_agent",
                        lambda *args, **kwargs: {"passed": True, "record_id": "rec1", "name": "case",
                                                 "module": "首页", "platform": "Android", "device": "a1", "steps": []})

    result = orchestrate.execute_case_with_fallback(
        app_id="gaotu", platform="android", udid="a1", entry=entry,
        version="5.91.90", current_account="12345679000", result_dir="/tmp",
    )

    assert result["passed"] is True
    assert result["script_fallback"] is True
    assert result["script_failure_note"] == "tap failed"
    assert "script_error" not in result
    assert generated == [True]


def test_execute_case_with_fallback_mechanism_failure_agent_also_fails_no_regenerate(monkeypatch):
    """脚本机制类失败回退 agent,agent 也失败 → 返回 agent 失败,不刷新脚本。"""
    entry = {"record_id": "rec1", "name": "case", "module": "首页", "steps": []}
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: False)
    monkeypatch.setattr(orchestrate, "find_case_script", lambda *args, **kwargs: "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: {"passed": False, "note": "prepare_state failed",
                                                 "steps": [{"type": "PREPARE_STATE", "passed": False, "note": "prepare_state failed"}],
                                                 "script_source": "script"})
    monkeypatch.setattr(orchestrate, "generate_case_script",
                        lambda *args, **kwargs: pytest.fail("agent 失败时不应刷新脚本"))
    monkeypatch.setattr(orchestrate, "execute_case_via_agent",
                        lambda *args, **kwargs: {"passed": False, "note": "agent failed too",
                                                 "record_id": "rec1", "steps": []})

    result = orchestrate.execute_case_with_fallback(
        app_id="gaotu", platform="android", udid="a1", entry=entry,
        version="5.91.90", current_account="12345679000", result_dir="/tmp",
    )

    assert result["passed"] is False
    assert result["script_fallback"] is True
    assert result["script_failure_note"] == "prepare_state failed"


def test_execute_case_with_fallback_real_assertion_failure_no_agent(monkeypatch):
    """脚本真实断言失败(取到值但内容不匹配)→ 直接返回失败,不回退 agent。"""
    entry = {"record_id": "rec1", "name": "case", "module": "首页", "steps": []}
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: False)
    monkeypatch.setattr(orchestrate, "find_case_script", lambda *args, **kwargs: "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: {"passed": False,
                                                 "note": "script assertion failed: 关注 | matched=['首页']; missing=['关注']",
                                                 "steps": [{"type": "ASSERT", "passed": False,
                                                            "note": "matched=['首页']; missing=['关注']"}],
                                                 "script_source": "script"})
    monkeypatch.setattr(orchestrate, "generate_case_script",
                        lambda *args, **kwargs: pytest.fail("真实断言失败不应刷新脚本"))
    monkeypatch.setattr(orchestrate, "execute_case_via_agent",
                        lambda *args, **kwargs: pytest.fail("真实断言失败不应回退 agent"))

    result = orchestrate.execute_case_with_fallback(
        app_id="gaotu", platform="android", udid="a1", entry=entry,
        version="5.91.90", current_account="12345679000", result_dir="/tmp",
    )

    assert result["passed"] is False
    assert result["script_source"] == "script"
    assert "script_fallback" not in result


def test_execute_case_with_fallback_script_result_keeps_order_and_state_group(monkeypatch):
    entry = {
        "record_id": "rec1",
        "name": "case",
        "module": "首页",
        "order": "A-02",
        "state_group": "login_flow",
        "steps": [],
    }
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: False)
    monkeypatch.setattr(orchestrate, "find_case_script", lambda *args, **kwargs: "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: {"passed": True, "steps": [], "script_source": "script"})
    monkeypatch.setattr(orchestrate, "execute_case_via_agent",
                        lambda *args, **kwargs: pytest.fail("should not fall back to agent"))

    result = orchestrate.execute_case_with_fallback(
        app_id="gaotu",
        platform="android",
        udid="a1",
        entry=entry,
        version="5.91.90",
        current_account="12345679000",
        result_dir="/tmp",
    )

    assert result["record_id"] == "rec1"
    assert result["order"] == "A-02"
    assert result["state_group"] == "login_flow"


def test_execute_case_with_fallback_ios_prefers_existing_script(monkeypatch):
    entry = {"record_id": "rec1", "name": "case", "module": "首页", "steps": []}
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: False)
    find_calls = []
    monkeypatch.setattr(orchestrate, "find_case_script",
                        lambda *args, **kwargs: find_calls.append(True) or "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: {"passed": True, "name": "case", "steps": [], "script_source": "script"})
    monkeypatch.setattr(orchestrate, "generate_case_script",
                        lambda *args, **kwargs: pytest.fail("existing iOS script should not regenerate"))
    monkeypatch.setattr(orchestrate, "execute_case_via_agent",
                        lambda *args, **kwargs: pytest.fail("should not fall back to agent"))

    result = orchestrate.execute_case_with_fallback(
        app_id="gaotu",
        platform="ios",
        udid="i1",
        entry=entry,
        version="5.91.90",
        current_account="12345679000",
        result_dir="/tmp",
    )

    assert result["passed"] is True
    assert result["script_source"] == "script"
    assert find_calls == [True]


def test_script_runtime_context_for_ios_ensures_network_and_uses_wda_port(monkeypatch):
    captured = {}
    monkeypatch.setattr(orchestrate, "_resolve_ios_device_wda_config", lambda app_id, udid: {"port": 8101})
    monkeypatch.setattr(orchestrate, "ensure_ios_network_permission_ready",
                        lambda app_id, udid, bundle_id, port: captured.setdefault("ensure", (app_id, udid, bundle_id, port)) or True)
    monkeypatch.setattr(
        orchestrate.orch_case_runtime_ios,
        "script_runtime_context",
        lambda **kwargs: (captured.setdefault("runtime", kwargs), {"run_flow": lambda *args, **kw: {"passed": True}})[1],
    )

    ctx = orchestrate._script_runtime_context_for("gaotu", "ios", "i1")

    assert "run_flow" in ctx
    assert captured["ensure"] == ("gaotu", "i1", "com.gaotu100.superclass", 8101)
    assert captured["runtime"]["port"] == 8101
    assert captured["runtime"]["bundle_id"] == "com.gaotu100.superclass"


def test_script_assert_ui_captures_checkpoint_without_agent(monkeypatch):
    handled = []
    ctx = {
        "script_meta": {"record_id": "rec1"},
        "handle_known_dialogs": lambda step=None: handled.append(step) or True,
        "capture_screenshot": lambda step=None: "/tmp/shot.png",
        "read_page_source": lambda force_refresh=False: "<App/>",
    }
    monkeypatch.setattr(
        orchestrate,
        "_assert_ui_via_agent",
        lambda *args, **kwargs: pytest.fail("assert_ui should not start agent during script flow"),
    )

    result = orchestrate._run_script_assert_ui(
        app_id="gaotu",
        platform="ios",
        udid="i1",
        ctx=ctx,
        step={"type": "assert_ui"},
        wda_port=8100,
    )

    assert result["passed"] is True
    assert result["verify_method"] == "screenshot"
    assert result["evidence"] == "/tmp/shot.png"
    assert result["checkpoint_index"] == 0
    assert handled == [{"type": "assert_ui"}]
    assert ctx["_script_ui_audit_checkpoints"][0]["screenshot"] == "/tmp/shot.png"


def test_script_ui_audit_entry_allows_known_dialog_handling_first():
    entry = orchestrate._script_ui_audit_entry(
        {"record_id": "rec1", "name": "case", "module": "首页"},
        {"type": "assert_ui", "text": "UI规范检查：首页"},
    )

    text = entry["steps"][0]["text"]
    assert "先自动处理已知系统弹窗" in text
    assert "除这些已知弹窗外，不执行额外点击/输入/跳转动作" in text


def test_finalize_deferred_script_ui_audit_updates_assert_ui_steps(monkeypatch):
    calls = []
    ctx = {
        "script_meta": {"record_id": "rec1"},
        "_script_ui_audit_checkpoints": [
            {"index": 0, "text": "UI规范检查：首页", "screenshot": "/tmp/home.png", "page_source": "<App/>"},
            {"index": 1, "text": "UI规范检查：登录", "screenshot": "/tmp/login.png", "page_source": "<App/>"},
        ],
    }
    monkeypatch.setattr(
        orchestrate,
        "_assert_ui_checkpoints_via_agent",
        lambda *args, **kwargs: calls.append(args) or [
            {"checkpoint_index": 0, "pass": True, "verify_method": "vision", "evidence": "/tmp/home.png", "confidence": "high", "note": "ok"},
            {"checkpoint_index": 1, "passed": False, "verify_method": "vision", "evidence": "/tmp/login.png", "confidence": "high", "note": "overlap"},
        ],
    )
    monkeypatch.setattr(orchestrate, "_cleanup_ios_appium_mcp_wda", lambda udid: None)
    monkeypatch.setattr(orchestrate, "_resolve_ios_device_wda_config", lambda app_id, udid: {})
    monkeypatch.setattr(orchestrate.ios_wda, "ensure_wda_ready", lambda *args: True)
    result = {"passed": True, "steps": [
        {"type": "ASSERT_UI", "text": "UI规范检查：首页", "passed": True, "checkpoint_index": 0},
        {"type": "ASSERT_UI", "text": "UI规范检查：登录", "passed": True, "checkpoint_index": 1},
    ]}

    orchestrate._finalize_deferred_script_ui_audit("gaotu", "ios", "i1", ctx, result, wda_port=8100)

    assert len(calls) == 1
    assert result["passed"] is False
    assert result["note"] == "assert_ui failed: UI规范检查：登录"
    assert result["steps"][0]["passed"] is True
    assert result["steps"][0]["note"] == "ok"
    assert result["steps"][1]["passed"] is False
    assert result["steps"][1]["note"] == "overlap"


def test_assert_ui_checkpoints_retries_when_agent_returns_no_assert_steps(monkeypatch):
    calls = []
    checkpoints = [
        {"index": 0, "text": "UI规范检查：首页", "screenshot": "/tmp/home.png", "page_source": "<App/>"},
    ]

    def fake_execute_case_via_agent(**kwargs):
        calls.append(kwargs["result_dir"])
        if len(calls) == 1:
            return {"passed": False, "note": "agent execution failed: failed", "steps": []}
        return {"passed": True, "steps": [
            {"type": "ASSERT", "passed": True, "verify_method": "vision",
             "evidence": "/tmp/home.png", "confidence": "high", "note": "ok"}
        ]}

    monkeypatch.setenv("ORCH_SCRIPT_UI_AUDIT_RETRIES", "1")
    monkeypatch.setattr(orchestrate, "execute_case_via_agent", fake_execute_case_via_agent)
    monkeypatch.setattr(orchestrate.time, "sleep", lambda seconds: None)

    results = orchestrate._assert_ui_checkpoints_via_agent(
        "gaotu", "ios", "i1", {"record_id": "rec1"}, checkpoints, wda_port=8100
    )

    assert len(calls) == 2
    assert results == [{
        "checkpoint_index": 0,
        "text": "UI规范检查：首页",
        "passed": True,
        "verify_method": "vision",
        "evidence": "/tmp/home.png",
        "confidence": "high",
        "note": "ok",
    }]


def test_finalize_deferred_script_ui_audit_stops_appium_mcp_wda_after_agent(monkeypatch):
    calls = []
    ctx = {
        "script_meta": {"record_id": "rec1"},
        "_script_ui_audit_checkpoints": [
            {"index": 0, "text": "UI规范检查：首页", "screenshot": "/tmp/home.png", "page_source": "<App/>"},
        ],
    }
    monkeypatch.setattr(orchestrate, "_assert_ui_checkpoints_via_agent",
                        lambda *args, **kwargs: calls.append("agent") or [{"checkpoint_index": 0, "passed": True}])
    monkeypatch.setattr(orchestrate, "_cleanup_ios_appium_mcp_wda",
                        lambda udid: calls.append(("cleanup", udid)))
    monkeypatch.setattr(orchestrate, "_resolve_ios_device_wda_config",
                        lambda app_id, udid: {"team": "TEAM1", "bundle_id": "wda.bundle", "port": 8102})
    monkeypatch.setattr(orchestrate.ios_wda, "ensure_wda_ready",
                        lambda *args: calls.append("wda") or True)

    orchestrate._finalize_deferred_script_ui_audit("gaotu", "ios", "i1", ctx, {"passed": True, "steps": []}, wda_port=8100)

    assert calls == ["agent", ("cleanup", "i1"), "wda"]


def test_execute_case_with_fallback_ui_audit_uses_script_with_assert_ui(monkeypatch):
    entry = {"record_id": "rec1", "name": "case", "module": "首页", "steps": []}
    monkeypatch.setattr(orchestrate, "resolve_ui_audit_enabled", lambda: True)
    find_calls = []
    monkeypatch.setattr(orchestrate, "find_case_script",
                        lambda *args, **kwargs: find_calls.append(True) or "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: {"passed": True, "name": "case", "steps": [
                            {"type": "ASSERT_UI", "passed": True, "verify_method": "vision"}
                        ], "script_source": "script"})
    generated = []
    monkeypatch.setattr(orchestrate, "generate_case_script",
                        lambda *args, **kwargs: generated.append(True) or "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "execute_case_via_agent",
                        lambda *args, **kwargs: {"passed": True, "record_id": "rec1", "name": "case", "module": "首页", "platform": "Android", "device": "a1", "steps": []})

    result = orchestrate.execute_case_with_fallback(
        app_id="gaotu",
        platform="android",
        udid="a1",
        entry=entry,
        version="5.91.90",
        current_account="12345679000",
        result_dir="/tmp",
    )

    assert result["passed"] is True
    assert result["script_source"] == "script"
    assert find_calls == [True]
    assert generated == []


def test_write_results_to_table_uses_order_and_state_group_fields(monkeypatch):
    captured = {}

    class _Resp:
        def __init__(self, payload):
            self.payload = payload
        def read(self):
            return _json.dumps(self.payload, ensure_ascii=False).encode()

    def fake_urlopen(req):
        url = req.full_url
        if "batch_create" in url:
            captured["body"] = _json.loads(req.data.decode("utf-8"))
            return _Resp({"code": 0})
        return _Resp({"code": 0, "data": {"obj_token": "obj-token"}})

    monkeypatch.setattr(orchestrate, "_get_token", lambda: "token")
    monkeypatch.setattr(orchestrate, "_resolve_obj_token", lambda app_token: "obj-token")
    monkeypatch.setattr(orchestrate.urllib.request, "urlopen", fake_urlopen)

    orchestrate.write_results_to_table("gaotu", "android", [{
        "record_id": "rec_case1",
        "order": "A-02",
        "state_group": "login_flow",
        "device": "a1",
        "name": "case1",
        "passed": True,
        "steps": [],
        "screenshots": [],
    }])

    fields = captured["body"]["records"][0]["fields"]
    assert fields["record_id"] == "rec_case1"
    assert fields["编号"] == "A-02"
    assert fields["状态组"] == "login_flow"
    assert fields["执行设备"] == "a1"
    assert fields["用例名称"] == "case1"
    assert fields["执行结果"] == "通过"


def test_write_results_to_table_writes_execution_version(monkeypatch):
    captured = {}

    class _Resp:
        def __init__(self, payload):
            self.payload = payload
        def read(self):
            return _json.dumps(self.payload, ensure_ascii=False).encode()

    def fake_urlopen(req):
        url = req.full_url
        if "batch_create" in url:
            captured["body"] = _json.loads(req.data.decode("utf-8"))
            return _Resp({"code": 0})
        return _Resp({"code": 0, "data": {"obj_token": "obj-token"}})

    monkeypatch.setattr(orchestrate, "_get_token", lambda: "token")
    monkeypatch.setattr(orchestrate, "_resolve_obj_token", lambda app_token: "obj-token")
    monkeypatch.setattr(orchestrate.urllib.request, "urlopen", fake_urlopen)

    orchestrate.write_results_to_table("gaotu", "android", [{
        "record_id": "rec_case1",
        "device": "a1",
        "name": "case1",
        "passed": True,
        "steps": [],
        "screenshots": [],
    }], version="5.91.92")

    fields = captured["body"]["records"][0]["fields"]
    assert fields["执行版本"] == "5.91.92"


def test_write_results_to_table_writes_execution_time(monkeypatch):
    captured = {}

    class _Resp:
        def __init__(self, payload):
            self.payload = payload
        def read(self):
            return _json.dumps(self.payload, ensure_ascii=False).encode()

    def fake_urlopen(req):
        url = req.full_url
        if "batch_create" in url:
            captured["body"] = _json.loads(req.data.decode("utf-8"))
            return _Resp({"code": 0})
        return _Resp({"code": 0, "data": {"obj_token": "obj-token"}})

    monkeypatch.setattr(orchestrate, "_get_token", lambda: "token")
    monkeypatch.setattr(orchestrate, "_resolve_obj_token", lambda app_token: "obj-token")
    monkeypatch.setattr(orchestrate.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(orchestrate.time, "time", lambda: 1772431200.123)

    orchestrate.write_results_to_table("gaotu", "android", [{
        "record_id": "rec_case1",
        "device": "a1",
        "name": "case1",
        "passed": True,
        "steps": [],
        "screenshots": [],
    }])

    fields = captured["body"]["records"][0]["fields"]
    assert fields["执行时间"] == 1772431200123


def test_write_results_to_table_coerces_numeric_order_for_number_field(monkeypatch):
    captured = {}

    class _Resp:
        def __init__(self, payload):
            self.payload = payload
        def read(self):
            return _json.dumps(self.payload, ensure_ascii=False).encode()

    def fake_urlopen(req):
        url = req.full_url
        if "batch_create" in url:
            captured["body"] = _json.loads(req.data.decode("utf-8"))
            return _Resp({"code": 0})
        return _Resp({"code": 0, "data": {"obj_token": "obj-token"}})

    monkeypatch.setattr(orchestrate, "_get_token", lambda: "token")
    monkeypatch.setattr(orchestrate, "_resolve_obj_token", lambda app_token: "obj-token")
    monkeypatch.setattr(orchestrate.urllib.request, "urlopen", fake_urlopen)

    orchestrate.write_results_to_table("gaotu", "android", [{
        "record_id": "rec_case1",
        "order": "109",
        "state_group": "首页",
        "device": "a1",
        "name": "case1",
        "passed": True,
        "steps": [],
        "screenshots": [],
    }])

    fields = captured["body"]["records"][0]["fields"]
    assert fields["编号"] == 109


def test_write_results_to_table_omits_record_id_for_failed_cases(monkeypatch):
    captured = {}

    class _Resp:
        def __init__(self, payload):
            self.payload = payload
        def read(self):
            return _json.dumps(self.payload, ensure_ascii=False).encode()

    def fake_urlopen(req):
        url = req.full_url
        if "batch_create" in url:
            captured["body"] = _json.loads(req.data.decode("utf-8"))
            return _Resp({"code": 0})
        return _Resp({"code": 0, "data": {"obj_token": "obj-token"}})

    monkeypatch.setattr(orchestrate, "_get_token", lambda: "token")
    monkeypatch.setattr(orchestrate, "_resolve_obj_token", lambda app_token: "obj-token")
    monkeypatch.setattr(orchestrate.urllib.request, "urlopen", fake_urlopen)

    orchestrate.write_results_to_table("gaotu", "ios", [{
        "record_id": "rec_failed",
        "device": "i1",
        "name": "failed case",
        "passed": False,
        "steps": [],
        "screenshots": [],
    }])

    fields = captured["body"]["records"][0]["fields"]
    assert "record_id" not in fields
    assert fields["执行结果"] == "失败"


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
    """回归 bug：进程仍存活时,即便结果文件为空也不能提前判完成。"""
    udid = "dev_alive"
    (tmp_path / f"result_{udid}.jsonl").write_text("")
    proc = _FakeProc([None])  # 永远存活
    results = orchestrate.collect_results(
        {udid: proc}, result_dir=str(tmp_path), timeout=1, poll_interval=0.02)
    # 存活+空文件 → 不判 done/0，最终因 proc 未退出走超时
    assert results[udid] == "timeout"


def test_collect_results_reads_only_after_exit(tmp_path):
    """进程正常退出(code=0)后读取 JSONL 结果，判 done。"""
    udid = "dev_exit"
    cases = [{"name": "c1", "platform": "Android", "passed": True}]
    _write_jsonl(tmp_path / f"result_{udid}.jsonl", cases)
    proc = _FakeProc([0], returncode=0)  # 正常退出
    results = orchestrate.collect_results(
        {udid: proc}, result_dir=str(tmp_path), timeout=1, poll_interval=0.02)
    assert results[udid][0]["passed"] is True


def test_collect_results_exit_no_file_is_failed(tmp_path):
    """进程退出却一条结果都没落盘 → 判失败(非提前完成)。"""
    udid = "dev_crash"
    proc = _FakeProc([1], returncode=1)
    results = orchestrate.collect_results(
        {udid: proc}, result_dir=str(tmp_path), timeout=1, poll_interval=0.02)
    assert results[udid] == "failed"


def test_collect_results_crash_keeps_partial(tmp_path):
    """核心：进程 429/异常退出(code=1)但已增量落盘部分用例 → 保留部分结果，不整台判失败。"""
    udid = "dev_partial"
    cases = [{"name": "c1", "platform": "Android", "passed": True},
             {"name": "c2", "platform": "Android", "passed": False}]
    _write_jsonl(tmp_path / f"result_{udid}.jsonl", cases)
    proc = _FakeProc([1], returncode=1)  # 异常退出
    with patch("orchestrate._notify") as notify:
        results = orchestrate.collect_results(
            {udid: proc}, result_dir=str(tmp_path), timeout=1, poll_interval=0.02,
            app_id="gaotu", version="9.9.9", run_id="r_test")
    # 已跑完的 2 条被保留(而非整台 "failed")
    assert isinstance(results[udid], list) and len(results[udid]) == 2
    # 崩溃仍即时报警
    assert notify.called


def test_collect_results_exit0_with_partial_results_marks_crashed(tmp_path):
    """进程正常退出但只落盘部分结果 → 保留部分结果，但不能记 done。"""
    udid = "dev_partial_exit0"
    cases = [{"name": "c1", "platform": "Android", "passed": True}]
    _write_jsonl(tmp_path / f"result_{udid}.jsonl", cases)
    proc = _FakeProc([0], returncode=0)
    with patch("orchestrate._notify") as notify, \
         patch("orchestrate.run_status") as rs:
        results = orchestrate.collect_results(
            {udid: proc},
            result_dir=str(tmp_path),
            timeout=1,
            poll_interval=0.02,
            app_id="gaotu",
            version="9.9.9",
            run_id="r_test",
            device_totals={udid: {"total": 3, "platform": "Android"}},
        )
    assert isinstance(results[udid], list)
    assert len(results[udid]) == 1
    assert notify.called
    assert rs.update_device.call_args.kwargs["state"] == "crashed"


def test_collect_results_tolerates_corrupt_last_line(tmp_path):
    """崩溃时半写的末行损坏 → 跳过该行，前面完整行照常读回。"""
    udid = "dev_halfwrite"
    good = _json.dumps({"name": "c1", "platform": "Android", "passed": True})
    (tmp_path / f"result_{udid}.jsonl").write_text(good + "\n" + '{"name": "c2", "pla')
    proc = _FakeProc([1], returncode=1)
    with patch("orchestrate._notify"):
        results = orchestrate.collect_results(
            {udid: proc}, result_dir=str(tmp_path), timeout=1, poll_interval=0.02,
            app_id="gaotu", version="9.9.9", run_id="r_test")
    assert isinstance(results[udid], list) and len(results[udid]) == 1


def test_collect_results_reads_agent_log_tail(monkeypatch, tmp_path):
    udid = "dev_crash"
    proc = _FakeProc([1], returncode=1)
    log_path = tmp_path / f"agent_{udid}.log"
    log_path.write_text("runner failed")
    monkeypatch.setattr(orchestrate, "agent_log_path", lambda value: str(tmp_path / f"agent_{value}.log"))
    with patch("orchestrate._notify") as notify:
        results = orchestrate.collect_results(
            {udid: proc}, result_dir=str(tmp_path), timeout=1, poll_interval=0.02,
            app_id="gaotu", version="9.9.9", run_id="r_test")
    assert results[udid] == "failed"
    assert "runner failed" in notify.call_args[0][2]


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
    _write_jsonl(tmp_path / "result_a1.jsonl",
                 [{"platform": "Android", "passed": True},
                  {"platform": "Android", "passed": False}])
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


def test_generate_reports_shows_script_hit_rate():
    """报告展示脚本命中率:有脚本的用例中脚本直接跑完的占比 + 回退数。"""
    results = {"a1": [
        {"platform": "Android", "passed": True, "exec_source": "script"},
        {"platform": "Android", "passed": True, "exec_source": "script"},
        {"platform": "Android", "passed": True, "exec_source": "script_fallback"},
        {"platform": "Android", "passed": True, "exec_source": "agent"},  # 无脚本,不计入命中率分母
    ]}
    device_totals = {"a1": {"total": 4, "platform": "Android"}}
    with patch("orchestrate._notify") as notify, \
         patch("orchestrate.write_results_to_table"), \
         patch("orchestrate.subprocess.run") as sr:
        sr.return_value.stdout = ""
        orchestrate.generate_reports("gaotu", "9.9.9", results, 60,
                                     start_time_str="00:00:00",
                                     device_totals=device_totals)
        body = notify.call_args[0][2]
        # 有脚本 3 条(2 script + 1 fallback),命中 2 → 2/3(66%),回退 1
        assert "脚本命中 2/3 (66%)" in body
        assert "回退 1" in body


def test_generate_reports_no_script_hides_hit_rate():
    """全是从零 agent(无脚本)时不显示命中率段。"""
    results = {"a1": [{"platform": "Android", "passed": True, "exec_source": "agent"}]}
    with patch("orchestrate._notify") as notify, \
         patch("orchestrate.write_results_to_table"), \
         patch("orchestrate.subprocess.run") as sr:
        sr.return_value.stdout = ""
        orchestrate.generate_reports("gaotu", "9.9.9", results, 60,
                                     start_time_str="00:00:00",
                                     device_totals={"a1": {"total": 1, "platform": "Android"}})
        assert "脚本命中" not in notify.call_args[0][2]


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


def test_chunk_entries_splits_device_cases_in_order():
    entries = [{"name": f"c{i}"} for i in range(5)]
    batches = orchestrate.chunk_entries(entries, batch_size=2)
    assert [[c["name"] for c in batch] for batch in batches] == [
        ["c0", "c1"],
        ["c2", "c3"],
        ["c4"],
    ]


def test_execute_device_batches_writes_each_batch(monkeypatch, tmp_path):
    udid = "a1"
    group = {
        "platform": "Android",
        "entries": [{"name": "c1"}, {"name": "c2"}, {"name": "c3"}],
    }
    launched = []
    writes = []
    batch_payloads = [
        [{"name": "c1", "platform": "Android", "device": udid, "passed": True, "steps": []},
         {"name": "c2", "platform": "Android", "device": udid, "passed": False, "steps": []}],
        [{"name": "c3", "platform": "Android", "device": udid, "passed": True, "steps": []}],
    ]

    class _Proc:
        returncode = 0
        def poll(self):
            return 0

    def fake_launch_agent_batch(app_id, batch_udid, platform, entries, **kwargs):
        launched.append({
            "udid": batch_udid,
            "platform": platform,
            "entries": [e["name"] for e in entries],
            "result_dir": kwargs["result_dir"],
            "batch_idx": kwargs["batch_idx"],
            "batch_count": kwargs["batch_count"],
        })
        return _Proc()

    def fake_collect_results(procs, result_dir="/tmp", **kwargs):
        idx = len(writes)
        result_path = tmp_path / "batch_results" / f"batch_{udid}_{idx}" / f"result_{udid}.jsonl"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        _write_jsonl(result_path, batch_payloads[idx])
        return {udid: batch_payloads[idx]}

    def fake_write_results_to_table(app_id, platform, cases):
        writes.append((app_id, platform, [c["name"] for c in cases]))

    monkeypatch.setattr(orchestrate, "launch_agent_batch", fake_launch_agent_batch)
    monkeypatch.setattr(orchestrate, "collect_results", fake_collect_results)
    monkeypatch.setattr(orchestrate, "write_results_to_table", fake_write_results_to_table)

    results = orchestrate.execute_device_batches(
        app_id="gaotu",
        udid=udid,
        group=group,
        version="5.91.90",
        run_id="r1",
        result_dir=str(tmp_path),
        batch_size=2,
    )

    assert [x["entries"] for x in launched] == [["c1", "c2"], ["c3"]]
    assert writes == [
        ("gaotu", "android", ["c1", "c2"]),
        ("gaotu", "android", ["c3"]),
    ]
    assert [c["name"] for c in results] == ["c1", "c2", "c3"]
    merged = orchestrate._load_jsonl(tmp_path / f"result_{udid}.jsonl")
    assert [c["name"] for c in merged] == ["c1", "c2", "c3"]


def test_execute_device_batches_recovers_legacy_agent_result_path(monkeypatch, tmp_path):
    udid = "a1"
    group = {
        "platform": "Android",
        "entries": [
            {"record_id": "r1", "name": "c1", "module": "首页"},
            {"record_id": "r2", "name": "c2", "module": "首页"},
        ],
    }
    payload = [
        {"record_id": "r1", "name": "c1", "platform": "Android", "device": udid, "passed": False, "steps": []},
        {"record_id": "r2", "name": "c2", "platform": "Android", "device": udid, "passed": True, "steps": []},
    ]

    class _Proc:
        returncode = 0
        def poll(self):
            return 0

    def fake_collect_results(procs, result_dir="/tmp", **kwargs):
        _write_jsonl(tmp_path / f"result_{udid}.jsonl", payload)
        return {udid: "failed"}

    writes = []
    monkeypatch.setattr(orchestrate, "launch_agent_batch", lambda *args, **kwargs: _Proc())
    monkeypatch.setattr(orchestrate, "collect_results", fake_collect_results)
    monkeypatch.setattr(orchestrate, "write_results_to_table",
                        lambda app_id, platform, cases: writes.append([c["name"] for c in cases]))

    results = orchestrate.execute_device_batches(
        app_id="gaotu",
        udid=udid,
        group=group,
        result_dir=str(tmp_path),
        batch_size=20,
    )

    assert [c["name"] for c in results] == ["c1", "c2"]
    assert writes == [["c1", "c2"]]


def test_resolve_agent_timeout_shortens_codex_only(monkeypatch):
    monkeypatch.delenv("ORCH_AGENT_TIMEOUT_SECONDS", raising=False)

    monkeypatch.setattr(orchestrate, "resolve_agent_runner", lambda: "codex")
    assert orchestrate._resolve_agent_timeout_seconds(90 * 60) == 15 * 60

    monkeypatch.setattr(orchestrate, "resolve_agent_runner", lambda: "claude")
    assert orchestrate._resolve_agent_timeout_seconds(90 * 60) == 90 * 60

    monkeypatch.setenv("ORCH_AGENT_TIMEOUT_SECONDS", "120")
    assert orchestrate._resolve_agent_timeout_seconds(90 * 60) == 120


def test_execute_device_batches_synthesizes_failures_when_agent_writes_no_results(monkeypatch, tmp_path):
    udid = "a1"
    group = {
        "platform": "Android",
        "entries": [
            {"record_id": "r1", "name": "c1", "module": "启动"},
            {"record_id": "r2", "name": "c2", "module": "启动"},
        ],
    }

    class _Proc:
        returncode = 1
        def poll(self):
            return 1

    writes = []
    monkeypatch.setattr(orchestrate, "resolve_agent_runner", lambda: "claude")
    monkeypatch.setattr(orchestrate, "launch_agent_batch", lambda *args, **kwargs: _Proc())
    monkeypatch.setattr(orchestrate, "collect_results", lambda *args, **kwargs: {udid: "timeout"})
    monkeypatch.setattr(orchestrate, "write_results_to_table",
                        lambda app_id, platform, cases: writes.append([c["name"] for c in cases]))

    results = orchestrate.execute_device_batches(
        app_id="gaotu",
        udid=udid,
        group=group,
        result_dir=str(tmp_path),
        batch_size=20,
    )

    assert [c["record_id"] for c in results] == ["r1", "r2"]
    assert all(c["passed"] is False for c in results)
    assert all(c["exec_source"] == "agent_timeout" for c in results)
    assert writes == [["c1", "c2"]]
    merged = orchestrate._load_jsonl(tmp_path / f"result_{udid}.jsonl")
    assert [c["record_id"] for c in merged] == ["r1", "r2"]


def test_execute_device_batches_dedupes_duplicate_agent_results(monkeypatch, tmp_path):
    udid = "a1"
    group = {
        "platform": "Android",
        "entries": [{"record_id": "r1", "name": "c1", "module": "启动"}],
    }
    payload = [
        {"record_id": "r1", "name": "c1", "platform": "Android", "device": udid,
         "passed": False, "steps": [{"note": "early"}]},
        {"record_id": "r1", "name": "c1", "platform": "Android", "device": udid,
         "passed": True, "steps": [{"note": "latest"}]},
    ]

    class _Proc:
        returncode = 0
        def poll(self):
            return 0

    seen_run_ids = []

    def fake_collect_results(procs, result_dir="/tmp", **kwargs):
        seen_run_ids.append(kwargs.get("run_id"))
        result_path = tmp_path / "batch_results" / f"batch_{udid}_0" / f"result_{udid}.jsonl"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        _write_jsonl(result_path, payload)
        return {udid: payload}

    monkeypatch.setattr(orchestrate, "resolve_agent_runner", lambda: "claude")
    monkeypatch.setattr(orchestrate, "launch_agent_batch", lambda *args, **kwargs: _Proc())
    monkeypatch.setattr(orchestrate, "collect_results", fake_collect_results)
    monkeypatch.setattr(orchestrate, "write_results_to_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrate, "generate_case_script", lambda *args, **kwargs: None)

    results = orchestrate.execute_device_batches(
        app_id="gaotu",
        udid=udid,
        group=group,
        run_id="run1",
        result_dir=str(tmp_path),
        batch_size=20,
    )

    assert seen_run_ids == ["run1"]
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert results[0]["steps"][0]["note"] == "latest"


def test_execute_device_batches_uses_script_first_results(monkeypatch, tmp_path):
    group = {
        "platform": "Android",
        "entries": [{"record_id": "rec1", "name": "c1", "module": "首页", "steps": []}],
    }
    monkeypatch.setattr(orchestrate, "find_case_script", lambda *args, **kwargs: "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "execute_case_with_fallback",
                        lambda **kwargs: {
                            "record_id": "rec1",
                            "name": "c1",
                            "module": "首页",
                            "platform": "Android",
                            "device": "a1",
                            "passed": True,
                            "steps": [],
                            "_current_account": "",
                        })
    writes = []
    monkeypatch.setattr(orchestrate, "write_results_to_table",
                        lambda app_id, platform, cases: writes.append((app_id, platform, len(cases))))

    results = orchestrate.execute_device_batches(
        app_id="gaotu",
        udid="a1",
        group=group,
        version="5.91.90",
        run_id="r1",
        result_dir=str(tmp_path),
        batch_size=20,
    )

    assert results[0]["record_id"] == "rec1"
    assert results[0]["passed"] is True
    assert writes == [("gaotu", "android", 1)]


def test_hydrate_batch_cases_backfills_missing_record_id():
    entries = [
        {"record_id": "rec1", "name": "c1", "module": "首页"},
        {"record_id": "rec2", "name": "c2", "module": "登录"},
    ]
    cases = [
        {"seq": 1, "name": "c1", "platform": "Android", "device": "a1", "passed": True, "steps": []},
        {"seq": 2, "platform": "Android", "device": "a1", "passed": False, "steps": []},
    ]

    hydrated = orchestrate._hydrate_batch_cases(cases, entries)

    assert hydrated[0]["record_id"] == "rec1"
    assert hydrated[1]["record_id"] == "rec2"
    assert hydrated[1]["name"] == "c2"
    assert hydrated[1]["module"] == "登录"


def test_execute_device_batches_hydrates_record_id_before_solidify(monkeypatch, tmp_path):
    """回归：agent 结果只写 source_record_id、无 record_id；execute_device_batches
    必须先 hydrate 再固化，否则 generate_case_script 读 case["record_id"] 会 KeyError
    掀翻整轮（线上 5.91.93 事故）。"""
    udid = "a1"
    group = {
        "platform": "Android",
        "entries": [
            {"record_id": "recPASS", "name": "c1", "state_group": "g1",
             "steps": [{"type": "PRECOND", "text": "账号：12345679000"}]},
        ],
    }
    launched = []
    solidified = []

    class _Proc:
        returncode = 0
        def poll(self):
            return 0

    def fake_launch_agent_batch(app_id, batch_udid, platform, entries, **kwargs):
        launched.append([e["name"] for e in entries])
        return _Proc()

    def fake_collect_results(procs, result_dir="/tmp", **kwargs):
        idx = len(launched) - 1
        result_path = tmp_path / "batch_results" / f"batch_{udid}_{idx}" / f"result_{udid}.jsonl"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        # 关键：只有 source_record_id，故意不带 record_id
        payload = [{"seq": 1, "name": "c1", "platform": "Android", "device": udid,
                    "passed": True, "source_record_id": "recPASS", "steps": []}]
        _write_jsonl(result_path, payload)
        return {udid: payload}

    monkeypatch.setattr(orchestrate, "launch_agent_batch", fake_launch_agent_batch)
    monkeypatch.setattr(orchestrate, "collect_results", fake_collect_results)
    monkeypatch.setattr(orchestrate, "write_results_to_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrate, "generate_case_script",
                        lambda app_id, platform, case, **kw: solidified.append(dict(case)))

    orchestrate.execute_device_batches(
        app_id="gaotu",
        udid=udid,
        group=group,
        version="5.91.90",
        run_id="r1",
        result_dir=str(tmp_path),
        batch_size=20,
    )

    # 通过用例进了固化，且拿到了 backfill 出的 record_id（没有则曾 KeyError 崩整轮）
    assert len(solidified) == 1
    assert solidified[0]["record_id"] == "recPASS"


def test_execute_device_batches_groups_by_state_group_and_account(monkeypatch, tmp_path):
    udid = "a1"
    group = {
        "platform": "Android",
        "entries": [
            {"name": "c1", "state_group": "g1", "steps": [{"type": "PRECOND", "text": "账号：12345679000"}]},
            {"name": "c2", "state_group": "g1", "steps": [{"type": "PRECOND", "text": "账号：12345679000"}]},
            {"name": "c3", "state_group": "g2", "steps": [{"type": "PRECOND", "text": "账号：12211119071"}]},
            {"name": "c4", "state_group": "g2", "steps": [{"type": "PRECOND", "text": "账号：12211119071"}]},
        ],
    }
    launched = []

    class _Proc:
        returncode = 0
        def poll(self):
            return 0

    def fake_launch_agent_batch(app_id, batch_udid, platform, entries, **kwargs):
        launched.append({
            "entries": [e["name"] for e in entries],
            "current_account": kwargs["current_account"],
            "batch_idx": kwargs["batch_idx"],
            "batch_count": kwargs["batch_count"],
        })
        return _Proc()

    def fake_collect_results(procs, result_dir="/tmp", **kwargs):
        idx = len(launched) - 1
        names = launched[idx]["entries"]
        result_path = tmp_path / "batch_results" / f"batch_{udid}_{idx}" / f"result_{udid}.jsonl"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [{"seq": pos, "name": n, "platform": "Android", "device": udid, "passed": True, "steps": []}
                   for pos, n in enumerate(names, 1)]
        _write_jsonl(result_path, payload)
        return {udid: payload}

    monkeypatch.setattr(orchestrate, "launch_agent_batch", fake_launch_agent_batch)
    monkeypatch.setattr(orchestrate, "collect_results", fake_collect_results)
    monkeypatch.setattr(orchestrate, "write_results_to_table", lambda *args, **kwargs: None)

    orchestrate.execute_device_batches(
        app_id="gaotu",
        udid=udid,
        group=group,
        version="5.91.90",
        run_id="r1",
        result_dir=str(tmp_path),
        batch_size=20,
    )

    assert [x["entries"] for x in launched] == [["c1", "c2"], ["c3", "c4"]]
    assert [x["batch_count"] for x in launched] == [2, 2]


def test_execute_device_batches_splits_same_state_group_on_account_change(monkeypatch, tmp_path):
    udid = "a1"
    group = {
        "platform": "Android",
        "entries": [
            {"name": "c1", "state_group": "g1", "steps": [{"type": "PRECOND", "text": "账号：12345679000"}]},
            {"name": "c2", "state_group": "g1", "steps": [{"type": "PRECOND", "text": "账号：12177931844"}]},
            {"name": "c3", "state_group": "g1", "steps": [{"type": "PRECOND", "text": "账号：12177931844"}]},
        ],
    }
    launched = []

    class _Proc:
        returncode = 0
        def poll(self):
            return 0

    def fake_launch_agent_batch(app_id, batch_udid, platform, entries, **kwargs):
        launched.append([e["name"] for e in entries])
        return _Proc()

    def fake_collect_results(procs, result_dir="/tmp", **kwargs):
        idx = len(launched) - 1
        names = launched[idx]
        result_path = tmp_path / "batch_results" / f"batch_{udid}_{idx}" / f"result_{udid}.jsonl"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [{"name": n, "platform": "Android", "device": udid, "passed": True, "steps": []}
                   for n in names]
        _write_jsonl(result_path, payload)
        return {udid: payload}

    monkeypatch.setattr(orchestrate, "launch_agent_batch", fake_launch_agent_batch)
    monkeypatch.setattr(orchestrate, "collect_results", fake_collect_results)
    monkeypatch.setattr(orchestrate, "write_results_to_table", lambda *args, **kwargs: None)

    orchestrate.execute_device_batches(
        app_id="gaotu",
        udid=udid,
        group=group,
        version="5.91.90",
        run_id="r1",
        result_dir=str(tmp_path),
        batch_size=20,
    )

    assert launched == [["c1"], ["c2", "c3"]]


def test_build_execution_batches_splits_when_prompt_budget_exceeded(monkeypatch):
    monkeypatch.setattr(orchestrate, "resolve_max_batch_prompt_chars", lambda: 220)
    entries = [
        {
            "record_id": "r1",
            "name": "c1",
            "module": "首页",
            "state_group": "g1",
            "steps": [{"type": "ACTION", "text": "A" * 60}],
        },
        {
            "record_id": "r2",
            "name": "c2",
            "module": "首页",
            "state_group": "g1",
            "steps": [{"type": "ACTION", "text": "B" * 60}],
        },
        {
            "record_id": "r3",
            "name": "c3",
            "module": "首页",
            "state_group": "g1",
            "steps": [{"type": "ACTION", "text": "C" * 60}],
        },
    ]

    batches = orchestrate.build_execution_batches(entries, batch_size=20)

    assert [[entry["name"] for entry in batch] for batch in batches] == [["c1"], ["c2"], ["c3"]]


def test_execute_device_batches_writes_results_before_launching_next_context_batch(monkeypatch, tmp_path):
    udid = "a1"
    group = {
        "platform": "Android",
        "entries": [
            {"record_id": "r1", "name": "c1", "module": "首页", "state_group": "g1", "steps": [{"type": "ACTION", "text": "A" * 60}]},
            {"record_id": "r2", "name": "c2", "module": "首页", "state_group": "g1", "steps": [{"type": "ACTION", "text": "B" * 60}]},
        ],
    }
    events = []

    class _Proc:
        returncode = 0
        def poll(self):
            return 0

    monkeypatch.setattr(orchestrate, "resolve_max_batch_prompt_chars", lambda: 220)

    def fake_launch_agent_batch(app_id, batch_udid, platform, entries, **kwargs):
        events.append(("launch", kwargs["batch_idx"], [e["name"] for e in entries]))
        return _Proc()

    def fake_collect_results(procs, result_dir="/tmp", **kwargs):
        batch_dir = os.path.basename(result_dir)
        idx = int(batch_dir.rsplit("_", 1)[-1])
        result_path = tmp_path / "batch_results" / f"batch_{udid}_{idx}" / f"result_{udid}.jsonl"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [{
            "record_id": f"r{idx + 1}",
            "name": f"c{idx + 1}",
            "platform": "Android",
            "device": udid,
            "passed": True,
            "steps": [],
        }]
        _write_jsonl(result_path, payload)
        return {udid: payload}

    def fake_write_results_to_table(app_id, platform, cases):
        events.append(("write", [c["name"] for c in cases]))

    monkeypatch.setattr(orchestrate, "launch_agent_batch", fake_launch_agent_batch)
    monkeypatch.setattr(orchestrate, "collect_results", fake_collect_results)
    monkeypatch.setattr(orchestrate, "write_results_to_table", fake_write_results_to_table)

    orchestrate.execute_device_batches(
        app_id="gaotu",
        udid=udid,
        group=group,
        version="5.91.90",
        run_id="r1",
        result_dir=str(tmp_path),
        batch_size=20,
    )

    assert events == [
        ("launch", 0, ["c1"]),
        ("write", ["c1"]),
        ("launch", 1, ["c2"]),
        ("write", ["c2"]),
    ]


def test_execute_device_batches_splits_launch_popup_group_per_case(monkeypatch, tmp_path):
    udid = "a1"
    group = {
        "platform": "iOS",
        "entries": [
            {"name": "c1", "state_group": "启动弹窗", "steps": []},
            {"name": "c2", "state_group": "启动弹窗", "steps": []},
            {"name": "c3", "state_group": "启动弹窗", "steps": []},
        ],
    }
    launched = []

    class _Proc:
        returncode = 0
        def poll(self):
            return 0

    def fake_launch_agent_batch(app_id, batch_udid, platform, entries, **kwargs):
        launched.append([e["name"] for e in entries])
        return _Proc()

    def fake_collect_results(procs, result_dir="/tmp", **kwargs):
        idx = len(launched) - 1
        names = launched[idx]
        result_path = tmp_path / "batch_results" / f"batch_{udid}_{idx}" / f"result_{udid}.jsonl"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [{"name": n, "platform": "iOS", "device": udid, "passed": True, "steps": []}
                   for n in names]
        _write_jsonl(result_path, payload)
        return {udid: payload}

    monkeypatch.setattr(orchestrate, "launch_agent_batch", fake_launch_agent_batch)
    monkeypatch.setattr(orchestrate, "collect_results", fake_collect_results)
    monkeypatch.setattr(orchestrate, "write_results_to_table", lambda *args, **kwargs: None)

    orchestrate.execute_device_batches(
        app_id="gaotu",
        udid=udid,
        group=group,
        version="5.91.90",
        run_id="r1",
        result_dir=str(tmp_path),
        batch_size=20,
    )

    assert launched == [["c1"], ["c2"], ["c3"]]


def test_entry_account_key_accepts_more_precond_formats():
    assert orchestrate.entry_account_key({
        "steps": [{"type": "PRECOND", "text": "使用12345679000登录并进入AI闪学"}]
    }) == "12345679000"
    assert orchestrate.entry_account_key({
        "steps": [{"type": "PRECOND", "text": "12345679000已登录，当前在AI闪学页"}]
    }) == "12345679000"
    assert orchestrate.entry_account_key({
        "steps": [{"type": "PRECOND", "text": "账号为12177931844，当前在首页"}]
    }) == "12177931844"


def test_run_clears_result_tables_once_before_batched_execution(monkeypatch):
    monkeypatch.setattr(orchestrate, "load_devices", lambda app_id: {
        "android": [{"udid": "a1", "name": "android-dev"}],
        "ios": [],
    })
    monkeypatch.setattr(orchestrate, "download_file", lambda url, dest: True)
    monkeypatch.setattr(orchestrate, "install_android", lambda path, udid: True)
    monkeypatch.setattr(orchestrate, "fetch_cases", lambda app_id: [
        {"record_id": "r1", "name": "c1", "module": "首页", "steps": [], "android_device": "a1", "ios_device": ""},
    ])
    monkeypatch.setattr(orchestrate, "run_exploration", lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrate, "finalize", lambda **kwargs: True)

    cleared = []
    monkeypatch.setattr(orchestrate, "clear_result_tables",
                        lambda app_id, platforms: cleared.append((app_id, tuple(sorted(platforms)))))
    monkeypatch.setattr(orchestrate, "execute_batches_for_groups",
                        lambda app_id, groups, **kwargs: {"a1": []})
    monkeypatch.setattr(
        orchestrate,
        "launch_claude_per_device",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy per-device agent must not be launched")
        ),
    )

    with patch("orchestrate.run_status"), patch("orchestrate._notify"):
        orchestrate._run(
            app_id="gaotu",
            version="5.91.90",
            apk_url="https://example.com/app.apk",
            ipa_url="",
            platforms={"android"},
            run_id="r1",
        )

    assert cleared == [("gaotu", ("android",))]


def test_run_resets_apps_after_exploration(monkeypatch):
    monkeypatch.setattr(orchestrate, "load_devices", lambda app_id: {
        "android": [{"udid": "a1", "name": "android-dev"}],
        "ios": [{"udid": "i1", "name": "ios-dev"}],
    })
    monkeypatch.setattr(orchestrate, "download_file", lambda url, dest: True)
    monkeypatch.setattr(orchestrate, "install_android", lambda path, udid: True)
    monkeypatch.setattr(orchestrate, "install_ios", lambda path, udid: True)
    monkeypatch.setattr(orchestrate.ios_wda, "ensure_wda_ready", lambda *args, **kwargs: True)
    monkeypatch.setattr(orchestrate, "ensure_ios_network_permission_ready", lambda *args, **kwargs: True)
    monkeypatch.setattr(orchestrate, "fetch_cases", lambda app_id: [])
    monkeypatch.setattr(orchestrate, "run_exploration", lambda *args, **kwargs: None)

    resets = []
    monkeypatch.setattr(orchestrate, "reset_apps_after_exploration",
                        lambda app_id, android_devices, ios_devices:
                        resets.append((app_id, tuple(android_devices), tuple(ios_devices))))

    with patch("orchestrate.run_status"), patch("orchestrate._notify"):
        orchestrate._run(
            app_id="gaotu",
            version="5.91.90",
            apk_url="https://example.com/app.apk",
            ipa_url="https://example.com/app.ipa",
            platforms={"android", "ios"},
            run_id="r1",
        )

    assert resets == [("gaotu", ("a1",), ("i1",))]


def test_run_ios_executes_after_wda_ready(monkeypatch):
    monkeypatch.setattr(orchestrate, "load_devices", lambda app_id: {
        "android": [],
        "ios": [{"udid": "i1", "name": "ios-dev"}],
    })
    monkeypatch.setattr(orchestrate, "download_file", lambda url, dest: True)
    monkeypatch.setattr(orchestrate, "install_ios", lambda path, udid: True)
    monkeypatch.setattr(orchestrate.ios_wda, "ensure_wda_ready", lambda *args, **kwargs: True)
    monkeypatch.setattr(orchestrate, "ensure_ios_network_permission_ready", lambda *args, **kwargs: True)
    monkeypatch.setattr(orchestrate, "fetch_cases", lambda app_id: [
        {"record_id": "r1", "name": "c1", "module": "首页", "steps": [], "android_device": "", "ios_device": "i1"},
    ])
    monkeypatch.setattr(orchestrate, "clear_result_tables", lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrate, "finalize", lambda **kwargs: True)

    executed = []
    monkeypatch.setattr(orchestrate, "execute_batches_for_groups",
                        lambda app_id, groups, **kwargs:
                        executed.append((app_id, sorted(groups.keys()))) or {"i1": []})

    with patch("orchestrate.run_status"), patch("orchestrate._notify"):
        orchestrate._run(
            app_id="gaotu",
            version="5.91.90",
            apk_url="",
            ipa_url="https://example.com/app.ipa",
            platforms={"ios"},
            run_id="r1",
        )

    assert executed == [("gaotu", ["i1"])]


def test_run_skips_ios_device_when_network_permission_prepare_fails(monkeypatch):
    monkeypatch.setattr(orchestrate, "load_devices", lambda app_id: {
        "android": [],
        "ios": [{"udid": "i1", "name": "ios-dev"}],
    })
    monkeypatch.setattr(orchestrate, "download_file", lambda url, dest: True)
    monkeypatch.setattr(orchestrate, "install_ios", lambda path, udid: True)
    monkeypatch.setattr(orchestrate.ios_wda, "ensure_wda_ready", lambda *args, **kwargs: True)
    monkeypatch.setattr(orchestrate, "ensure_ios_network_permission_ready", lambda *args, **kwargs: False)
    monkeypatch.setattr(orchestrate, "fetch_cases", lambda app_id: [
        {"record_id": "r1", "name": "c1", "module": "首页", "steps": [], "android_device": "", "ios_device": "i1"},
    ])

    executed = []
    monkeypatch.setattr(orchestrate, "execute_batches_for_groups",
                        lambda app_id, groups, **kwargs:
                        executed.append((app_id, sorted(groups.keys()))) or {})

    with patch("orchestrate.run_status"), patch("orchestrate._notify") as notify:
        orchestrate._run(
            app_id="gaotu",
            version="5.91.90",
            apk_url="",
            ipa_url="https://example.com/app.ipa",
            platforms={"ios"},
            run_id="r1",
        )

    assert executed == []
    assert any("网络权限预热失败" in call.args[2] for call in notify.call_args_list)


def test_run_skips_ios_device_when_wda_not_ready(monkeypatch):
    monkeypatch.setattr(orchestrate, "load_devices", lambda app_id: {
        "android": [],
        "ios": [{"udid": "i1", "name": "ios-dev"}],
    })
    monkeypatch.setattr(orchestrate, "download_file", lambda url, dest: True)
    monkeypatch.setattr(orchestrate, "install_ios", lambda path, udid: True)
    monkeypatch.setattr(orchestrate.ios_wda, "ensure_wda_ready", lambda *args, **kwargs: False)
    monkeypatch.setattr(orchestrate, "fetch_cases", lambda app_id: [
        {"record_id": "r1", "name": "c1", "module": "首页", "steps": [], "android_device": "", "ios_device": "i1"},
    ])

    executed = []
    monkeypatch.setattr(orchestrate, "execute_batches_for_groups",
                        lambda app_id, groups, **kwargs:
                        executed.append((app_id, sorted(groups.keys()))) or {"i1": []})

    with patch("orchestrate.run_status"), patch("orchestrate._notify") as notify:
        orchestrate._run(
            app_id="gaotu",
            version="5.91.90",
            apk_url="",
            ipa_url="https://example.com/app.ipa",
            platforms={"ios"},
            run_id="r1",
        )

    assert executed == []
    assert any("WDA 未就绪" in args[2] for args, _ in notify.call_args_list)


def test_generate_case_script_orders_unmatched_numbered_asserts_by_index(tmp_path, monkeypatch):
    """编号断言若无同号 ACTION，应按编号插到位（介于前后动作之间），而非全部堆到末尾。"""
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec_order",
        "name": "order case",
        "module": "启动登录",
        "platform": "iOS",
        "passed": True,
        "steps": [
            {"type": "ACTION", "text": "2. 点击不同意", "script_action": "tap",
             "locator": {"by": "accessibility_id", "value": "不同意"}},
            {"type": "ACTION", "text": "5. 点击同意", "script_action": "tap",
             "locator": {"by": "accessibility_id", "value": "同意"}},
            {"type": "ASSERT", "text": "1. 隐私弹窗弹出", "pass": True,
             "verify_method": "text", "evidence": "page_source contains 同意, 不同意", "confidence": "high"},
            {"type": "ASSERT", "text": "2. 切换为温馨提示", "pass": True,
             "verify_method": "text", "evidence": "page_source contains 温馨提示标题", "confidence": "high"},
            {"type": "ASSERT", "text": "3. 温馨提示正文完整", "pass": True,
             "verify_method": "text", "evidence": "page_source contains 温馨提示正文内容", "confidence": "high"},
            {"type": "ASSERT", "text": "4. 同意/简单浏览模式按钮", "pass": True,
             "verify_method": "text", "evidence": "page_source contains 同意标签, 简单浏览模式", "confidence": "high"},
            {"type": "ASSERT", "text": "5. 青少年守护弹窗", "pass": True,
             "verify_method": "text", "evidence": "page_source contains 青少年守护标题", "confidence": "high"},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "ios", case, version="5.91.93")
    content = open(path).read()

    i2 = content.index("'text': '2. 切换为温馨提示'")
    i3 = content.index("'text': '3. 温馨提示正文完整'")
    i4 = content.index("'text': '4. 同意/简单浏览模式按钮'")
    i5tap = content.index("'value': '同意'")   # step-5 tap locator
    i5 = content.index("'text': '5. 青少年守护弹窗'")
    # asserts 3 and 4 must sit AFTER assert 2 and BEFORE the step-5 tap / assert 5
    assert i2 < i3 < i4 < i5tap < i5


def test_known_dialog_actions_wireless_data_precedes_generic_wlan():
    """使用无线数据弹窗的 source 含'无线局域网'(仅无线局域网按钮),必须先命中专用条目
    点'无线局域网与蜂窝网络',否则通用('无线局域网','允许')先匹配、点不到'允许'而失败。"""
    actions = orchestrate._KNOWN_DIALOG_TEXT_ACTIONS
    markers = [m for m, _ in actions]
    assert ("使用无线数据", "无线局域网与蜂窝网络") in actions
    assert markers.index("使用无线数据") < markers.index("无线局域网")


def test_ios_handle_known_dialogs_taps_wireless_and_cellular(monkeypatch):
    dialog_src = '允许"高途"使用无线数据？ 无线局域网与蜂窝网络 仅无线局域网'
    dismissed_src = "首页 发现"
    state = {"src": dialog_src}
    clicked = []

    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_create_session",
                        lambda port, bundle_id: "sid")
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_get_source",
                        lambda port, sid: state["src"])

    def fake_find(port, sid, by, value):
        # 只有真实存在的按钮"无线局域网与蜂窝网络"能定位到;"允许"不存在
        return "el" if value == "无线局域网与蜂窝网络" and value in state["src"] else ""

    def fake_click(port, sid, el):
        clicked.append(el)
        state["src"] = dismissed_src   # 点击后弹窗消失
        return True

    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_find_element", fake_find)
    monkeypatch.setattr(orchestrate.orch_case_runtime_ios, "_click_element", fake_click)

    runtime = orchestrate.orch_case_runtime_ios.script_runtime_context(
        "i1", 8100, "com.gaotu100.superclass",
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        run_flow_fn=orchestrate._run_flow,
        known_dialog_text_actions=orchestrate._KNOWN_DIALOG_TEXT_ACTIONS,
    )

    assert runtime["handle_known_dialogs"]({}) is True
    assert clicked == ["el"]   # 点了'无线局域网与蜂窝网络',没有因'允许'失败


def test_ios_handle_known_dialogs_dismisses_system_alert_via_alert_api(monkeypatch):
    """iOS 系统弹窗不在 page_source,必须走 alert API;按 alert 文案选按钮名 accept。"""
    ios = orchestrate.orch_case_runtime_ios
    alert_state = {"text": '允许"高途"使用无线数据？\n关闭无线数据时…'}
    accepts = []

    monkeypatch.setattr(ios, "_create_session", lambda port, bundle_id: "sid")
    # page_source 里没有该系统弹窗文案(应用内是首页)
    monkeypatch.setattr(ios, "_get_source", lambda port, sid: "首页 发现")
    monkeypatch.setattr(ios, "_alert_text", lambda port, sid: alert_state["text"])

    def fake_accept(port, sid, name=None):
        accepts.append(name)
        alert_state["text"] = ""   # 点掉后无 alert
        return True
    monkeypatch.setattr(ios, "_accept_alert", fake_accept)

    runtime = ios.script_runtime_context(
        "i1", 8100, "com.gaotu100.superclass",
        assert_evidence_present_fn=lambda runtime, method, evidence: True,
        run_prepare_state_fn=lambda udid, step, runtime: True,
        run_flow_fn=orchestrate._run_flow,
        known_dialog_text_actions=orchestrate._KNOWN_DIALOG_TEXT_ACTIONS,
    )

    assert runtime["handle_known_dialogs"]({}) is True
    assert accepts == ["无线局域网与蜂窝网络"]   # 按文案选对了按钮


def test_ios_alert_helpers_exist():
    ios = orchestrate.orch_case_runtime_ios
    assert callable(getattr(ios, "_alert_text", None))
    assert callable(getattr(ios, "_accept_alert", None))


# --- prune_old_packages 跨平台竞态回归 (iOS run 误删安卓在下的 apk) ---

def _touch(path):
    with open(path, "w") as f:
        f.write("x")

def test_prune_ios_run_keeps_sibling_apk(tmp_path):
    """iOS run(仅 platforms=ios)绝不能删同 App 的 .apk（并发安卓 run 正在下）。"""
    app = "prunetestios"
    try:
        _touch(f"/tmp/{app}_5.91.93.apk")   # 安卓并发 run 当前版本包
        _touch(f"/tmp/{app}_5.91.90.ipa")   # iOS 历史版本，应被删
        _touch(f"/tmp/{app}_5.91.92.ipa")   # iOS 当前版本，应保留
        _REAL_PRUNE(app, "5.91.92", {"ios"})
        assert os.path.exists(f"/tmp/{app}_5.91.93.apk"), "iOS run 误删了安卓 apk"
        assert os.path.exists(f"/tmp/{app}_5.91.92.ipa"), "当前版本 ipa 被误删"
        assert not os.path.exists(f"/tmp/{app}_5.91.90.ipa"), "历史 ipa 未清理"
    finally:
        for p in glob.glob(f"/tmp/{app}_*"):
            os.remove(p)

def test_prune_android_run_only_touches_apk(tmp_path):
    """android run(仅 platforms=android)只清 apk,不碰 ipa。"""
    app = "prunetestand"
    try:
        _touch(f"/tmp/{app}_5.91.90.apk")   # 历史 apk,应删
        _touch(f"/tmp/{app}_5.91.93.apk")   # 当前 apk,应留
        _touch(f"/tmp/{app}_5.91.92.ipa")   # iOS 并发 run 包,不能碰
        _REAL_PRUNE(app, "5.91.93", {"android"})
        assert not os.path.exists(f"/tmp/{app}_5.91.90.apk"), "历史 apk 未清理"
        assert os.path.exists(f"/tmp/{app}_5.91.93.apk"), "当前 apk 被误删"
        assert os.path.exists(f"/tmp/{app}_5.91.92.ipa"), "android run 误碰了 ipa"
    finally:
        for p in glob.glob(f"/tmp/{app}_*"):
            os.remove(p)

def test_prune_no_platforms_fallback_prunes_both(tmp_path):
    """platforms 为空时兜底:两种扩展名都清理历史、保留当前版本。"""
    app = "prunetestboth"
    try:
        _touch(f"/tmp/{app}_5.91.90.apk")
        _touch(f"/tmp/{app}_5.91.90.ipa")
        _touch(f"/tmp/{app}_5.91.93.apk")
        _touch(f"/tmp/{app}_5.91.93.ipa")
        _REAL_PRUNE(app, "5.91.93")
        assert not os.path.exists(f"/tmp/{app}_5.91.90.apk")
        assert not os.path.exists(f"/tmp/{app}_5.91.90.ipa")
        assert os.path.exists(f"/tmp/{app}_5.91.93.apk")
        assert os.path.exists(f"/tmp/{app}_5.91.93.ipa")
    finally:
        for p in glob.glob(f"/tmp/{app}_*"):
            os.remove(p)
