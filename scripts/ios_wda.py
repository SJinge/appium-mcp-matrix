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
            if r.status != 200:
                return False
            body = json.loads(r.read().decode())
            return "value" in body or "sessionId" in body
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


def _kill_proxy(port: int):
    r = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True)
    for pid in r.stdout.split():
        try:
            subprocess.run(["kill", pid], capture_output=True)
        except Exception:
            pass


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
    if proxy_listening(port):
        # 不健康却仍在监听 => 上游隧道很可能已失效,视为僵尸,杀掉重起
        log.info(f"[{udid}] proxy on :{port} listening but WDA unhealthy, restarting (stale)")
        _kill_proxy(port)
    _start_proxy(udid, port)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health_check(port):
            log.info(f"[{udid}] WDA ready on :{port}")
            return True
        time.sleep(3)
    log.warning(f"[{udid}] WDA 未在 {timeout}s 内就绪(编译/签名/锁屏?)见 /tmp/wda_build_{udid}.log")
    return False
