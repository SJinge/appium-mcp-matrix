# Auto-Release CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 飞书群消息触发发版后，自动在 4 台 Android + 4 台 iOS 上批量执行 Bitable 标记用例，生成双端 Wiki 报告并发送飞书群通知。

**Architecture:** Flask server（云端）接收飞书 Webhook，SSH 触发 Mac 端 `orchestrate.py` 后台运行；orchestrate.py 安装包、可选探索 App、读 Bitable 过滤用例、并行启动 8 个 claude CLI 进程执行，收集结果后生成报告。

**Tech Stack:** Python 3.11, Flask 3.x, pytest, PyYAML, subprocess

**Specs:**
- [发版自动触发设计](../specs/2026-05-27-auto-release-ci-design.md)
- [APK探索驱动设计](../specs/2026-05-26-apk-exploration-design.md)

---

## File Structure

| 文件 | 动作 | 职责 |
|------|------|------|
| `server/app.py` | 新建 | Flask webhook 服务 |
| `server/requirements.txt` | 新建 | Flask 依赖 |
| `server/tests/test_app.py` | 新建 | Flask 单元测试 |
| `scripts/orchestrate.py` | 新建 | Mac 端编排主控 |
| `scripts/tests/test_orchestrate.py` | 新建 | orchestrate 单元测试 |
| `config/devices.yaml` | 新建 | 每个 App 的 8 台设备 UDID |
| `scripts/feishu_config.py` | 修改 | 追加 BITABLE_CONFIGS（每个 App 的 app_token + table_id） |
| `scripts/wiki_report.py:36` | 修改 | `--account` required=True → default="多账号" |

---

## Part A：前置准备

### Task 1：wiki_report.py —— 让 --account 可选

**Files:**
- Modify: `scripts/wiki_report.py:36`

- [ ] **Step 1: 修改 --account 参数**

```python
# scripts/wiki_report.py 第36行，将
p.add_argument("--account",   required=True)
# 改为
p.add_argument("--account",   default="多账号")
```

- [ ] **Step 2: 验证改动不破坏现有调用**

```bash
cd /Users/mac/Documents/projects/appium-mcp-matrix
python3 scripts/wiki_report.py --version 1.0.0 --platform Android \
  --time "10:00" --duration "60s" \
  --total 1 --passed 1 --failed 0 --rate 100 \
  --no-notify
```

预期：脚本正常运行不报错（可能因缺少真实 token 而失败，但不应因 --account 报错）

- [ ] **Step 3: Commit**

```bash
git add scripts/wiki_report.py
git commit -m "fix: make --account optional in wiki_report (batch execution has no single account)"
```

---

### Task 2：~~Bitable 添加字段~~ —— 已跳过

> Bitable 用例表中已存在 **"是否是否执行自动化"** 列（Checkbox），无需新建。
> Task 7 的过滤字段名统一使用 `是否是否执行自动化`。

---

### Task 3：config/devices.yaml + feishu_config.py Bitable 配置

**Files:**
- Create: `config/devices.yaml`
- Modify: `scripts/feishu_config.py`

- [ ] **Step 1: 创建 config/devices.yaml**

```yaml
# 每个 app 可覆盖，留空则继承 default
default:
  android:
    - udid: "ANDROID_UDID_1"
      name: "Android设备1"
    - udid: "ANDROID_UDID_2"
      name: "Android设备2"
    - udid: "ANDROID_UDID_3"
      name: "Android设备3"
    - udid: "ANDROID_UDID_4"
      name: "Android设备4"
  ios:
    - udid: "IOS_UDID_1"
      name: "iOS设备1"
    - udid: "IOS_UDID_2"
      name: "iOS设备2"
    - udid: "IOS_UDID_3"
      name: "iOS设备3"
    - udid: "IOS_UDID_4"
      name: "iOS设备4"
```

将占位符替换为真实 UDID（Android 用 `adb devices` 查，iOS 用 `tidevice list` 查）。

- [ ] **Step 2: 追加 BITABLE_CONFIGS 到 feishu_config.py**

```python
# 追加到 scripts/feishu_config.py 末尾
BITABLE_CONFIGS = {
    "gaotu": {
        "app_token": "<从Bitable URL获取>",
        "table_id":  "<从Bitable URL获取>",
    },
    "tutu": {
        "app_token": "",
        "table_id":  "",
    },
    "jingpin": {
        "app_token": "",
        "table_id":  "",
    },
    "gongkao": {
        "app_token": "",
        "table_id":  "",
    },
    "xinli": {
        "app_token": "",
        "table_id":  "",
    },
    "ketang": {
        "app_token": "",
        "table_id":  "",
    },
}
```

从各 App 的 Bitable URL 提取 `app_token` 和 `table_id` 填入。

- [ ] **Step 3: Commit**

```bash
git add config/devices.yaml scripts/feishu_config.py
git commit -m "config: add devices.yaml and Bitable configs per app"
```

---

## Part B：Flask Webhook 服务

### Task 4：消息解析（TDD）

**Files:**
- Create: `server/tests/test_app.py`
- Create: `server/app.py`（仅解析逻辑，不含 SSH）

- [ ] **Step 1: 创建测试文件**

```python
# server/tests/test_app.py
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
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd /Users/mac/Documents/projects/appium-mcp-matrix
pip install pytest flask --quiet
pytest server/tests/test_app.py -v 2>&1 | head -20
```

预期：`ImportError` 或 `ModuleNotFoundError`（app.py 不存在）

- [ ] **Step 3: 创建 server/app.py 实现解析**

```python
# server/app.py
import re, json, os, subprocess
from flask import Flask, request, jsonify

app = Flask(__name__)

APP_IDS = {"gaotu", "tutu", "jingpin", "gongkao", "xinli", "ketang"}
_MSG_RE = re.compile(
    r'(?P<app>' + '|'.join(APP_IDS) + r')\s+'
    r'(?P<version>\d+\.\d+(?:\.\d+)?)\s+'
    r'android:(?P<apk_url>https?://\S+)\s+'
    r'ios:(?P<ipa_url>https?://\S+)',
    re.IGNORECASE
)

def parse_message(text: str) -> dict | None:
    m = _MSG_RE.search(text)
    if not m:
        return None
    return {
        "app_id":  m.group("app").lower(),
        "version": m.group("version"),
        "apk_url": m.group("apk_url"),
        "ipa_url": m.group("ipa_url"),
    }
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest server/tests/test_app.py -v
```

预期：4 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/tests/test_app.py
git commit -m "feat: Flask webhook message parser with tests"
```

---

### Task 5：Flask Webhook 路由 + SSH 触发

**Files:**
- Modify: `server/app.py`
- Modify: `server/tests/test_app.py`

- [ ] **Step 1: 追加 webhook 路由测试**

```python
# 追加到 server/tests/test_app.py
from unittest.mock import patch, MagicMock
from app import app as flask_app

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    return flask_app.test_client()

def test_url_verification(client):
    resp = client.post("/webhook/feishu",
        json={"type": "url_verification", "challenge": "abc123"},
        content_type="application/json")
    assert resp.status_code == 200
    assert resp.get_json()["challenge"] == "abc123"

def test_non_text_message_ignored(client):
    payload = {"event": {"message": {"message_type": "image"}, "sender": {}}}
    resp = client.post("/webhook/feishu", json=payload)
    assert resp.status_code == 200

def test_bot_message_ignored(client):
    payload = {"event": {
        "message": {"message_type": "text", "content": '{"text":"gaotu 1.0 android:https://a.apk ios:https://b.ipa"}'},
        "sender": {"sender_type": "app"}
    }}
    resp = client.post("/webhook/feishu", json=payload)
    assert resp.status_code == 200

@patch("app.ssh_trigger")
@patch("app.is_running", return_value=False)
def test_valid_message_triggers_ssh(mock_running, mock_ssh, client):
    mock_ssh.return_value = True
    payload = {"event": {
        "message": {"message_type": "text",
                    "content": '{"text":"gaotu 5.91 android:https://a.apk ios:https://b.ipa"}'},
        "sender": {"sender_type": "user"}
    }}
    resp = client.post("/webhook/feishu", json=payload)
    assert resp.status_code == 200
    mock_ssh.assert_called_once_with("gaotu", "5.91",
                                      "https://a.apk", "https://b.ipa")

@patch("app.ssh_trigger")
@patch("app.is_running", return_value=True)
def test_duplicate_trigger_rejected(mock_running, mock_ssh, client):
    payload = {"event": {
        "message": {"message_type": "text",
                    "content": '{"text":"gaotu 5.91 android:https://a.apk ios:https://b.ipa"}'},
        "sender": {"sender_type": "user"}
    }}
    client.post("/webhook/feishu", json=payload)
    mock_ssh.assert_not_called()
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest server/tests/test_app.py -v 2>&1 | tail -15
```

预期：新增测试 FAILED（`ssh_trigger`、`is_running`、路由不存在）

- [ ] **Step 3: 实现路由和 SSH 函数**

```python
# 追加到 server/app.py

MAC_HOST        = os.environ.get("MAC_HOST", "")
MAC_USER        = os.environ.get("MAC_USER", "")
MAC_KEY         = os.environ.get("MAC_KEY", os.path.expanduser("~/.ssh/id_rsa"))
ORCHESTRATE_PATH = os.environ.get("ORCHESTRATE_PATH",
                                   "/Users/mac/Documents/projects/appium-mcp-matrix/scripts/orchestrate.py")

def is_running(app_id: str, version: str) -> bool:
    pid_file = f"/tmp/orchestrate_{app_id}_{version}.pid"
    result = subprocess.run(
        ["ssh", "-i", MAC_KEY, "-o", "ConnectTimeout=5",
         f"{MAC_USER}@{MAC_HOST}",
         f"[ -f {pid_file} ] && ps -p $(cat {pid_file}) > /dev/null 2>&1 && echo running || echo idle"],
        capture_output=True, text=True, timeout=10
    )
    return "running" in result.stdout

def ssh_trigger(app_id: str, version: str, apk_url: str, ipa_url: str) -> bool:
    log = f"/tmp/orchestrate_{app_id}_{version}.log"
    pid_file = f"/tmp/orchestrate_{app_id}_{version}.pid"
    cmd = (
        f"nohup python3 {ORCHESTRATE_PATH} "
        f"--app {app_id} --version '{version}' "
        f"--apk-url '{apk_url}' --ipa-url '{ipa_url}' "
        f"> {log} 2>&1 & echo $! | tee {pid_file}"
    )
    result = subprocess.run(
        ["ssh", "-i", MAC_KEY, "-o", "ConnectTimeout=5",
         f"{MAC_USER}@{MAC_HOST}", cmd],
        capture_output=True, text=True, timeout=15
    )
    return result.returncode == 0

def _feishu_reply(chat_id: str, text: str):
    import urllib.request
    from scripts.feishu_config import APP_ID, APP_SECRET  # noqa: F401
    # 复用 wiki_report.py 的 get_token / feishu 函数逻辑
    pass  # 在 Task 6 实现

@app.route("/webhook/feishu", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    if data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    event = data.get("event", {})
    msg   = event.get("message", {})
    sender = event.get("sender", {})

    if msg.get("message_type") != "text":
        return "ok"
    if sender.get("sender_type") == "app":
        return "ok"

    text = json.loads(msg.get("content", "{}")).get("text", "")
    parsed = parse_message(text)
    if not parsed:
        return "ok"

    app_id, version = parsed["app_id"], parsed["version"]

    if is_running(app_id, version):
        return "ok"

    ssh_trigger(app_id, version, parsed["apk_url"], parsed["ipa_url"])
    return "ok"
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest server/tests/test_app.py -v
```

预期：全部 PASSED

- [ ] **Step 5: 创建 requirements.txt**

```
# server/requirements.txt
flask>=3.0
pytest>=8.0
```

- [ ] **Step 6: Commit**

```bash
git add server/app.py server/tests/test_app.py server/requirements.txt
git commit -m "feat: Flask webhook route with SSH trigger and duplicate guard"
```

---

## Part C：orchestrate.py

### Task 6：CLI 骨架 + 安装阶段

**Files:**
- Create: `scripts/orchestrate.py`
- Create: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: 创建测试文件（安装阶段）**

```python
# scripts/tests/test_orchestrate.py
import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import patch, call
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
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd /Users/mac/Documents/projects/appium-mcp-matrix
pytest scripts/tests/test_orchestrate.py -v 2>&1 | head -20
```

预期：ImportError（orchestrate.py 不存在）

- [ ] **Step 3: 创建 orchestrate.py 骨架 + 安装函数**

```python
#!/usr/bin/env python3
# scripts/orchestrate.py
import argparse, json, os, subprocess, sys, time, yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
from feishu_config import APP_ID, APP_SECRET, GROUP_CHAT_ID, BITABLE_CONFIGS

PKG_NAMES = {
    "gaotu":   "com.gaotu100.superclass",
    "tutu":    "com.gaotu100.tutu",
    "jingpin": "com.gaotu100.jingpin",
    "gongkao": "com.gaotu100.gongkao",
    "xinli":   "com.gaotu100.xinli",
    "ketang":  "com.gaotu100.ketang",
}

def load_devices(app_id: str, config_path: str = None) -> dict:
    if config_path is None:
        config_path = os.path.join(PROJECT_ROOT, "config", "devices.yaml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return cfg.get(app_id, cfg["default"])

def extract_version_android(pkg: str) -> str:
    r = subprocess.run(
        ["adb", "shell", "dumpsys", "package", pkg],
        capture_output=True, text=True
    )
    for line in r.stdout.splitlines():
        if "versionName=" in line:
            return line.strip().split("=", 1)[1].strip()
    return "unknown"

def install_android(apk_path: str, udid: str) -> bool:
    r = subprocess.run(
        ["adb", "-s", udid, "install", "-r", apk_path],
        capture_output=True, text=True
    )
    return r.returncode == 0

def install_ios(ipa_path: str, udid: str) -> bool:
    r = subprocess.run(
        ["tidevice", "-u", udid, "install", ipa_path],
        capture_output=True, text=True
    )
    return "Complete" in r.stdout

def download_file(url: str, dest: str) -> bool:
    r = subprocess.run(["curl", "-L", "-o", dest, url], capture_output=True)
    return r.returncode == 0 and os.path.getsize(dest) > 1_000_000

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--app",      required=True)
    p.add_argument("--version",  required=True)
    p.add_argument("--apk-url",  required=True, dest="apk_url")
    p.add_argument("--ipa-url",  required=True, dest="ipa_url")
    return p.parse_args()

def main():
    args    = parse_args()
    app_id  = args.app
    version = args.version

    pid_file = f"/tmp/orchestrate_{app_id}_{version}.pid"
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    try:
        _run(app_id, version, args.apk_url, args.ipa_url)
    finally:
        if os.path.exists(pid_file):
            os.remove(pid_file)

def _run(app_id, version, apk_url, ipa_url):
    devices = load_devices(app_id)

    # 1. 下载
    apk_path = f"/tmp/{app_id}_{version}.apk"
    ipa_path = f"/tmp/{app_id}_{version}.ipa"
    print(f"[INFO] 下载 APK: {apk_url}")
    if not download_file(apk_url, apk_path):
        _notify(app_id, version, "❌ APK 下载失败，终止")
        return
    print(f"[INFO] 下载 IPA: {ipa_url}")
    if not download_file(ipa_url, ipa_path):
        _notify(app_id, version, "❌ IPA 下载失败，终止")
        return

    # 2. 安装
    android_ok, ios_ok = [], []
    for d in devices["android"]:
        if install_android(apk_path, d["udid"]):
            android_ok.append(d)
            print(f"[INFO] Android {d['udid']} 安装成功")
        else:
            print(f"[WARN] Android {d['udid']} 安装失败，跳过")

    for d in devices["ios"]:
        if install_ios(ipa_path, d["udid"]):
            ios_ok.append(d)
            print(f"[INFO] iOS {d['udid']} 安装成功")
        else:
            print(f"[WARN] iOS {d['udid']} 安装失败，跳过")

    if not android_ok and not ios_ok:
        _notify(app_id, version, "❌ 所有设备安装失败，终止")
        return

    print(f"[INFO] 安装完成：Android {len(android_ok)} 台，iOS {len(ios_ok)} 台")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pip install pyyaml --quiet
pytest scripts/tests/test_orchestrate.py -v
```

预期：3 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrate.py scripts/tests/test_orchestrate.py
git commit -m "feat: orchestrate.py skeleton with install phase and tests"
```

---

### Task 7：Bitable 读取 + 过滤 + 设备分组

**Files:**
- Modify: `scripts/orchestrate.py`
- Modify: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: 追加测试**

```python
# 追加到 scripts/tests/test_orchestrate.py
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
            "Android设备": [{"text": "a1", "type": "text"}],
            "ios设备":    [{"text": "i1", "type": "text"}],
            "是否执行自动化": True,
        }
    }
    entry = orchestrate.parse_record(record)
    assert entry["record_id"] == "rec001"
    assert entry["name"] == "1 测试登录"
    assert any(s["type"] == "PRECOND" for s in entry["steps"])
    assert any(s["type"] == "ACTION"  for s in entry["steps"])
    assert any(s["type"] == "ASSERT"  for s in entry["steps"])
    assert entry["android_device"] == "a1"
    assert entry["ios_device"] == "i1"

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
    assert "" not in groups  # 空设备不入组
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest scripts/tests/test_orchestrate.py::test_parse_bitable_record \
       scripts/tests/test_orchestrate.py::test_group_by_device -v
```

预期：AttributeError（函数未定义）

- [ ] **Step 3: 实现 parse_record + fetch_cases + group_by_device**

```python
# 追加到 scripts/orchestrate.py

import urllib.request, urllib.error, datetime

def _get_token() -> str:
    data = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode()
    req  = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    return json.load(urllib.request.urlopen(req))["tenant_access_token"]

def _text_field(value) -> str:
    if isinstance(value, list):
        return "".join(item.get("text", "") for item in value)
    return str(value) if value else ""

def parse_record(record: dict) -> dict:
    fields = record["fields"]
    num    = fields.get("用例编号", "")
    name   = _text_field(fields.get("用例名称", ""))
    steps  = []

    # PRECOND
    for line in _text_field(fields.get("预置条件", "")).splitlines():
        line = line.strip()
        if line:
            steps.append({"type": "PRECOND", "text": line})

    # ACTION
    raw_steps = _text_field(fields.get("测试步骤", ""))
    for line in raw_steps.splitlines():
        line = line.strip()
        if line:
            steps.append({"type": "ACTION", "text": line})

    # ASSERT（验证点 + 预期结果）
    for line in _text_field(fields.get("验证点", "")).splitlines():
        line = line.strip()
        if line:
            steps.append({"type": "ASSERT", "text": line})
    result_text = _text_field(fields.get("预期结果", "")).strip()
    if result_text:
        steps.append({"type": "ASSERT", "text": result_text})

    return {
        "record_id":      record["record_id"],
        "name":           f"{num} {name}".strip(),
        "steps":          steps,
        "android_device": _text_field(fields.get("Android设备", "")),
        "ios_device":     _text_field(fields.get("ios设备", "")),
        "module":         _text_field(fields.get("模块", "")),
    }

def fetch_cases(app_id: str) -> list[dict]:
    cfg   = BITABLE_CONFIGS[app_id]
    token = _get_token()
    url   = (f"https://open.feishu.cn/open-apis/bitable/v1/apps"
             f"/{cfg['app_token']}/tables/{cfg['table_id']}/records/search")
    body  = json.dumps({
        "filter": {
            "conjunction": "and",
            "conditions": [{"field_name": "是否执行自动化", "operator": "is",
                            "value": ["true"]}]
        },
        "page_size": 500
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST"
    )
    resp  = json.load(urllib.request.urlopen(req))
    items = resp.get("data", {}).get("items", [])
    return [parse_record(r) for r in items]

def group_by_device(entries: list[dict]) -> dict:
    groups = {}
    for entry in entries:
        for platform, field in [("Android", "android_device"), ("iOS", "ios_device")]:
            udid = entry.get(field, "").strip()
            if not udid:
                continue
            if udid not in groups:
                groups[udid] = {"platform": platform, "entries": []}
            groups[udid]["entries"].append(entry)
    return groups
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest scripts/tests/test_orchestrate.py -v
```

预期：全部 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrate.py scripts/tests/test_orchestrate.py
git commit -m "feat: Bitable fetch, record parsing, device grouping"
```

---

### Task 8：探索阶段触发

**Files:**
- Modify: `scripts/orchestrate.py`

- [ ] **Step 1: 实现 run_exploration 函数**

```python
# 追加到 scripts/orchestrate.py

def run_exploration(app_id: str, version: str, android_udid: str):
    app_dir = os.path.join(PROJECT_ROOT, "apps", app_id)
    index_path = os.path.join(app_dir, "index.md")
    os.makedirs(app_dir, exist_ok=True)
    prompt = (
        f"探索 {app_id} App，版本 {version}，设备 {android_udid}（Android）。"
        f"广度优先遍历各 Tab 和子页面（最大深度2），"
        f"为每个页面截图并分析 UI 树，"
        f"生成 apps/{app_id}/index.md 和 pages/*.md。"
        f"见 common/device.md 了解设备就绪检查规范。"
    )
    skill_dir = os.path.join(PROJECT_ROOT, ".claude", "skills", app_id)
    common_dir = os.path.join(PROJECT_ROOT, "common")
    cmd = [
        "claude",
        "--add-dir", skill_dir,
        "--add-dir", common_dir,
        "--print", prompt
    ]
    log_path = f"/tmp/explore_{app_id}_{version}.log"
    print(f"[INFO] 开始探索，日志：{log_path}")
    try:
        with open(log_path, "w") as log:
            r = subprocess.run(cmd, stdout=log, stderr=log, timeout=1800)
        if r.returncode == 0 and os.path.exists(index_path):
            print(f"[INFO] 探索完成，index.md 已生成")
        else:
            print(f"[WARN] 探索失败或未生成 index.md，继续执行（退化为视觉定位）")
    except subprocess.TimeoutExpired:
        print(f"[WARN] 探索超时（30min），继续执行")
```

- [ ] **Step 2: 在 _run() 中插入探索步骤**

```python
# 在 _run() 函数"安装"之后、"Bitable读取"之前插入：

    # 3. 探索（新版本）
    if android_ok:
        run_exploration(app_id, version, android_ok[0]["udid"])
```

- [ ] **Step 3: 验证函数可调用（不实际执行）**

```bash
python3 -c "import sys; sys.path.insert(0,'scripts'); import orchestrate; print('OK')"
```

预期：`OK`

- [ ] **Step 4: Commit**

```bash
git add scripts/orchestrate.py
git commit -m "feat: app exploration trigger in orchestrate pipeline"
```

---

### Task 9：并行执行 + 超时保护

**Files:**
- Modify: `scripts/orchestrate.py`
- Modify: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: 追加并行执行测试**

```python
# 追加到 scripts/tests/test_orchestrate.py
import tempfile, json as _json

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
    # 结果文件不存在，应超时
    results = orchestrate.collect_results(
        {"missing_device": None},
        result_dir=str(tmp_path),
        timeout=1  # 1秒超时
    )
    assert results["missing_device"] == "timeout"
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest scripts/tests/test_orchestrate.py::test_collect_results_reads_json \
       scripts/tests/test_orchestrate.py::test_collect_results_timeout_marks_failure -v
```

预期：AttributeError

- [ ] **Step 3: 实现 build_prompt、launch_claude_per_device、collect_results**

```python
# 追加到 scripts/orchestrate.py

def build_prompt(app_id: str, udid: str, platform: str,
                 entries: list, bitable_token: str, table_id: str) -> str:
    cases_json = json.dumps(
        [{"record_id": e["record_id"], "name": e["name"],
          "module": e["module"], "steps": e["steps"]} for e in entries],
        ensure_ascii=False
    )
    return (
        f"你是{app_id} App 自动化测试工程师。\n"
        f"设备：{udid}（{platform}）\n"
        f"Bitable app_token={bitable_token} table_id={table_id}\n\n"
        f"请依次执行以下用例，每条完成后立即回写 Bitable 执行结果。\n"
        f"全部执行完成后，将结果写入 /tmp/result_{udid}.json（格式参考 common/parallel.md）。\n\n"
        f"用例列表：\n{cases_json}"
    )

def launch_claude_per_device(app_id: str, groups: dict,
                              bitable_token: str, table_id: str) -> dict:
    procs = {}
    skill_dir  = os.path.join(PROJECT_ROOT, ".claude", "skills", app_id)
    common_dir = os.path.join(PROJECT_ROOT, "common")

    for udid, group in groups.items():
        prompt   = build_prompt(app_id, udid, group["platform"],
                                group["entries"], bitable_token, table_id)
        log_path = f"/tmp/claude_{udid}.log"
        cmd = ["claude", "--add-dir", skill_dir, "--add-dir", common_dir,
               "--print", prompt]
        with open(log_path, "w") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=log)
        procs[udid] = proc
        print(f"[INFO] 启动 {group['platform']} {udid} (pid={proc.pid})")
    return procs

def collect_results(procs: dict, result_dir: str = "/tmp",
                    timeout: int = 90 * 60) -> dict:
    deadline = time.time() + timeout
    pending  = set(procs.keys())
    results  = {}

    while pending and time.time() < deadline:
        for udid in list(pending):
            path = os.path.join(result_dir, f"result_{udid}.json")
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        results[udid] = json.load(f)
                    pending.discard(udid)
                    print(f"[INFO] {udid} 完成，读取结果")
                except json.JSONDecodeError:
                    pass
        if pending:
            time.sleep(10)

    # 超时处理
    for udid in pending:
        print(f"[WARN] {udid} 超时，强制终止")
        proc = procs.get(udid)
        if proc and proc.poll() is None:
            proc.kill()
        results[udid] = "timeout"

    return results
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest scripts/tests/test_orchestrate.py -v
```

预期：全部 PASSED

- [ ] **Step 5: 在 _run() 中调用并行执行**

```python
# 在 _run() 函数探索阶段之后添加：

    # 4. 读 Bitable
    print("[INFO] 读取 Bitable 用例...")
    entries = fetch_cases(app_id)
    groups  = group_by_device(entries)
    if not groups:
        _notify(app_id, version, f"⚠️ {app_id} {version} 无标记自动化用例")
        return

    cfg = BITABLE_CONFIGS[app_id]
    total = sum(len(g["entries"]) for g in groups.values())
    print(f"[INFO] 共 {total} 条用例，{len(groups)} 台设备")

    # 5. 并行执行
    start_time = time.time()
    procs   = launch_claude_per_device(app_id, groups,
                                        cfg["app_token"], cfg["table_id"])
    results = collect_results(procs)
    duration = int(time.time() - start_time)
    print(f"[INFO] 执行完成，总耗时 {duration}s")
```

- [ ] **Step 6: Commit**

```bash
git add scripts/orchestrate.py scripts/tests/test_orchestrate.py
git commit -m "feat: parallel device execution with timeout protection"
```

---

### Task 10：报告生成 + 飞书通知

**Files:**
- Modify: `scripts/orchestrate.py`

- [ ] **Step 1: 实现 generate_reports 和 _notify**

```python
# 追加到 scripts/orchestrate.py

def _feishu_post(body: dict):
    token = _get_token()
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST"
    )
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"[WARN] 飞书通知失败: {e}")

def _notify(app_id: str, version: str, message: str):
    _feishu_post({
        "receive_id": GROUP_CHAT_ID,
        "msg_type": "text",
        "content": json.dumps({"text": f"[{app_id} {version}] {message}"})
    })

def generate_reports(app_id: str, version: str, results: dict, duration: int):
    import datetime
    start_time = datetime.datetime.now().strftime("%H:%M:%S")
    script = os.path.join(PROJECT_ROOT, "scripts", "wiki_report.py")

    android_cases, ios_cases = [], []
    for udid, data in results.items():
        if data == "timeout":
            continue
        for case in (data if isinstance(data, list) else []):
            platform = case.get("platform", "").lower()
            if platform == "android":
                android_cases.append(case)
            elif platform == "ios":
                ios_cases.append(case)

    wiki_urls = {}
    for platform, cases in [("Android", android_cases), ("iOS", ios_cases)]:
        if not cases:
            continue
        total  = len(cases)
        passed = sum(1 for c in cases if c.get("passed"))
        failed = total - passed
        rate   = int(passed / total * 100) if total else 0
        result = subprocess.run(
            ["python3", script,
             "--app", app_id, "--version", version,
             "--platform", platform,
             "--time", start_time, "--duration", f"{duration}s",
             "--total", str(total), "--passed", str(passed),
             "--failed", str(failed), "--rate", str(rate),
             "--cases", json.dumps(cases, ensure_ascii=False)],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if "Wiki 报告已创建" in line:
                url = line.split("：")[-1].strip()
                wiki_urls[platform] = url
                print(line)

    # 最终群通知
    lines = [f"📱 {app_id} {version} 自动化测试完成\n"]
    for platform, cases in [("Android", android_cases), ("iOS", ios_cases)]:
        if not cases:
            continue
        total  = len(cases)
        passed = sum(1 for c in cases if c.get("passed"))
        rate   = int(passed / total * 100) if total else 0
        url    = wiki_urls.get(platform, "")
        lines.append(f"{platform}：{passed}/{total} 通过 ({rate}%)  📄 {url}")
    lines.append(f"\n总耗时：{duration // 60}分{duration % 60}秒")
    _notify(app_id, version, "\n".join(lines))
```

- [ ] **Step 2: 在 _run() 末尾调用报告生成**

```python
# 在 _run() 末尾追加：

    # 6. 生成报告
    generate_reports(app_id, version, results, duration)

    # 7. 清理临时文件
    for udid in groups:
        path = f"/tmp/result_{udid}.json"
        if os.path.exists(path):
            os.remove(path)
    print("[INFO] 完成")
```

- [ ] **Step 3: 完整流程冒烟验证（dry-run）**

```bash
python3 scripts/orchestrate.py --help
```

预期：显示 --app / --version / --apk-url / --ipa-url 参数说明，无报错。

- [ ] **Step 4: Commit**

```bash
git add scripts/orchestrate.py
git commit -m "feat: report generation and Feishu notification in orchestrate"
```

---

## Part D：部署

### Task 11：Flask 服务器部署

**Files:**
- Create: `server/.env.example`

- [ ] **Step 1: 创建 .env.example**

```bash
# server/.env.example
MAC_HOST=192.168.x.x
MAC_USER=mac
MAC_KEY=/home/deploy/.ssh/id_rsa
ORCHESTRATE_PATH=/Users/mac/Documents/projects/appium-mcp-matrix/scripts/orchestrate.py
```

- [ ] **Step 2: 在云服务器上部署 Flask**

```bash
# 在云服务器执行
cd /opt/appium-webhook
pip install flask gunicorn

# 复制 server/app.py 到服务器
# 创建 .env 填入真实值

# 启动服务
gunicorn -w 1 -b 0.0.0.0:5000 app:app --daemon \
  --access-logfile /var/log/webhook-access.log \
  --error-logfile /var/log/webhook-error.log
```

- [ ] **Step 3: 飞书开发者控制台配置事件订阅**

1. 打开飞书开发者控制台 → 选择 Bot 应用
2. 添加事件订阅 → Webhook URL 填 `http://<server_ip>:5000/webhook/feishu`
3. 订阅事件：`im.message.receive_v1`（接收群消息）
4. 确保 Bot 已加入目标群聊

- [ ] **Step 4: 验证 Webhook 连通性**

在飞书群发消息：
```
gaotu 5.91.51 android:https://example.com/test.apk ios:https://example.com/test.ipa
```

预期：Bot 回复 "✅ 已收到，开始执行 gaotu 5.91.51"

- [ ] **Step 5: Commit**

```bash
git add server/.env.example
git commit -m "docs: add Flask deployment env example"
```

---

## Self-Review

**Spec coverage 检查：**

| Spec 要求 | 对应 Task |
|----------|----------|
| 飞书消息触发 | Task 4、5 |
| SSH 触发 Mac | Task 5 |
| 防重复执行 | Task 5（is_running） |
| APK/IPA 安装 | Task 6 |
| 探索新版本 | Task 8 |
| Bitable 过滤"是否执行自动化" | Task 7 |
| 按设备字段分组 | Task 7 |
| 8 台并行执行 | Task 9 |
| 90min 超时保护 | Task 9 |
| wiki_report.py 双端报告 | Task 10 |
| 飞书群最终通知 | Task 10 |
| wiki_report.py --account 可选 | Task 1 |
| devices.yaml 配置 | Task 3 |
| Bitable "是否执行自动化"字段 | Task 2 |
