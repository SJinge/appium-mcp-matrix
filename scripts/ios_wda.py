#!/usr/bin/env python3
"""iOS 真机 WDA 就绪保证。tunnel 由 LaunchDaemon 常驻;本模块只负责 WDA+proxy。"""
import glob, os, sys, time, json, plistlib, subprocess, urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = "http://127.0.0.1:49151/"
def _resolve_wda_dir() -> str:
    """定位 WebDriverAgent 源码目录(含 WebDriverAgent.xcodeproj)。

    换机后 appium-mcp 的 npm 前缀会变(brew 的 /opt/homebrew ↔ npm --prefix ~/.local),
    写死单一路径会在另一台机上崩。按候选顺序探测第一个存在 xcodeproj 的目录;
    可用 ORCH_WDA_DIR 显式覆盖。
    """
    override = os.environ.get("ORCH_WDA_DIR", "").strip()
    suffix = ("node_modules/appium-mcp/node_modules/"
              "appium-xcuitest-driver/node_modules/appium-webdriveragent")
    candidates = []
    if override:
        candidates.append(override)
    candidates += [
        os.path.expanduser(f"~/.local/lib/{suffix}"),
        f"/opt/homebrew/lib/{suffix}",
        f"/usr/local/lib/{suffix}",
    ]
    for d in candidates:
        if os.path.isdir(os.path.join(d, "WebDriverAgent.xcodeproj")):
            return d
    # 都没命中:返回首选(新机路径),让后续报错带出真实缺失路径
    return candidates[0] if candidates else ""


WDA_DIR = _resolve_wda_dir()
# 固定 derivedDataPath(按 udid 隔离):首次全量构建落在这里并被设备信任一次;
# 之后 WDA 死了用 test-without-building 复用同一份已签名产物重启,不重签 → 信任不失效。
DERIVED_DATA_ROOT = "/tmp/wda_derived"
# Xcode 默认 DerivedData:Appium/历史构建的 WDA 产物在此;固定路径没有产物时回退到这里
# 最新的一份,避免为了免重签反而触发全量 clean build(clean build 会重签 + 撞
# /usr/local/include 交叉编译坑)。
DEFAULT_DERIVED_DATA = os.path.expanduser("~/Library/Developer/Xcode/DerivedData")
# xcodebuild 进程活着 ≠ WDA 健康:runner 可能已死但进程不退(隧道断/锁屏/证书弹窗)。
# 用构建日志的更新时效区分「构建/服务进行中」与「僵尸」:日志超过此秒数没动且 WDA 不健康
# → 判僵尸,杀掉重建,否则永远卡在 wda_running=True 分支自愈不了。
WDA_LOG_STALE_SECS = 150


def _dd_dir(udid: str) -> str:
    return os.path.join(DERIVED_DATA_ROOT, udid)


def _xctestrun_path(udid: str) -> str:
    """可复用的 .xctestrun 产物路径;存在即可免重编直接 test-without-building 重启。

    优先固定 derivedDataPath;没有则回退 Xcode 默认 DerivedData 里最新的 WDA 产物。
    两处都没有才返回空(触发全量构建)。
    """
    pinned = sorted(glob.glob(os.path.join(_dd_dir(udid), "Build", "Products", "*.xctestrun")))
    if pinned:
        return pinned[0]
    cands = glob.glob(os.path.join(
        DEFAULT_DERIVED_DATA, "WebDriverAgent-*", "Build", "Products", "*.xctestrun"))
    return max(cands, key=os.path.getmtime) if cands else ""


def _device_wda_port(xctestrun: str, default: int = 8100) -> int:
    """WDA 在设备侧实际监听端口:由 xctestrun 里烤进的 USE_PORT 决定。

    复用已有产物时该端口不一定是 8100(Appium 构建时按 wdaLocalPort 烤成 8101/8102...),
    proxy 上游必须连这个端口,否则 Connection refused。解析失败回退 default。
    """
    if not xctestrun or not os.path.exists(xctestrun):
        return default
    try:
        with open(xctestrun, "rb") as f:
            data = plistlib.load(f)
        for cfg in data.values():
            if not isinstance(cfg, dict):
                continue
            env = cfg.get("EnvironmentVariables") or {}
            val = env.get("USE_PORT")
            if val:
                return int(val)
    except Exception as e:
        log.warning(f"解析 xctestrun USE_PORT 失败,回退 {default}: {e}")
    return default

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


def _start_wda(udid: str, team: str, bundle_id: str, rebuild: bool = True):
    logf = open(f"/tmp/wda_build_{udid}.log", "w")
    xctestrun = "" if rebuild else _xctestrun_path(udid)
    if xctestrun:
        # 复用已构建并被设备信任的 WDA 产物,不重新签名 → 免费/个人证书信任不会失效。
        cmd = ["xcodebuild", "test-without-building",
               "-xctestrun", xctestrun,
               "-destination", f"id={udid}"]
        log.info(f"[{udid}] relaunching WDA (no rebuild): {xctestrun}")
    else:
        # 首次构建(或产物缺失):全量构建到固定 derivedDataPath,需在设备上信任一次证书。
        cmd = ["xcodebuild", "test",
               "-project", os.path.join(WDA_DIR, "WebDriverAgent.xcodeproj"),
               "-scheme", "WebDriverAgentRunner",
               "-destination", f"id={udid}",
               "-derivedDataPath", _dd_dir(udid),
               "-allowProvisioningUpdates",
               "CODE_SIGN_STYLE=Automatic",
               f"DEVELOPMENT_TEAM={team}",
               f"PRODUCT_BUNDLE_IDENTIFIER={bundle_id}"]
        log.info(f"[{udid}] building+starting WDA (full): {' '.join(cmd)}")
    subprocess.Popen(cmd, stdout=logf, stderr=logf, cwd=WDA_DIR)


def _kill_proxy(port: int):
    r = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True)
    for pid in r.stdout.split():
        try:
            subprocess.run(["kill", pid], capture_output=True)
        except Exception:
            pass


def _kill_wda(udid: str):
    subprocess.run(["pkill", "-f", f"xcodebuild.*id={udid}"], capture_output=True)


def _wda_log_age(udid: str):
    """WDA 构建日志距今多少秒没更新;文件不存在返回 None(视作无进行中构建)。"""
    try:
        return time.time() - os.path.getmtime(f"/tmp/wda_build_{udid}.log")
    except OSError:
        return None


def _start_proxy(udid: str, port: int, device_port: int = 8100):
    logf = open(f"/tmp/wda_proxy_{udid}.log", "w")
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "wda_proxy.py"),
           "--udid", udid, "--port", str(port),
           "--device-port", str(device_port), "--registry", REGISTRY]
    log.info(f"[{udid}] starting proxy on :{port} -> device :{device_port}")
    subprocess.Popen(cmd, stdout=logf, stderr=logf)


def ensure_wda_ready(udid: str, team: str, bundle_id: str,
                     port: int, timeout: int = 180) -> bool:
    if health_check(port):
        log.info(f"[{udid}] WDA already healthy on :{port} (reuse)")
        return True
    if not tunnel_ready(udid):
        log.warning(f"[{udid}] tunnel 未就绪,检查 tunneld LaunchDaemon")
        return False
    xctestrun = _xctestrun_path(udid)
    need_start = not wda_running(udid)
    if not need_start:
        # 进程活着但(顶部已判)WDA 不健康。日志还在动 → 构建/启动进行中,继续等;
        # 日志已停(或没有我方日志=别处遗留的野进程)→ 判僵尸,杀掉重建,否则永远卡。
        age = _wda_log_age(udid)
        if age is None or age > WDA_LOG_STALE_SECS:
            log.info(f"[{udid}] xcodebuild 存活但 WDA 不健康、构建日志 "
                     f"{'缺失' if age is None else str(int(age)) + 's 未更新'} => 判僵尸,杀掉重建")
            _kill_wda(udid)
            need_start = True
        else:
            log.info(f"[{udid}] WDA 构建/启动疑似进行中(日志 {int(age)}s 前更新),继续等待")
    if need_start:
        # 已构建过(有 .xctestrun)→ 免重编复用已信任产物重启;否则首次全量构建。
        _start_wda(udid, team, bundle_id, rebuild=not xctestrun)
    if proxy_listening(port):
        # 不健康却仍在监听 => 上游隧道很可能已失效,视为僵尸,杀掉重起
        log.info(f"[{udid}] proxy on :{port} listening but WDA unhealthy, restarting (stale)")
        _kill_proxy(port)
    # 设备侧端口由复用产物 xctestrun 的 USE_PORT 决定(不一定是 8100)
    _start_proxy(udid, port, device_port=_device_wda_port(xctestrun))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health_check(port):
            log.info(f"[{udid}] WDA ready on :{port}")
            return True
        time.sleep(3)
    log.warning(f"[{udid}] WDA 未在 {timeout}s 内就绪(编译/签名/锁屏?)见 /tmp/wda_build_{udid}.log")
    return False
