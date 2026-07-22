# Orchestrator 执行器双适配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `scripts/orchestrate.py` 同时支持 `claude` 与 `codex` 两种设备执行器，默认使用 `codex`，保留 Claude skill 注入能力，并为 Codex 注入共享执行上下文。

**Architecture:** 在 orchestrator 中新增 runner 解析、命令构造、共享执行上下文拼装与中性日志路径四个小能力。Claude 路径继续使用 `--add-dir` 注入 skill 与 `common/`，Codex 路径改为直接消费共享执行上下文，结果收集与报告链路保持不变。

**Tech Stack:** Python 3、pytest、subprocess、环境变量配置、现有 webhook/orchestrate 流程

---

## 文件结构与职责

- `scripts/orchestrate.py`
  负责 runner 选择、prompt 组装、子进程启动、日志路径管理、结果收集。
- `scripts/tests/test_orchestrate.py`
  负责 runner 选择、命令构造、共享上下文注入、日志路径与错误处理的单元测试。
- `README.md`
  负责记录默认 runner、环境变量切换方式，以及 Claude/Codex 的注入差异。
- `deploy/launchd/com.gaotu.appium-matrix.webhook.plist`
  负责托管服务的显式环境变量配置。

### Task 1: 为 runner 选择补测试护栏

**Files:**
- Modify: `scripts/tests/test_orchestrate.py`
- Test: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: 写默认 runner 为 codex 的失败测试**

```python
def test_resolve_agent_runner_defaults_to_codex(monkeypatch):
    monkeypatch.delenv("ORCH_AGENT_CLI", raising=False)
    assert orchestrate.resolve_agent_runner() == "codex"
```

- [ ] **Step 2: 运行单测确认失败**

Run: `pytest scripts/tests/test_orchestrate.py::test_resolve_agent_runner_defaults_to_codex -v`
Expected: FAIL，提示 `orchestrate` 中不存在 `resolve_agent_runner`

- [ ] **Step 3: 写显式 claude 回退的失败测试**

```python
def test_resolve_agent_runner_accepts_claude(monkeypatch):
    monkeypatch.setenv("ORCH_AGENT_CLI", "claude")
    assert orchestrate.resolve_agent_runner() == "claude"
```

- [ ] **Step 4: 运行单测确认失败**

Run: `pytest scripts/tests/test_orchestrate.py::test_resolve_agent_runner_accepts_claude -v`
Expected: FAIL，提示 `resolve_agent_runner` 不存在

- [ ] **Step 5: 写非法 runner 抛错的失败测试**

```python
import pytest

def test_resolve_agent_runner_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("ORCH_AGENT_CLI", "unknown")
    with pytest.raises(ValueError, match="ORCH_AGENT_CLI"):
        orchestrate.resolve_agent_runner()
```

- [ ] **Step 6: 运行单测确认失败**

Run: `pytest scripts/tests/test_orchestrate.py::test_resolve_agent_runner_rejects_unknown_value -v`
Expected: FAIL，提示 `resolve_agent_runner` 不存在

- [ ] **Step 7: 写最小实现让测试通过**

```python
def resolve_agent_runner() -> str:
    value = os.environ.get("ORCH_AGENT_CLI", "").strip().lower() or "codex"
    if value not in {"codex", "claude"}:
        raise ValueError("ORCH_AGENT_CLI must be one of: codex, claude")
    return value
```

- [ ] **Step 8: 运行三条单测确认通过**

Run: `pytest scripts/tests/test_orchestrate.py::test_resolve_agent_runner_defaults_to_codex scripts/tests/test_orchestrate.py::test_resolve_agent_runner_accepts_claude scripts/tests/test_orchestrate.py::test_resolve_agent_runner_rejects_unknown_value -v`
Expected: 3 passed

- [ ] **Step 9: 提交**

```bash
git add scripts/orchestrate.py scripts/tests/test_orchestrate.py
git commit -m "test: cover orchestrator runner resolution"
```

### Task 2: 为日志路径与命令构造补测试并实现

**Files:**
- Modify: `scripts/orchestrate.py`
- Modify: `scripts/tests/test_orchestrate.py`
- Test: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: 写中性日志路径的失败测试**

```python
def test_agent_log_path_uses_neutral_name():
    assert orchestrate.agent_log_path("device1") == "/tmp/agent_device1.log"
```

- [ ] **Step 2: 运行单测确认失败**

Run: `pytest scripts/tests/test_orchestrate.py::test_agent_log_path_uses_neutral_name -v`
Expected: FAIL，提示 `agent_log_path` 不存在

- [ ] **Step 3: 写 Claude 命令构造的失败测试**

```python
def test_build_agent_command_for_claude_includes_add_dir(tmp_path):
    skill_dir = str(tmp_path / "skills")
    common_dir = str(tmp_path / "common")
    cmd = orchestrate.build_agent_command(
        runner="claude",
        prompt="run cases",
        skill_dir=skill_dir,
        common_dir=common_dir,
    )
    assert cmd[:5] == ["claude", "--add-dir", skill_dir, "--add-dir", common_dir]
    assert cmd[-2:] == ["--print", "run cases"]
```

- [ ] **Step 4: 运行单测确认失败**

Run: `pytest scripts/tests/test_orchestrate.py::test_build_agent_command_for_claude_includes_add_dir -v`
Expected: FAIL，提示 `build_agent_command` 不存在

- [ ] **Step 5: 写 Codex 命令构造的失败测试**

```python
def test_build_agent_command_for_codex_does_not_use_add_dir(tmp_path):
    cmd = orchestrate.build_agent_command(
        runner="codex",
        prompt="run cases",
        skill_dir=str(tmp_path / "skills"),
        common_dir=str(tmp_path / "common"),
    )
    assert cmd[0] == "codex"
    assert "--add-dir" not in cmd
```

- [ ] **Step 6: 运行单测确认失败**

Run: `pytest scripts/tests/test_orchestrate.py::test_build_agent_command_for_codex_does_not_use_add_dir -v`
Expected: FAIL，提示 `build_agent_command` 不存在

- [ ] **Step 7: 写最小实现让三条测试通过**

```python
def agent_log_path(udid: str) -> str:
    return f"/tmp/agent_{udid}.log"


def build_agent_command(runner: str, prompt: str, skill_dir: str, common_dir: str) -> list:
    if runner == "claude":
        return ["claude", "--add-dir", skill_dir, "--add-dir", common_dir, "--print", prompt]
    if runner == "codex":
        return ["codex", "exec", prompt]
    raise ValueError(f"Unsupported runner: {runner}")
```

- [ ] **Step 8: 运行三条单测确认通过**

Run: `pytest scripts/tests/test_orchestrate.py::test_agent_log_path_uses_neutral_name scripts/tests/test_orchestrate.py::test_build_agent_command_for_claude_includes_add_dir scripts/tests/test_orchestrate.py::test_build_agent_command_for_codex_does_not_use_add_dir -v`
Expected: 3 passed

- [ ] **Step 9: 提交**

```bash
git add scripts/orchestrate.py scripts/tests/test_orchestrate.py
git commit -m "feat: add runner-specific command builder"
```

### Task 3: 为共享执行上下文补测试并接入 prompt

**Files:**
- Modify: `scripts/orchestrate.py`
- Modify: `scripts/tests/test_orchestrate.py`
- Test: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: 写共享执行上下文存在性的失败测试**

```python
def test_build_shared_execution_context_contains_common_rules():
    context = orchestrate.build_shared_execution_context("gaotu")
    assert "common/elements/login.md" in context
    assert "common/device.md" in context
```

- [ ] **Step 2: 运行单测确认失败**

Run: `pytest scripts/tests/test_orchestrate.py::test_build_shared_execution_context_contains_common_rules -v`
Expected: FAIL，提示 `build_shared_execution_context` 不存在

- [ ] **Step 3: 写 prompt 注入共享上下文的失败测试**

```python
def test_build_prompt_includes_shared_execution_context(monkeypatch):
    monkeypatch.setattr(orchestrate, "build_shared_execution_context", lambda app_id: "共享上下文片段")
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "共享上下文片段" in prompt
```

- [ ] **Step 4: 运行单测确认失败**

Run: `pytest scripts/tests/test_orchestrate.py::test_build_prompt_includes_shared_execution_context -v`
Expected: FAIL，因为 `build_prompt` 尚未包含共享上下文

- [ ] **Step 5: 写最小实现让测试通过**

```python
def build_shared_execution_context(app_id: str) -> str:
    parts = [
        "执行前必须读取以下文件：",
        "- common/elements/login.md",
        "- common/elements/dialog.md",
        "- common/screenshot.md",
        "- common/device.md",
        "- common/locator.md",
    ]
    if app_id == "gaotu":
        parts.append("- .claude/skills/gaotu/elements.md")
    return "\n".join(parts)
```

并在 `build_prompt(...)` 的开头拼接：

```python
shared_context = build_shared_execution_context(app_id)
prompt = f"{shared_context}\n\n{prompt}"
```

- [ ] **Step 6: 运行两条单测确认通过**

Run: `pytest scripts/tests/test_orchestrate.py::test_build_shared_execution_context_contains_common_rules scripts/tests/test_orchestrate.py::test_build_prompt_includes_shared_execution_context -v`
Expected: 2 passed

- [ ] **Step 7: 提交**

```bash
git add scripts/orchestrate.py scripts/tests/test_orchestrate.py
git commit -m "feat: add shared execution context for codex"
```

### Task 4: 切换启动流程到 runner-neutral 执行器

**Files:**
- Modify: `scripts/orchestrate.py`
- Modify: `scripts/tests/test_orchestrate.py`
- Test: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: 写启动流程默认走 codex 的失败测试**

```python
def test_launch_agent_per_device_uses_resolved_runner(monkeypatch):
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
    monkeypatch.setattr(orchestrate.subprocess, "Popen", fake_popen)
    orchestrate.launch_agent_per_device("gaotu", entries, version="5.91.90")
    assert popen_calls[0][0] == "codex"
```

- [ ] **Step 2: 运行单测确认失败**

Run: `pytest scripts/tests/test_orchestrate.py::test_launch_agent_per_device_uses_resolved_runner -v`
Expected: FAIL，提示 `launch_agent_per_device` 不存在

- [ ] **Step 3: 写 Claude 启动流程保留 add-dir 的失败测试**

```python
def test_launch_agent_per_device_preserves_claude_add_dir(monkeypatch):
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
    monkeypatch.setattr(orchestrate.subprocess, "Popen", fake_popen)
    orchestrate.launch_agent_per_device("gaotu", entries, version="5.91.90")
    assert "--add-dir" in popen_calls[0]
```

- [ ] **Step 4: 运行单测确认失败**

Run: `pytest scripts/tests/test_orchestrate.py::test_launch_agent_per_device_preserves_claude_add_dir -v`
Expected: FAIL，提示 `launch_agent_per_device` 不存在

- [ ] **Step 5: 实现 runner-neutral 启动函数并替换调用点**

```python
def launch_agent_per_device(app_id: str, groups: dict, wda_ports: dict = None, version: str = None) -> dict:
    runner = resolve_agent_runner()
    wda_ports = wda_ports or {}
    procs = {}
    skill_dir = os.path.join(PROJECT_ROOT, ".claude", "skills", app_id)
    common_dir = os.path.join(PROJECT_ROOT, "common")

    for udid, group in groups.items():
        prompt = build_prompt(app_id, udid, group["platform"], group["entries"],
                              wda_port=wda_ports.get(udid), version=version)
        log_path = agent_log_path(udid)
        cmd = build_agent_command(runner, prompt, skill_dir, common_dir)
        with open(log_path, "w") as logf:
            proc = subprocess.Popen(cmd, stdout=logf, stderr=logf)
        procs[udid] = proc
    return procs
```

并将原调用点：

```python
procs = launch_claude_per_device(...)
```

替换为：

```python
procs = launch_agent_per_device(...)
```

- [ ] **Step 6: 运行两条单测确认通过**

Run: `pytest scripts/tests/test_orchestrate.py::test_launch_agent_per_device_uses_resolved_runner scripts/tests/test_orchestrate.py::test_launch_agent_per_device_preserves_claude_add_dir -v`
Expected: 2 passed

- [ ] **Step 7: 提交**

```bash
git add scripts/orchestrate.py scripts/tests/test_orchestrate.py
git commit -m "feat: switch orchestrator to configurable agent runner"
```

### Task 5: 更新 crash-tail 路径与文档配置

**Files:**
- Modify: `scripts/orchestrate.py`
- Modify: `README.md`
- Modify: `deploy/launchd/com.gaotu.appium-matrix.webhook.plist`
- Test: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: 写 crash-tail 使用新日志路径的失败测试**

```python
def test_collect_results_reads_agent_log_tail(tmp_path):
    udid = "dev_crash"
    proc = _FakeProc([1], returncode=1)
    (tmp_path / f"agent_{udid}.log").write_text("runner failed")
    with patch("orchestrate._notify"):
        results = orchestrate.collect_results(
            {udid: proc}, result_dir=str(tmp_path), timeout=1, poll_interval=0.02,
            app_id="gaotu", version="9.9.9", run_id="r_test")
    assert results[udid] == "failed"
```

- [ ] **Step 2: 运行单测确认失败**

Run: `pytest scripts/tests/test_orchestrate.py::test_collect_results_reads_agent_log_tail -v`
Expected: FAIL，因为当前 tail 仍读取 `/tmp/claude_<udid>.log`

- [ ] **Step 3: 修改结果收集逻辑统一走 `agent_log_path()`**

```python
tail = _tail_file(agent_log_path(udid))
```

将 `collect_results()` 中所有旧的 `"/tmp/claude_{udid}.log"` 引用替换为 `agent_log_path(udid)`。

- [ ] **Step 4: 更新 README 文档**

补充说明：

```md
- 新增环境变量 `ORCH_AGENT_CLI`，支持 `codex` / `claude`
- 默认值为 `codex`
- `claude` 仍使用 `.claude/skills/<app>` + `common/` 注入
- `codex` 使用 orchestrator 生成的共享执行上下文
```

- [ ] **Step 5: 更新 launchd 配置**

在 plist 的环境变量区域加入：

```xml
<key>ORCH_AGENT_CLI</key>
<string>codex</string>
```

- [ ] **Step 6: 运行目标单测确认通过**

Run: `pytest scripts/tests/test_orchestrate.py::test_collect_results_reads_agent_log_tail -v`
Expected: 1 passed

- [ ] **Step 7: 运行完整测试文件确认通过**

Run: `pytest scripts/tests/test_orchestrate.py -v`
Expected: 全部通过

- [ ] **Step 8: 提交**

```bash
git add scripts/orchestrate.py scripts/tests/test_orchestrate.py README.md deploy/launchd/com.gaotu.appium-matrix.webhook.plist
git commit -m "docs: document dual runner orchestrator setup"
```

## Self-Review

- Spec coverage:
  - runner 可配置：Task 1、Task 4
  - 默认 codex / 回退 claude：Task 1、Task 2、Task 4
  - Claude skill 保留：Task 2、Task 4
  - Codex 共享上下文：Task 3
  - 中性日志与 crash tail：Task 2、Task 5
  - 文档与 launchd 配置：Task 5
- Placeholder scan:
  - 已避免使用 TBD / TODO / “自行实现”
- Type consistency:
  - 统一使用 `resolve_agent_runner`、`build_agent_command`、`build_shared_execution_context`、`agent_log_path`、`launch_agent_per_device`

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-09-orchestrator-agent-runner.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
