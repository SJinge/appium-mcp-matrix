# iOS 真机 WDA 自动化启动 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 orchestrate 后台无人值守执行 iOS 真机用例:tunnel 用 root LaunchDaemon 常驻,WDA+proxy 按需拉起,session 显式连已就绪 WDA。

**Architecture:** 混合方案。`pymobiledevice3 remote tunneld` 由 `/Library/LaunchDaemons` 以 root 常驻(开机自启+自愈)。`scripts/ios_wda.py` 提供 `ensure_wda_ready()`:健康检查→不健康则起 xcodebuild WDA + `scripts/wda_proxy.py`→轮询就绪≤180s。orchestrate 在 iOS 装完后调它,失败判环境阻断报警不写结果;就绪端口经 `build_prompt` 注入 prompt,claude 用 `appium:webDriverAgentUrl` 直连,不再自装 WDA。

**Tech Stack:** Python 3(/usr/bin/python3)、pytest、unittest.mock、launchd、pymobiledevice3、appium-xcuitest-driver。

参考 spec:`docs/superpowers/specs/2026-07-02-ios-wda-autostart-design.md`

---

## 文件结构

- 新增 `scripts/wda_proxy.py` —— 参数化 TCP proxy(从 `/tmp/wda_proxy.py` 迁移),含可测的 `discover_tunnel_host(registry, udid)`。
- 新增 `scripts/ios_wda.py` —— WDA 就绪保证:`health_check` / `tunnel_ready` / `proxy_listening` / `wda_running` / `ensure_wda_ready`。
- 新增 `scripts/tests/test_wda_proxy.py`、`scripts/tests/test_ios_wda.py`。
- 改 `scripts/orchestrate.py` —— 默认常量、import、iOS 集成点、`build_prompt` iOS 分支、端口线程串联。
- 改 `scripts/tests/test_orchestrate.py` —— 集成点与 build_prompt 测试。
- 新增 `deploy/launchd/com.gaotu.appium-matrix.tunneld.plist`,改 `deploy/launchd/README.md`。
- 改 `config/devices.yaml` —— iOS 设备 `wda` 段。
- 改 `common/device.md` —— iOS capabilities 固化 `webDriverAgentUrl`。

---

## Task 1: wda_proxy.py 迁移并参数化

**Files:**
- Create: `scripts/wda_proxy.py`
- Test: `scripts/tests/test_wda_proxy.py`

- [ ] **Step 1: Write the failing test**

```python
# scripts/tests/test_wda_proxy.py
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
    payload = {"000081010001E28D436E0001E".replace("0001E", "0001E"): 0}  # placeholder
    payload = {"00008101001E28D436E0001E": {"address": "fd00::2"}}
    with patch("wda_proxy.urllib.request.urlopen", return_value=_fake_urlopen(payload)):
        host = wda_proxy.discover_tunnel_host("http://127.0.0.1:49151/",
                                              "00008101-001E28D436E0001E")
    assert host == "fd00::2"


def test_discover_tunnel_host_missing_returns_none():
    with patch("wda_proxy.urllib.request.urlopen", return_value=_fake_urlopen({})):
        host = wda_proxy.discover_tunnel_host("http://127.0.0.1:49151/", "unknown-udid")
    assert host is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest scripts/tests/test_wda_proxy.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'wda_proxy'`)

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""IPv4 127.0.0.1:{port} -> device tunnel IPv6 [addr]:8100 TCP proxy.
Auto-discovers the tunnel address from pymobiledevice3 tunneld registry (:49151).
Usage: wda_proxy.py --udid <udid> --port 8100 [--registry http://127.0.0.1:49151/]
"""
import argparse, socket, select, sys, json, urllib.request, time

WDA_DEVICE_PORT = 8100  # WDA always listens on 8100 on the device side


def discover_tunnel_host(registry: str, udid: str):
    with urllib.request.urlopen(registry, timeout=5) as r:
        data = json.load(r)
    entry = data.get(udid) or data.get(udid.replace("-", ""))
    if isinstance(entry, list):
        entry = entry[0] if entry else None
    if isinstance(entry, dict):
        return entry.get("tunnel-address") or entry.get("address")
    return None


def _pipe(a, b):
    try:
        while True:
            r, _, _ = select.select([a, b], [], [])
            if a in r:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
            if b in r:
                d = b.recv(65536)
                if not d:
                    break
                a.sendall(d)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.close()
            except OSError:
                pass


def serve(udid: str, port: int, registry: str):
    import threading
    host = None
    for _ in range(30):
        try:
            host = discover_tunnel_host(registry, udid)
        except Exception as e:
            print(f"registry not ready: {e}", file=sys.stderr)
        if host:
            break
        time.sleep(1)
    if not host:
        print("ERROR: could not discover tunnel host from registry "
              f"{registry} (is tunneld running?)", file=sys.stderr)
        sys.exit(1)
    print(f"tunnel host = {host}; proxy 127.0.0.1:{port} -> [{host}]:{WDA_DEVICE_PORT}")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(64)
    while True:
        cli, _ = srv.accept()
        try:
            info = socket.getaddrinfo(host, WDA_DEVICE_PORT, socket.AF_INET6, socket.SOCK_STREAM)
            fam, typ, proto, _, addr = info[0]
            up = socket.socket(fam, typ, proto)
            up.connect(addr)
        except OSError as e:
            print(f"upstream connect failed: {e}", file=sys.stderr)
            cli.close()
            continue
        threading.Thread(target=_pipe, args=(cli, up), daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--udid", required=True)
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--registry", default="http://127.0.0.1:49151/")
    args = ap.parse_args()
    serve(args.udid, args.port, args.registry)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest scripts/tests/test_wda_proxy.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/wda_proxy.py scripts/tests/test_wda_proxy.py
git commit -m "feat: 参数化 WDA proxy(udid/port/registry)+ tunnel 发现单测"
```

---

## Task 2: ios_wda.py 核心逻辑

**Files:**
- Create: `scripts/ios_wda.py`
- Test: `scripts/tests/test_ios_wda.py`

- [ ] **Step 1: Write the failing test**

```python
# scripts/tests/test_ios_wda.py
import sys, os, io, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import patch, MagicMock
import ios_wda


def _urlopen_ok():
    cm = MagicMock()
    cm.__enter__.return_value = io.BytesIO(b'{"value":{"state":"success"}}')
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
    # unhealthy first, tunnel ok, not running/listening, then becomes healthy on poll
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest scripts/tests/test_ios_wda.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'ios_wda'`)

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""iOS 真机 WDA 就绪保证。tunnel 由 LaunchDaemon 常驻;本模块只负责 WDA+proxy。"""
import os, sys, time, json, subprocess, urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = "http://127.0.0.1:49151/"
WDA_DIR = ("/opt/homebrew/lib/node_modules/appium-mcp/node_modules/"
           "appium-xcuitest-driver/node_modules/appium-webdriveragent")

try:
    import logging_setup
    log = logging_setup.get_logger("ios_wda", logfile="orchestrate.log")
except Exception:
    import logging
    log = logging.getLogger("ios_wda")


def health_check(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def tunnel_ready(udid: str) -> bool:
    try:
        with urllib.request.urlopen(REGISTRY, timeout=5) as r:
            data = json.load(r)
    except Exception:
        return False
    return bool(data.get(udid) or data.get(udid.replace("-", "")))


def proxy_listening(port: int) -> bool:
    r = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def wda_running(udid: str) -> bool:
    r = subprocess.run(["pgrep", "-f", f"xcodebuild.*id={udid}"],
                       capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def _start_wda(udid: str, team: str, bundle_id: str):
    logf = open(f"/tmp/wda_build_{udid}.log", "w")
    cmd = ["xcodebuild", "test",
           "-project", os.path.join(WDA_DIR, "WebDriverAgent.xcodeproj"),
           "-scheme", "WebDriverAgentRunner",
           "-destination", f"id={udid}", "-allowProvisioningUpdates",
           "CODE_SIGN_STYLE=Automatic",
           f"DEVELOPMENT_TEAM={team}",
           f"PRODUCT_BUNDLE_IDENTIFIER={bundle_id}"]
    log.info(f"[{udid}] starting WDA: {' '.join(cmd)}")
    subprocess.Popen(cmd, stdout=logf, stderr=logf, cwd=WDA_DIR)


def _start_proxy(udid: str, port: int):
    logf = open(f"/tmp/wda_proxy_{udid}.log", "w")
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "wda_proxy.py"),
           "--udid", udid, "--port", str(port), "--registry", REGISTRY]
    log.info(f"[{udid}] starting proxy on :{port}")
    subprocess.Popen(cmd, stdout=logf, stderr=logf)


def ensure_wda_ready(udid: str, team: str, bundle_id: str,
                     port: int, timeout: int = 180) -> bool:
    if health_check(port):
        log.info(f"[{udid}] WDA already healthy on :{port} (reuse)")
        return True
    if not tunnel_ready(udid):
        log.warning(f"[{udid}] tunnel 未就绪,检查 tunneld LaunchDaemon")
        return False
    if not wda_running(udid):
        _start_wda(udid, team, bundle_id)
    if not proxy_listening(port):
        _start_proxy(udid, port)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health_check(port):
            log.info(f"[{udid}] WDA ready on :{port}")
            return True
        time.sleep(3)
    log.warning(f"[{udid}] WDA 未在 {timeout}s 内就绪(编译/签名/锁屏?)见 /tmp/wda_build_{udid}.log")
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest scripts/tests/test_ios_wda.py -v`
Expected: PASS(10 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/ios_wda.py scripts/tests/test_ios_wda.py
git commit -m "feat: ios_wda.ensure_wda_ready(健康检查/复用/拉WDA+proxy/超时)"
```

---

## Task 3: orchestrate 集成点 + 端口串联

**Files:**
- Modify: `scripts/orchestrate.py`(常量 + import;iOS 装完后集成;`launch_claude_per_device` 与 `build_prompt` 加端口)
- Test: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 scripts/tests/test_orchestrate.py 末尾
def test_build_prompt_ios_injects_wda_url():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "i1", "iOS", entries, wda_port=8100)
    assert "webDriverAgentUrl" in prompt
    assert "http://127.0.0.1:8100" in prompt


def test_build_prompt_android_no_wda_url():
    entries = [{"record_id": "r1", "name": "c1", "module": "m", "steps": []}]
    prompt = orchestrate.build_prompt("gaotu", "a1", "Android", entries)
    assert "webDriverAgentUrl" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest scripts/tests/test_orchestrate.py -k build_prompt -v`
Expected: FAIL(`build_prompt() got an unexpected keyword argument 'wda_port'`)

- [ ] **Step 3: Write minimal implementation**

在 `orchestrate.py` `PKG_NAMES` 块后新增常量并 import:

```python
import ios_wda

DEFAULT_WDA_TEAM   = "5YX44746D6"
DEFAULT_WDA_BUNDLE = "com.shijinge.WebDriverAgentRunner"
DEFAULT_WDA_PORT   = 8100
```

改 `build_prompt` 签名与 iOS 分支(在 `return (` 之前构造 `wda_note`,并把它插入返回串):

```python
def build_prompt(app_id: str, udid: str, platform: str, entries: list,
                 wda_port: int = None) -> str:
    cases_json = json.dumps(
        [{"record_id": e["record_id"], "name": e["name"],
          "module": e["module"], "steps": e["steps"]} for e in entries],
        ensure_ascii=False
    )
    wda_note = ""
    if platform.lower() == "ios" and wda_port:
        wda_note = (
            f"\n【iOS WDA 已就绪(务必遵守)】\n"
            f"建 session 必须带 appium:webDriverAgentUrl = http://127.0.0.1:{wda_port}，"
            f"严禁让 XCUITest driver 自行重装/重启 WDA(会架空已就绪 WDA 并触发签名)。\n"
        )
    return (
        f"你是{app_id} App 自动化测试工程师。\n"
        f"设备：{udid}（{platform}）\n"
        f"{wda_note}\n"
        f"⚠️ 跑的是【线上生产环境】：严禁重放 ACTION（点击/提交/下单）做重试，会重复写线上数据。\n\n"
        # ... 其余原文保持不变 ...
    )
```

改 `launch_claude_per_device` 接受端口映射并透传:

```python
def launch_claude_per_device(app_id: str, groups: dict, wda_ports: dict = None) -> dict:
    wda_ports = wda_ports or {}
    procs = {}
    skill_dir  = os.path.join(PROJECT_ROOT, ".claude", "skills", app_id)
    common_dir = os.path.join(PROJECT_ROOT, "common")
    for udid, group in groups.items():
        prompt = build_prompt(app_id, udid, group["platform"], group["entries"],
                              wda_port=wda_ports.get(udid))
        log_path = f"/tmp/claude_{udid}.log"
        cmd = ["claude", "--add-dir", skill_dir, "--add-dir", common_dir,
               "--print", prompt]
        with open(log_path, "w") as logf:
            proc = subprocess.Popen(cmd, stdout=logf, stderr=logf)
        procs[udid] = proc
        log.info(f"Launched {group['platform']} {udid} (pid={proc.pid})")
    return procs
```

改 `_run` 的 iOS 安装循环(把原 `ios_ok.append(d)` 段替换为带 WDA 门禁),并在调用处传 `wda_ports`:

```python
    wda_ports = {}
    if "ios" in platforms:
        for d in devices["ios"]:
            if not install_ios(ipa_path, d["udid"]):
                log.warning(f"iOS {d['udid']} install failed, skipping")
                continue
            log.info(f"iOS {d['udid']} installed")
            wda = d.get("wda", {})
            port = wda.get("port", DEFAULT_WDA_PORT)
            if ios_wda.ensure_wda_ready(
                    d["udid"], wda.get("team", DEFAULT_WDA_TEAM),
                    wda.get("bundle_id", DEFAULT_WDA_BUNDLE), port):
                ios_ok.append(d)
                wda_ports[d["udid"]] = port
            else:
                _notify(app_id, version,
                        f"⚠️ iOS {d['udid']} WDA 未就绪，环境阻断，跳过（不写结果表）")
                log.warning(f"iOS {d['udid']} WDA not ready, skipping (env blocked)")
```

并把 `procs = launch_claude_per_device(app_id, groups)` 改为:

```python
    procs = launch_claude_per_device(app_id, groups, wda_ports=wda_ports)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest scripts/tests/test_orchestrate.py -v`
Expected: PASS(含新增 2 条 + 原有全绿)

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrate.py scripts/tests/test_orchestrate.py
git commit -m "feat: orchestrate iOS 装完调 ensure_wda_ready + webDriverAgentUrl 注入 prompt"
```

---

## Task 4: devices.yaml iOS wda 段

**Files:**
- Modify: `config/devices.yaml`
- Test: `scripts/tests/test_orchestrate.py`(扩展 load_devices 测试)

- [ ] **Step 1: Write the failing test**

```python
# 追加到 scripts/tests/test_orchestrate.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest scripts/tests/test_orchestrate.py -k load_devices_parses_ios_wda -v`
Expected: FAIL（KeyError: 'wda'，因为当前 devices.yaml 无此段;此测试用 tmp yaml 故应 PASS —— 若已 PASS 说明 load_devices 天然透传,直接进 Step 3 补真实配置）

> 注:`load_devices` 用 `yaml.safe_load` 原样返回嵌套结构,本测试验证透传行为,预期直接 PASS。真正要改的是真实配置文件。

- [ ] **Step 3: 写入真实配置**

编辑 `config/devices.yaml`,给 gaotu(或 default)的 iOS 设备补 `wda` 段:

```yaml
  ios:
    - udid: "00008101-001E28D436E0001E"
      name: "111的iPhone12 (iOS 18.7.8)"
      wda:
        team: "5YX44746D6"
        bundle_id: "com.shijinge.WebDriverAgentRunner"
        port: 8100
    - udid: "00008110-00180CD9348B801E"
      name: "iPhone (iOS 18.7.8)"
      wda:
        port: 8101
```

- [ ] **Step 4: Run test + 校验 yaml 合法**

Run: `/usr/bin/python3 -m pytest scripts/tests/test_orchestrate.py -k load_devices -v`
Run: `/usr/bin/python3 -c "import yaml; yaml.safe_load(open('config/devices.yaml'))" && echo YAML_OK`
Expected: PASS + `YAML_OK`

- [ ] **Step 5: Commit**

```bash
git add config/devices.yaml scripts/tests/test_orchestrate.py
git commit -m "feat: devices.yaml iOS 设备补 wda 段(team/bundle_id/port)"
```

---

## Task 5: common/device.md 固化 webDriverAgentUrl

**Files:**
- Modify: `common/device.md`(iOS capabilities 段)

- [ ] **Step 1: 修改 iOS capabilities 块**

把 `common/device.md` 的 iOS capabilities JSON 改为(新增 `webDriverAgentUrl` 及说明):

```json
{
  "platformName": "iOS",
  "appium:automationName": "XCUITest",
  "appium:udid": "<udid>",
  "appium:bundleId": "<bundleId>",
  "appium:noReset": true,
  "appium:autoAcceptAlerts": true,
  "appium:webDriverAgentUrl": "http://127.0.0.1:8100",
  "appium:wdaLaunchTimeout": 120000,
  "appium:wdaConnectionTimeout": 120000
}
```

在该 JSON 下方补一行说明:

```markdown
> 真机务必带 `appium:webDriverAgentUrl`（端口由 orchestrate 按设备下发,单设备默认 8100）：
> WDA 已由 orchestrate 预先拉起,driver 直连即可,不要让它自装(会触发签名、架空已就绪 WDA)。
```

- [ ] **Step 2: 校验渲染无误**

Run: `grep -n "webDriverAgentUrl" common/device.md`
Expected: 命中新增行。

- [ ] **Step 3: Commit**

```bash
git add common/device.md
git commit -m "docs: device.md iOS capabilities 固化 webDriverAgentUrl"
```

---

## Task 6: tunneld LaunchDaemon plist + README

**Files:**
- Create: `deploy/launchd/com.gaotu.appium-matrix.tunneld.plist`
- Modify: `deploy/launchd/README.md`

- [ ] **Step 1: 写 plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.gaotu.appium-matrix.tunneld</string>

  <!-- iOS17+ RemoteXPC 隧道,必须 root(LaunchDaemon 天然以 root 运行) -->
  <key>ProgramArguments</key>
  <array>
    <string>/Users/mac/.wda-venv/bin/pymobiledevice3</string>
    <string>remote</string>
    <string>tunneld</string>
  </array>

  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/Users/mac/Documents/projects/appium-mcp-matrix/logs/launchd.tunneld.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/mac/Documents/projects/appium-mcp-matrix/logs/launchd.tunneld.err.log</string>
</dict>
</plist>
```

- [ ] **Step 2: 校验 plist 合法**

Run: `plutil -lint deploy/launchd/com.gaotu.appium-matrix.tunneld.plist`
Expected: `OK`

- [ ] **Step 3: 在 README.md 追加 tunneld 段**

在 `deploy/launchd/README.md` 末尾追加:

```markdown
## tunneld(iOS 真机 WDA 隧道,root 守护)

iOS17+ 真机自动化需 RemoteXPC 隧道,必须 root 启动。用 LaunchDaemon 常驻:

安装(一次性,需 sudo):
```bash
sudo cp deploy/launchd/com.gaotu.appium-matrix.tunneld.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.gaotu.appium-matrix.tunneld.plist
sudo launchctl load -w /Library/LaunchDaemons/com.gaotu.appium-matrix.tunneld.plist
```

观测:
```bash
curl -s http://127.0.0.1:49151/ | python3 -m json.tool   # tunnel 注册表
tail -f logs/launchd.tunneld.err.log
```

卸载:`sudo launchctl unload -w /Library/LaunchDaemons/com.gaotu.appium-matrix.tunneld.plist`

> 注:放 `/Library/LaunchDaemons`(非 `~/Library/LaunchAgents`)才以 root 运行。
> tunneld 只访问 USB 设备、不读 ~/Documents,不撞 webhook 当年的 TCC 坑。
```

- [ ] **Step 4: Commit**

```bash
git add deploy/launchd/com.gaotu.appium-matrix.tunneld.plist deploy/launchd/README.md
git commit -m "feat: tunneld root LaunchDaemon(常驻+自愈)+ 部署文档"
```

---

## Task 7: 全量回归 + 集成验证清单

**Files:** 无代码改动(验证任务)

- [ ] **Step 1: 全量单测**

Run: `/usr/bin/python3 -m pytest scripts/tests/ server/tests/ -v`
Expected: 全绿(含本次新增 test_wda_proxy / test_ios_wda / 扩展的 test_orchestrate)

- [ ] **Step 2: Android 回归确认(静态)**

Run: `git diff main -- scripts/orchestrate.py | grep -nE "^\+" | grep -i android`
Expected: 无对 Android 分支逻辑的改动(集成点仅在 iOS 分支内;`launch_claude_per_device` 新增参数有默认值,Android 调用路径不变)

- [ ] **Step 3: 真机集成验证(手工,需 iphone12 在线且解锁)**

```bash
# 1) 装 tunneld daemon(见 Task 6),确认注册表有设备
curl -s http://127.0.0.1:49151/ | python3 -m json.tool
# 2) 单独验证 ensure_wda_ready
/usr/bin/python3 -c "import sys; sys.path.insert(0,'scripts'); import ios_wda; \
print(ios_wda.ensure_wda_ready('00008101-001E28D436E0001E','5YX44746D6','com.shijinge.WebDriverAgentRunner',8100))"
# 3) 健康检查
curl -s http://127.0.0.1:8100/status
```
Expected: 第 2 步打印 `True`;第 3 步返回 JSON。

- [ ] **Step 4: 端到端(手工)**

删幂等标记后触发一次 iOS run,确认 claude 日志里 session 用了 `webDriverAgentUrl` 且未出现二次 WDA 安装/120s 超时:
```bash
rm -f /tmp/orchestrate_gaotu_*_ios.triggered
# 触发后:
grep -i "webDriverAgentUrl\|8100" /tmp/claude_00008101-001E28D436E0001E.log
```
Expected: 命中 webDriverAgentUrl;无 WDA 重装/超时报错。

- [ ] **Step 5: 无需 commit(纯验证)**

---

## Self-Review 记录

- **Spec 覆盖**:混合架构(Task 6 tunneld + Task 2/3 WDA/proxy)、ensure 流程与复用(Task 2)、集成点+capability 闭环(Task 3)、配置化(Task 4)、device.md 固化(Task 5)、失败方案A分层报警(Task 2/3 文案)、测试分层(Task 1/2/3 单测 + Task 7 集成)。全部有对应任务。
- **Placeholder**:无 TBD/TODO;每个代码步给出完整代码。
- **类型一致**:`ensure_wda_ready(udid,team,bundle_id,port,timeout)`、`build_prompt(...,wda_port=None)`、`launch_claude_per_device(...,wda_ports=None)`、`discover_tunnel_host(registry,udid)` 在各任务间签名一致。
- **capability 名**:硬要求仅 `appium:webDriverAgentUrl`(设置后 XCUITest 即直连不自装,足够);spec 提到的 `usePreinstalledWDA` 因 driver 版本差异不作硬要求,实现时如需可另加。
