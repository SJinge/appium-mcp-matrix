#!/usr/bin/env python3
import argparse, glob, json, os, platform, re, shlex, shutil, signal, subprocess, sys, time
import importlib.util
import urllib.request, urllib.error, urllib.parse, datetime
import plistlib
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
from feishu_config import APP_ID, APP_SECRET, GROUP_CHAT_ID, BITABLE_CONFIGS, RESULT_TABLES
from orch_config import (
    PKG_NAMES,
    APP_DISPLAY_NAMES,
    DEFAULT_WDA_TEAM,
    DEFAULT_WDA_BUNDLE,
    DEFAULT_WDA_PORT,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_CONCURRENT_AGENT_PROCS,
    DEFAULT_MAX_BATCH_PROMPT_CHARS,
    resolve_agent_runner,
    load_runner_secrets,
    resolve_max_concurrent_agent_procs,
    resolve_max_batch_prompt_chars,
    resolve_ui_audit_enabled,
)
import orch_cases
import orch_case_script
import orch_case_runtime
import orch_case_runtime_ios
import orch_execution
import orch_result_table
import orch_reporting
import run_status
import logging_setup
import ios_wda

log = logging_setup.get_logger("orchestrate", logfile="orchestrate.log")


# ---- Thin compatibility aliases -------------------------------------------------
# Keep historical names on `orchestrate` so existing tests/monkeypatch usage stay valid,
# while making this file easier to scan as an entrypoint.
_text_field = orch_cases.text_field
_case_order_key = orch_cases.case_order_key
_extract_udid = orch_cases.extract_udid
parse_record = orch_cases.parse_record
group_by_device = orch_cases.group_by_device
entry_account_key = orch_cases.entry_account_key
estimate_entry_prompt_chars = orch_cases.estimate_entry_prompt_chars

_batch_result_dir = orch_execution.batch_result_dir
_batch_result_path = orch_execution.batch_result_path
_batch_account_path = orch_execution.batch_account_path
_append_jsonl = orch_execution.append_jsonl

_passed_assert_steps = orch_case_script.passed_assert_steps
should_generate_case_script = orch_case_script.should_generate_case_script
is_toast_like_assert = orch_case_script.is_toast_like_assert
_normalize_evidence_token = orch_case_script.normalize_evidence_token
_split_evidence_tokens = orch_case_script.split_evidence_tokens

_parse_bounds_center = orch_case_runtime.parse_bounds_center
_find_bounds_by_locator = orch_case_runtime.find_bounds_by_locator
_page_matches_target = orch_case_runtime.page_matches_target

_lowconf_review_steps = orch_result_table.lowconf_review_steps
_tail_file = orch_reporting.tail_file
_load_jsonl = orch_reporting.load_jsonl


def resolve_ui_audit_enabled() -> bool:
    value = os.environ.get("ORCH_ENABLE_UI_AUDIT", "").strip().lower()
    if not value:
        return True
    return value not in {"0", "false", "no", "off"}


def agent_log_path(udid: str) -> str:
    return f"/tmp/agent_{udid}.log"


def _codex_config_arg(key: str, value) -> str:
    return f"{key}={json.dumps(value)}"


def build_agent_command(runner: str, prompt: str, skill_dir: str, common_dir: str) -> list:
    if runner == "claude":
        # --dangerously-skip-permissions：headless(--print)无人应答，缺此标志时 claude
        # 对每个工具调用(appium MCP)都要权限确认、并因 workspace 未被 trust 而拒用工具，
        # 于是只描述计划反问"要不要继续"就退出 → 每条用例判失败。等价 codex 的
        # --dangerously-bypass-approvals-and-sandbox。此标志同时跳过 trust 对话框。
        return ["claude", "--dangerously-skip-permissions",
                "--add-dir", skill_dir, "--add-dir", common_dir, "--print", prompt]
    if runner == "codex":
        # codex exec 默认 approval=never，会把 appium-mcp 的非只读工具直接取消。
        # 编排执行只依赖 appium-mcp；忽略用户全局 config，避免无关 MCP 配置解析失败
        # 阻断设备 agent 启动，再显式注入最小可运行配置。
        return [
            "codex",
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C",
            os.path.dirname(common_dir),
            "-c",
            _codex_config_arg("model_provider", "custom"),
            "-c",
            _codex_config_arg("model", "gpt-5.5"),
            "-c",
            _codex_config_arg("model_providers.custom.name", "OpenAI"),
            "-c",
            _codex_config_arg("model_providers.custom.wire_api", "responses"),
            "-c",
            "model_providers.custom.requires_openai_auth=true",
            "-c",
            _codex_config_arg("model_providers.custom.base_url", "https://sub2api7.baijia.com"),
            "-c",
            "disable_response_storage=true",
            "-c",
            _codex_config_arg("mcp_servers.appium-mcp.type", "stdio"),
            "-c",
            _codex_config_arg("mcp_servers.appium-mcp.command", "appium-mcp"),
            "-c",
            _codex_config_arg("mcp_servers.appium-mcp.env.NO_UI", "true"),
            "-c",
            _codex_config_arg("mcp_servers.appium-mcp.env.SCREENSHOT_QUALITY", "50"),
            "-c",
            _codex_config_arg("mcp_servers.appium-mcp.env.CACHE_TTL", "300000"),
            "-c",
            _codex_config_arg("mcp_servers.appium-mcp.env.LOG_LEVEL", "warn"),
            "-c",
            _codex_config_arg("mcp_servers.appium-mcp.env.ANDROID_HOME", "/Users/mac/Library/Android/sdk"),
            prompt,
        ]
    raise ValueError(f"Unsupported runner: {runner}")


def build_shared_execution_context(app_id: str) -> str:
    parts = [
        "【共享执行上下文】",
        "执行前必须读取以下文件：",
        "- common/elements/login.md",
        "- common/elements/dialog.md",
        "- common/screenshot.md",
        "- common/device.md",
        "- common/locator.md",
        "遇到无法自动化或环境不满足的用例，不要提问等待确认，直接判失败并在 note 说明原因后继续下一条。",
        "每跑完一条用例，必须立即增量 append 到本轮提示【结果落盘】指定的唯一 JSONL 绝对路径，不能等全部结束再统一写入。",
    ]
    if app_id == "gaotu":
        parts.append("- .claude/skills/gaotu/elements.md")
    return "\n".join(parts)


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


def extract_version_android_for_udid(udid: str, pkg: str) -> str:
    r = subprocess.run(
        ["adb", "-s", udid, "shell", "dumpsys", "package", pkg],
        capture_output=True, text=True
    )
    for line in r.stdout.splitlines():
        if "versionName=" in line:
            return line.strip().split("=", 1)[1].strip()
    return "unknown"


def uninstall_android(udid: str, pkg: str) -> bool:
    try:
        r = subprocess.run(
            ["adb", "-s", udid, "uninstall", pkg],
            capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        log.warning(f"adb uninstall 超时(>120s)，判卸载失败: {udid}")
        return False
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    return r.returncode == 0 or "unknown package" in out or "not installed for 0" in out


def install_android(apk_path: str, udid: str) -> bool:
    pkg = PKG_NAMES.get("gaotu", "com.gaotu100.superclass")
    if not uninstall_android(udid, pkg):
        log.warning(f"adb uninstall 失败，继续尝试安装: {udid}")
    try:
        r = subprocess.run(
            ["adb", "-s", udid, "install", "-r", apk_path],
            capture_output=True, text=True, timeout=300
        )
    except subprocess.TimeoutExpired:
        log.warning(f"adb install 超时(>300s)，判安装失败: {udid}")
        return False
    return r.returncode == 0


def _tidevice_cmd(*args) -> list:
    """构造 tidevice 子进程命令。

    CLT python 是 universal 二进制，subprocess 起的子进程 slice 由内核按架构偏好挑，
    不严格继承父进程；一旦落到 x86_64 slice，`from PIL import Image` 会因本机
    Pillow 是 arm64-only 轮子而 ImportError 崩溃 → tidevice 一启动就死、install 秒失败。
    在 Apple Silicon 上用 `arch -arm64` 把 tidevice 子进程钉死 arm64，匹配 arm64 的 PIL。
    """
    base = [sys.executable, "-m", "tidevice", *args]
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return ["arch", "-arm64", *base]
    return base


def uninstall_ios(udid: str, bundle_id: str) -> bool:
    try:
        r = subprocess.run(
            _tidevice_cmd("-u", udid, "uninstall", bundle_id),
            capture_output=True, text=True, timeout=180
        )
    except subprocess.TimeoutExpired:
        log.warning(f"tidevice uninstall 超时(>180s)，判卸载失败: {udid}")
        return False
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    ok = r.returncode == 0 or "not installed" in out or "install lookup failed" in out
    if not ok:
        log.warning(f"tidevice uninstall 失败 rc={r.returncode}: {udid} :: {out.strip()[:500]}")
    return ok


def install_ios(ipa_path: str, udid: str) -> bool:
    # tidevice CLI 常不在 PATH，用同解释器的 -m 调用更稳
    # 真机安装偶发卡在 lockdown/installd 不返回，必须设 timeout，否则主流程无限等(卡死)
    bundle_id = PKG_NAMES.get("gaotu", "com.gaotu100.superclass")
    if not uninstall_ios(udid, bundle_id):
        log.warning(f"tidevice uninstall 失败，继续尝试安装: {udid}")
    try:
        r = subprocess.run(
            _tidevice_cmd("-u", udid, "install", ipa_path),
            capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired:
        log.warning(f"tidevice install 超时(>600s)，判安装失败: {udid}")
        return False
    out = (r.stdout or "") + (r.stderr or "")
    ok = r.returncode == 0 or "Complete" in out
    if not ok:
        # 吞掉 stderr 会让 PIL/架构崩溃这类"秒失败"完全隐形，故失败必落盘
        log.warning(f"tidevice install 失败 rc={r.returncode}: {udid} :: {out.strip()[:800]}")
    return ok


def resolve_ios_ipa_url(url: str) -> str:
    """
    iOS 的 downloadUrl 通常是 itms-services 安装清单（指向 .plist），
    需解析出 manifest 里 kind=software-package 的真实 .ipa 直链。
    非 itms-services 链接原样返回。
    """
    if not url.startswith("itms-services"):
        return url
    qs = urllib.parse.urlparse(url).query
    plist_url = urllib.parse.parse_qs(qs).get("url", [""])[0]
    if not plist_url:
        log.warning(f"itms-services 链接无 url 参数：{url}")
        return url
    try:
        with urllib.request.urlopen(plist_url, timeout=30) as resp:
            manifest = plistlib.loads(resp.read())
        for item in manifest.get("items", []):
            for asset in item.get("assets", []):
                if asset.get("kind") == "software-package" and asset.get("url"):
                    return asset["url"]
    except Exception as e:
        log.warning(f"解析 iOS manifest 失败：{e}")
    return url


def download_file(url: str, dest: str) -> bool:
    # 加超时/续传/重试，避免 CDN 连接 stall 时 curl 无限干等卡死整轮。
    # 抖动加固：放宽低速中止窗口 + 多重试 + 断点续传，让偶发抖动能自愈，
    # 又保留 stall 兜底(真卡死 60s 无进展才中断，不会无限干等)：
    #   --connect-timeout 15            连接 15s 建不上就失败
    #   --speed-limit/--speed-time      连续 60s 平均 <10KB/s 才视为卡死中断
    #                                   (原 30s；抖动多在 1 分钟内恢复，给足缓冲)
    #   --retry 5 --retry-delay 5       卡死/失败自动重试 5 次，每次间隔 5s 等网络恢复
    #   --retry-connrefused             连接被拒也纳入重试(不止超时/5xx)
    #   -C -                            断点续传，重试从已下字节接着下不从头来
    # 阈值可用 ORCH_DL_SPEED_TIME / ORCH_DL_RETRY 覆盖，免改代码调参。
    speed_time = os.environ.get("ORCH_DL_SPEED_TIME", "60")
    retry = os.environ.get("ORCH_DL_RETRY", "5")
    r = subprocess.run(
        ["curl", "-L", "--connect-timeout", "15",
         "--speed-limit", "10240", "--speed-time", speed_time,
         "--retry", retry, "--retry-delay", "5", "--retry-connrefused",
         "-C", "-", "-o", dest, url],
        capture_output=True)
    exists = os.path.exists(dest)
    size_ok = exists and os.path.getsize(dest) > 1_000_000
    if size_ok:
        if r.returncode != 0:
            stderr = (r.stderr or b"").decode("utf-8", errors="ignore").strip()
            stdout = (r.stdout or b"").decode("utf-8", errors="ignore").strip()
            detail = stderr or stdout or f"curl exit {r.returncode}"
            log.warning(f"下载命令返回非0，但文件已有效落盘，按成功处理: {detail}")
        return True
    return False


def _remote_size(url: str) -> int:
    """HEAD 取远端 Content-Length（跟随重定向取最终值）；取不到返回 -1。"""
    try:
        r = subprocess.run(["curl", "-sIL", url], capture_output=True, timeout=30)
        out = (r.stdout or b"").decode("utf-8", errors="ignore")
        sizes = re.findall(r"(?im)^content-length:\s*(\d+)", out)
        return int(sizes[-1]) if sizes else -1
    except Exception:
        return -1


def prune_old_packages(app_id: str, version: str, platforms=None):
    """只保留当前版本安装包，删除同 App 历史版本的 /tmp 残留包。

    在下载阶段开始时调用；当前版本文件（含正被 ORCH_SKIP_DOWNLOAD 复用的包）保留。

    仅清理本 run 所属平台的扩展名（android→apk / ios→ipa）。android 与 ios 是
    两个独立并发进程且版本号常不同，若一起 glob apk+ipa，会把并发的另一平台 run
    正在下载的当前版本包当"历史版本"删掉（历史事故：iOS run 5.91.92 删掉安卓在下的
    gaotu_5.91.93.apk 导致 APK 下载失败）。platforms 为空时兜底清理两种扩展名。
    """
    plats = platforms or {"android", "ios"}
    exts = []
    if "android" in plats:
        exts.append("apk")
    if "ios" in plats:
        exts.append("ipa")
    keep = {f"{app_id}_{version}.{e}" for e in exts}
    paths = []
    for e in exts:
        paths += glob.glob(f"/tmp/{app_id}_*.{e}")
    for path in paths:
        if os.path.basename(path) in keep:
            continue
        try:
            os.remove(path)
            log.info(f"清理历史版本安装包: {path}")
        except OSError as e:
            log.warning(f"清理历史包失败 {path}: {e}")


def ensure_package(url: str, dest: str, label: str) -> bool:
    """下载安装包到 dest。

    ORCH_SKIP_DOWNLOAD 开启时，仅当本地包已存在且大小与远端 Content-Length
    严格相等才复用、跳过下载；取不到远端大小或大小不等一律重下，避免复用上一轮
    被中断的截断半包（历史事故：>1MB 但不完整的残包被当成功）。
    """
    if os.environ.get("ORCH_SKIP_DOWNLOAD", "").strip().lower() in ("1", "true", "yes"):
        if os.path.exists(dest):
            local, remote = os.path.getsize(dest), _remote_size(url)
            if remote > 0 and local == remote:
                log.info(f"{label} 复用本地已完整包，跳过下载（{local} bytes == 远端）: {dest}")
                return True
            log.info(f"{label} 本地包不完整/无法核对远端大小"
                     f"(local={local}, remote={remote})，重新下载")
    log.info(f"Downloading {label}: {url}")
    return download_file(url, dest)


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
        log.warning(f"Feishu notify failed: {e}")


def _notify(app_id: str, version: str, message: str):
    if os.environ.get("ORCH_NO_NOTIFY"):
        log.info(f"[群消息已静默 ORCH_NO_NOTIFY] [{app_id} {version}] {message}")
        return
    _feishu_post({
        "receive_id": GROUP_CHAT_ID,
        "msg_type": "text",
        "content": json.dumps({"text": f"[{app_id} {version}] {message}"})
    })


def _get_token() -> str:
    data = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode()
    req  = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    return json.load(urllib.request.urlopen(req))["tenant_access_token"]


def fetch_cases(app_id: str) -> list:
    cfg   = BITABLE_CONFIGS[app_id]
    token = _get_token()
    url   = (f"https://open.feishu.cn/open-apis/bitable/v1/apps"
             f"/{cfg['app_token']}/tables/{cfg['table_id']}/records/search")
    body_obj = {
        "filter": {
            "conjunction": "and",
            "conditions": [{"field_name": "执行方式", "operator": "is",
                            "value": ["自动"]}]
        },
        "page_size": 500
    }
    if cfg.get("view_id"):
        body_obj["view_id"] = cfg["view_id"]  # 按用户指定视图顺序返回
    body  = json.dumps(body_obj).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST"
    )
    resp  = json.load(urllib.request.urlopen(req))
    items = resp.get("data", {}).get("items", [])
    entries = [parse_record(r) for r in items]
    return sorted(entries, key=lambda e: _case_order_key(e.get("order") or e.get("name", "")))


def group_by_device(entries: list) -> dict:
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


def _prepare_executable_groups(app_id: str, version: str, entries: list,
                               android_ok: list, ios_ok: list,
                               platforms: set) -> dict:
    groups = group_by_device(entries)
    installed = {d["udid"] for d in android_ok} | {d["udid"] for d in ios_ok}
    requested = {str(platform).lower() for platform in platforms}
    skipped = {
        udid: group for udid, group in groups.items()
        if group.get("platform", "").lower() in requested and udid not in installed
    }
    for udid, group in skipped.items():
        log.warning(
            f"跳过 {group['platform']} 设备 {udid}（未连接/未安装），"
            f"{len(group['entries'])} 条用例不执行"
        )
    return {
        udid: group for udid, group in groups.items()
        if group.get("platform", "").lower() in requested and udid in installed
    }


def chunk_entries(entries: list, batch_size: int = DEFAULT_BATCH_SIZE) -> list:
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    return [entries[i:i + batch_size] for i in range(0, len(entries), batch_size)]


def build_execution_batches(entries: list, batch_size: int = DEFAULT_BATCH_SIZE) -> list:
    return orch_cases.build_execution_batches(
        entries,
        batch_size=batch_size,
        max_prompt_chars=resolve_max_batch_prompt_chars(),
    )


def _batch_result_dir(result_dir: str, udid: str, batch_idx: int) -> str:
    return orch_execution.batch_result_dir(result_dir, udid, batch_idx)


def _batch_result_path(result_dir: str, udid: str, batch_idx: int) -> str:
    return orch_execution.batch_result_path(result_dir, udid, batch_idx)


def _batch_account_path(result_dir: str, udid: str, batch_idx: int) -> str:
    return orch_execution.batch_account_path(result_dir, udid, batch_idx)


def _append_jsonl(path: str, cases: list):
    return orch_execution.append_jsonl(path, cases)


def _hydrate_batch_cases(batch_cases: list, entries: list) -> list:
    """Backfill identity fields when agent JSONL omits them."""
    return orch_execution.hydrate_batch_cases(batch_cases, entries)


def _select_legacy_batch_cases(legacy_cases: list, entries: list, already_done: int = 0) -> list:
    if not legacy_cases:
        return []
    record_ids = {entry.get("record_id") for entry in entries if entry.get("record_id")}
    if record_ids:
        matched = [case for case in legacy_cases if case.get("record_id") in record_ids]
        if matched:
            return matched
    if len(legacy_cases) == len(entries):
        return legacy_cases
    if len(legacy_cases) > already_done:
        return legacy_cases[already_done:already_done + len(entries)]
    return []


def _load_batch_cases_with_legacy(result_dir: str, udid: str, batch_idx: int,
                                  entries: list, batch_data=None,
                                  already_done: int = 0) -> list:
    batch_cases = _load_jsonl(_batch_result_path(result_dir, udid, batch_idx))
    if batch_cases:
        return batch_cases
    if isinstance(batch_data, list) and batch_data:
        return batch_data
    legacy_path = os.path.join(result_dir, f"result_{udid}.jsonl")
    legacy_cases = _select_legacy_batch_cases(_load_jsonl(legacy_path), entries, already_done)
    if legacy_cases:
        log.warning(
            f"{udid} batch {batch_idx + 1} 未写入批结果文件，"
            f"已从 legacy 结果文件兜底读取 {len(legacy_cases)} 条: {legacy_path}"
        )
    return legacy_cases


def _build_agent_failure_cases(entries: list, udid: str, platform: str, reason: str) -> list:
    cases = []
    for entry in entries:
        cases.append({
            "record_id": entry.get("record_id", ""),
            "name": entry.get("name", ""),
            "module": entry.get("module", ""),
            "order": entry.get("order", ""),
            "state_group": entry.get("state_group", ""),
            "platform": platform,
            "device": udid,
            "passed": False,
            "duration": 0,
            "screenshots": [],
            "exec_source": "agent_timeout" if "超时" in reason else "agent_failed",
            "note": reason,
            "steps": [{
                "type": "ASSERT",
                "text": "agent 执行结果落盘",
                "passed": False,
                "verify_method": "runtime",
                "evidence": "",
                "confidence": "high",
                "note": reason,
            }],
        })
    return cases


def _dedupe_batch_cases(batch_cases: list, entries: list) -> list:
    if not batch_cases:
        return batch_cases
    entry_keys = []
    for entry in entries:
        key = entry.get("record_id") or entry.get("name")
        if key:
            entry_keys.append(key)
    if not entry_keys:
        return batch_cases

    latest = {}
    extras = []
    for case in batch_cases:
        key = case.get("record_id") or case.get("source_record_id") or case.get("name")
        if key in entry_keys:
            latest[key] = case
        else:
            extras.append(case)

    ordered = [latest[key] for key in entry_keys if key in latest]
    remaining = max(0, len(entries) - len(ordered))
    return ordered + extras[:remaining]


def case_script_path(app_id: str, platform: str, record_id: str) -> str:
    return os.path.join(PROJECT_ROOT, "apps", app_id, "cases", platform.lower(), f"{record_id}.py")


def find_case_script(app_id: str, platform: str, record_id: str) -> str:
    path = case_script_path(app_id, platform, record_id)
    return path if os.path.exists(path) else ""


def _passed_assert_steps(case: dict) -> list:
    return orch_case_script.passed_assert_steps(case)


def should_generate_case_script(case: dict) -> bool:
    return orch_case_script.should_generate_case_script(case)


_KNOWN_DIALOG_TEXT_ACTIONS = (
    ("发送通知", "允许"),
    ("使用无线数据", "无线局域网与蜂窝网络"),
    ("无线局域网", "允许"),
    ("本地网络", "允许"),
    ("网络权限", "允许"),
    ("跟踪", "允许"),
    ("学习阶段", "一年级"),
    ("发现新版本", "取消"),
    ("剪切板", "允许"),
)


def is_toast_like_assert(step: dict) -> bool:
    return orch_case_script.is_toast_like_assert(step)


def _normalize_evidence_token(token: str) -> str:
    return orch_case_script.normalize_evidence_token(token)


def _split_evidence_tokens(evidence: str) -> list:
    return orch_case_script.split_evidence_tokens(evidence)


def _expand_compound_id_tokens(tokens: list) -> list:
    expanded = []
    for token in tokens:
        text = str(token or "").strip()
        if not text:
            continue
        if "|" not in text:
            expanded.append(text)
            continue
        if ":id/" in text:
            prefix, suffixes = text.split(":id/", 1)
            base = f"{prefix}:id/"
            for suffix in suffixes.split("|"):
                suffix = suffix.strip()
                if suffix:
                    expanded.append(suffix if ":id/" in suffix else f"{base}{suffix}")
        else:
            expanded.extend(s.strip() for s in text.split("|") if s.strip())
    return expanded


def _id_evidence_tokens(evidence: str) -> list:
    text = str(evidence or "").strip()
    if not text:
        return []
    # 复合 id(pkg:id/a|b|c)先展开为空格分隔的完整 id。否则下方 findall 会被 | 截断,
    # 只抓到第一个 id、丢弃其余 → 多 id 断言只校验首个、其余静默假通过。
    text = re.sub(
        r"[A-Za-z0-9_.]+:id/[A-Za-z0-9_]+(?:\|[A-Za-z0-9_]+)+",
        lambda m: " ".join(_expand_compound_id_tokens([m.group(0)])),
        text,
    )
    full_ids = re.findall(r"[A-Za-z0-9_.]+:id/[A-Za-z0-9_]+", text)
    if full_ids:
        tokens = list(full_ids)
        tokens.extend(
            label.strip()
            for label in re.findall(r":id/[A-Za-z0-9_]+\(([^)]*)\)", text)
            if label.strip()
        )
        for quoted in re.findall(r"text\s*(?:=|contains|含)\s*[\"'“‘]?([^\"'”’；;]+)[\"'”’]?", text):
            text_token = quoted.strip()
            if text_token and ":id/" not in text_token:
                tokens.append(text_token)
        tokens.extend(re.findall(r"《([^》]+)》", text))
        return tokens
    parsed = []
    pieces = re.split(r"[；;|/、,，]+", text)
    for piece in pieces:
        part = piece.strip()
        if not part:
            continue
        full_ids = re.findall(r"[A-Za-z0-9_.]+:id/[A-Za-z0-9_]+", part)
        if full_ids:
            parsed.extend(full_ids)
            for quoted in re.findall(r"text\s*(?:=|contains|含)\s*[\"'“‘]?([^\"'”’；;]+)[\"'”’]?", part):
                text_token = quoted.strip()
                if text_token and ":id/" not in text_token:
                    parsed.append(text_token)
            continue
        if part.startswith("/tmp/") or part.startswith("screenshot="):
            continue
        ident_match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", part)
        if ident_match:
            ident = ident_match.group(1)
            if ident and ident not in {"text", "hint"}:
                parsed.append(f":id/{ident}")
            paren = re.search(r"\(([^)]*)\)", part)
            if paren:
                label = re.sub(r"^(?:hint|text)\s+", "", paren.group(1).strip())
                if label:
                    parsed.append(label)
        for quoted in re.findall(r"(?:text|含)\s*(?:=|含)?\s*[\"'“‘]([^\"'”’]+)[\"'”’]", part):
            parsed.append(quoted)
        parsed.extend(re.findall(r"《([^》]+)》", part))
    if parsed:
        return parsed
    if re.search(r"\btext\s*含\b", text):
        tokens = []
        for ident in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s+text\s*含", text):
            tokens.append(f":id/{ident}")
        for quoted in re.findall(r"[\"'“‘]([^\"'”’]+)[\"'”’]", text):
            tokens.append(quoted)
        if tokens:
            return tokens
    if re.search(r"[A-Za-z_][A-Za-z0-9_]*\s*\(", text):
        pieces = re.split(r"[；;|/、,，]+", text)
        tokens = []
        for piece in pieces:
            match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(([^)]*)\))?", piece)
            if not match:
                continue
            ident, label = match.groups()
            tokens.append(f":id/{ident}")
            if label:
                tokens.append(label)
        if tokens:
            return tokens
    return _expand_compound_id_tokens([text])


def _assert_evidence_present(runtime: dict, verify_method: str, evidence: str) -> bool:
    return _assert_evidence_detail(runtime, verify_method, evidence)["passed"]


def _assert_evidence_detail(runtime: dict, verify_method: str, evidence: str) -> dict:
    source = ""
    reader = runtime.get("read_page_source")
    if callable(reader):
        source = reader()
    if verify_method not in {"id", "text"}:
        return {"passed": False, "tokens": [], "matched": [], "missing": [], "source": source}
    if runtime.get("platform") == "ios":
        # iOS 无 resource-id:id/text 断言证据都是定位散文(XCUIElementType/name=/xpath 等),
        # 用 Android 的 _id_evidence_tokens 会造出 :id/XCUIElementTypeButton 之类必失败垃圾 token。
        # 统一提取屏显可见文案,与 iOS page_source 的 name/label 做子串命中。
        tokens = orch_case_script.extract_ios_visible_tokens(evidence)
        if not tokens:
            tokens = [_normalize_evidence_token(evidence)]
    elif verify_method == "id":
        tokens = _id_evidence_tokens(evidence)
    else:
        tokens = _split_evidence_tokens(evidence)
        if not tokens:
            tokens = [_normalize_evidence_token(evidence)]
    filtered = [token for token in tokens if token]
    matched = [token for token in filtered if token in source]
    missing = [token for token in filtered if token not in source]
    return {
        "passed": not missing,
        "tokens": filtered,
        "matched": matched,
        "missing": missing,
        "source": source,
    }


def _normalize_flow_locator(locator, platform: str = ""):
    return orch_case_script.normalize_flow_locator(locator, _text_field, platform)


def _normalize_flow_fallbacks(fallbacks, platform: str = ""):
    return orch_case_script.normalize_flow_fallbacks(fallbacks, _text_field, platform)


def _flow_step_from_action(step: dict) -> dict:
    return orch_case_script.flow_step_from_action(
        step, _text_field, str(step.get("platform", ""))
    )


def _flow_step_from_assert(step: dict) -> dict:
    return orch_case_script.flow_step_from_assert(step)


def _infer_prepare_state_target(precond_texts: list) -> str:
    return orch_case_script.infer_prepare_state_target(precond_texts)


def _prepare_state_from_case(case: dict) -> dict:
    return orch_case_script.prepare_state_from_case(case, entry_account_key)


def _build_case_flow(case: dict) -> list:
    return orch_case_script.build_case_flow(
        case, entry_account_key, _text_field, ui_audit_enabled=resolve_ui_audit_enabled()
    )


def generate_case_script(app_id: str, platform: str, case: dict, version: str = None):
    if not should_generate_case_script(case):
        return None

    # agent 结果 JSONL 是外部输入，个别通过用例可能漏写 record_id；
    # 固化仅是副产物，缺 record_id 时跳过并告警，绝不因此让整轮崩掉。
    record_id = case.get("record_id")
    if not record_id:
        log.warning(f"用例通过但结果缺 record_id，跳过脚本固化: name={case.get('name', '')!r}")
        return None

    path = case_script_path(app_id, platform, record_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    normalized_platform = platform.lower()
    case_for_flow = dict(case)
    case_for_flow["platform"] = normalized_platform

    meta = {
        "app_id": app_id,
        "bundle_id": PKG_NAMES.get(app_id, ""),
        "app_version": version or case.get("app_version", ""),
        "record_id": record_id,
        "name": case.get("name", ""),
        "module": case.get("module", ""),
        "platform": platform.lower(),
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    flow = _build_case_flow(case_for_flow)
    content = f'''# Auto-generated by orchestrate. Edit with care.
META = {repr(meta)}
FLOW = {repr(flow)}


def execute(ctx):
    return ctx["run_flow"](META, FLOW)
'''
    with open(path, "w") as f:
        f.write(content)
    return path


def _read_account_state(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _stop_android_app(udid: str, pkg: str) -> bool:
    try:
        r = subprocess.run(
            ["adb", "-s", udid, "shell", "am", "force-stop", pkg],
            capture_output=True, text=True, timeout=60
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _resolve_latest_local_artifact(app_id: str, platform: str) -> str:
    ext = "ipa" if platform.lower() == "ios" else "apk"
    candidates = sorted(
        glob.glob(f"/tmp/{app_id}_*.{ext}"),
        key=lambda path: os.path.getmtime(path),
        reverse=True,
    )
    return candidates[0] if candidates else ""


def _resolve_local_artifact_for_script(app_id: str, platform: str, version: str = "") -> str:
    ext = "ipa" if platform.lower() == "ios" else "apk"
    if version:
        exact = f"/tmp/{app_id}_{version}.{ext}"
        if os.path.exists(exact):
            return exact
    return _resolve_latest_local_artifact(app_id, platform)


def _artifact_version_from_path(path: str) -> str:
    name = os.path.basename(path or "")
    match = re.match(r"^[^_]+_(.+)\.(apk|ipa)$", name)
    return match.group(1) if match else ""


def _resolve_android_launch_component(udid: str, package_name: str) -> str:
    if not package_name:
        return ""
    try:
        result = subprocess.run(
            ["adb", "-s", udid, "shell", "cmd", "package", "resolve-activity", "--brief", package_name],
            capture_output=True, text=True, timeout=20
        )
    except subprocess.TimeoutExpired:
        return ""
    if result.returncode != 0:
        return ""
    for line in reversed((result.stdout or "").splitlines()):
        candidate = line.strip()
        if "/" in candidate and " " not in candidate:
            return candidate
    return ""


def _launch_app_after_reinstall_for_script(app_id: str, platform: str, udid: str, ctx: dict) -> bool:
    bundle_id = ctx.get("script_meta", {}).get("bundle_id") or PKG_NAMES.get(app_id, "")
    if platform.lower() == "ios":
        if not bundle_id:
            return False
        wda = _resolve_ios_device_wda_config(app_id, udid)
        ensure_ios_network_permission_ready(
            app_id, udid, bundle_id, wda.get("port", DEFAULT_WDA_PORT))
        try:
            result = subprocess.run(
                _tidevice_cmd("-u", udid, "launch", bundle_id),
                capture_output=True, text=True, timeout=60
            )
        except subprocess.TimeoutExpired:
            return False
        ok = result.returncode == 0
    else:
        component = _resolve_android_launch_component(udid, bundle_id)
        if not component:
            return False
        ok = orch_case_runtime.adb_route(
            udid, {"value": component}, subprocess
        )
    if ok:
        time.sleep(4)
        invalidate_runtime = ctx.get("invalidate_state")
        if callable(invalidate_runtime):
            invalidate_runtime()
    return ok


def _reinstall_app_for_script(app_id: str, platform: str, udid: str, ctx: dict) -> bool:
    version = ctx.get("script_meta", {}).get("app_version", "")
    artifact_path = _resolve_local_artifact_for_script(app_id, platform, version)
    if not artifact_path or not os.path.exists(artifact_path):
        log.warning(f"脚本重装失败：未找到本地安装包 app={app_id} platform={platform}")
        return False
    ctx["resolved_artifact_path"] = artifact_path
    ctx["resolved_artifact_version"] = _artifact_version_from_path(artifact_path)
    close_runtime = ctx.get("close")
    if callable(close_runtime):
        try:
            close_runtime()
        except Exception:
            pass
    invalidate_runtime = ctx.get("invalidate_state")
    if callable(invalidate_runtime):
        invalidate_runtime()
    if platform.lower() == "ios":
        installed = install_ios(artifact_path, udid)
    else:
        installed = install_android(artifact_path, udid)
        try:
            ctx["installed_app_version"] = extract_version_android_for_udid(
                udid, ctx.get("script_meta", {}).get("bundle_id") or PKG_NAMES.get(app_id, "")
            )
        except OSError:
            ctx["installed_app_version"] = ""
    if not installed:
        return False
    if platform.lower() == "ios":
        wda = _resolve_ios_device_wda_config(app_id, udid)
        port = wda.get("port", DEFAULT_WDA_PORT)
        return ios_wda.ensure_wda_ready(
            udid,
            wda.get("team", DEFAULT_WDA_TEAM),
            wda.get("bundle_id", DEFAULT_WDA_BUNDLE),
            port,
        )
    return _launch_app_after_reinstall_for_script(app_id, platform, udid, ctx)


def _page_matches_target(page_source: str, target: str) -> bool:
    if not page_source or not target:
        return False
    checks = {
        "home": (("首页",), ("发现",)),
        "my_tab": (("我的", "点击登录"),),
        "class_tab": (("上课",), ("我的课程",)),
        "login": (("手机号登录",), ("获取验证码",)),
    }
    groups = checks.get(target, ())
    return bool(groups) and any(all(needle in page_source for needle in group) for group in groups)


# prepare_state 冷启后页面还没渲染完就读，会把"未到目标态"误判成失败→整条用例回退慢
# agent（本轮 8/9 回退皆源于此）。失败路径按此节奏重读/重路由若干次；已在目标态的用例
# 首轮即命中返回，零新增延迟。
PREPARE_STATE_POLL_ATTEMPTS = 6
PREPARE_STATE_POLL_INTERVAL = 2.0

# 脚本内自动登录(走查账号)轮询节奏:等协议弹窗/验证码框/登录回跳渲染。
LOGIN_VERIFY_ATTEMPTS = 8
LOGIN_VERIFY_INTERVAL = 1.5

# 高途首启弹窗序列(隐私弹窗→青少年守护)不在 _KNOWN_DIALOG_TEXT_ACTIONS 通用表里——放进去会
# 误伤"启动弹窗组"里自行断言/点击这些弹窗的用例(它们靠 assert+tap 走分支,不能被自动点掉)。
# 但重装冷启后它们盖在登录页/首页之上,不主动点过就永远到不了目标态(本轮 prepare_state
# failed 主因)。故仅在 prepare_state 内按 marker 主动点过一层:
#   隐私弹窗:出现"不同意"按钮 → 点"同意"进入;青少年守护:点"已满14岁"走正常流(未满14岁是退出分支)。
# marker 取"不同意"/"未满14岁"而非"同意/协议"——后者在登录页也有(《用户协议》链接),会误伤。
_STARTUP_DIALOG_ACTIONS = (
    ("不同意", "同意"),
    ("未满14岁", "已满14岁"),
)


def _advance_startup_dialog(source: str, tap_text) -> bool:
    """首启弹窗序列若在当前页,主动点过一层;返回是否点了(点了则本轮不判目标态,下轮重读)。"""
    if not source or not callable(tap_text):
        return False
    for marker, action in _STARTUP_DIALOG_ACTIONS:
        if marker in source:
            tap_text(action)
            return True
    return False


# prepare_state 的 account:<UNLOGIN>/<NONE>/空 都不是"要登进去的真实账号"——只有真实手机号才需登录。
_LOGIN_ACCOUNT_SENTINELS = frozenset({"<UNLOGIN>", "<NONE>", ""})


def _account_needs_login(account: str) -> bool:
    return bool(account) and account not in _LOGIN_ACCOUNT_SENTINELS


def _source_on_login_page(source: str) -> bool:
    return bool(source) and (
        "手机号登录" in source or "获取验证码" in source or "请输入手机号" in source
    )


def _source_logged_in(source: str) -> bool:
    # 登录后底部 tab 出现即已登录:iOS 有"AI闪学"文案;Android uiautomator dump 里底部导航
    # resource-id "tab_title" 字面出现(登录页是独立全屏 Activity,无底部导航,不会误判)。
    return bool(source) and ("AI闪学" in source or "tab_title" in source)


def _run_prepare_state(udid: str, step: dict, runtime: dict) -> bool:
    target = step.get("target", "")
    account = step.get("account", "")
    login = runtime.get("login")
    # 登录感知仅在平台提供 login 原语(当前仅 iOS)且账号是真实手机号时启用;
    # Android 无 login 原语→needs_login 恒 False,完全保留旧行为(不改动、零回归)。
    needs_login = callable(login) and _account_needs_login(account)
    if not target and not needs_login:
        return True
    route_text = {
        "home": "首页",
        "my_tab": "我的",
        "class_tab": "上课",
    }.get(target)
    handle_known_dialogs = runtime.get("handle_known_dialogs")
    tap_text = runtime.get("tap_text")
    for attempt in range(PREPARE_STATE_POLL_ATTEMPTS):
        if callable(handle_known_dialogs):
            handle_known_dialogs({})
        source = runtime["read_page_source"](True)
        # 首启弹窗盖在目标页上时,即便底层已渲染出"登录/首页"文案也不算就绪——先点过弹窗再重读,
        # 否则会把弹窗遮挡下的残留文案误判成已就绪。
        if _advance_startup_dialog(source, tap_text):
            if attempt + 1 < PREPARE_STATE_POLL_ATTEMPTS:
                time.sleep(PREPARE_STATE_POLL_INTERVAL)
            continue
        if needs_login:
            # 已登录且(无指定 target 或已到 target)→ 就绪。
            if _source_logged_in(source) and (not target or _page_matches_target(source, target)):
                return True
            # 在登录页且平台提供 login 原语(仅 iOS)→ 脚本内登录,下轮重读验证。
            # login 失败不在此处返回 False,继续轮询;耗尽后回退 agent(不硬拿未登录页断言)。
            if callable(login) and _source_on_login_page(source):
                login(account)
                if attempt + 1 < PREPARE_STATE_POLL_ATTEMPTS:
                    time.sleep(PREPARE_STATE_POLL_INTERVAL)
                continue
            # 已登录但还没到指定 target → 走下面的路由逻辑把 tab 切过去。
        else:
            if _page_matches_target(source, target):
                return True
            if target == "login" and "登录" in source:
                return True
        # 目标态未就绪：尝试路由后等页面 settle，下一轮重读（冷启动/弹层消失需要时间）。
        if route_text and callable(tap_text):
            tap_text(route_text)
        if attempt + 1 < PREPARE_STATE_POLL_ATTEMPTS:
            time.sleep(PREPARE_STATE_POLL_INTERVAL)
    return False


def _stop_ios_app(udid: str, bundle_id: str) -> bool:
    try:
        r = subprocess.run(
            _tidevice_cmd("-u", udid, "kill", bundle_id),
            capture_output=True, text=True, timeout=60
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def reset_apps_after_exploration(app_id: str, android_devices: list, ios_devices: list):
    pkg = PKG_NAMES.get(app_id, "")
    for udid in android_devices:
        if not _stop_android_app(udid, pkg):
            log.warning(f"探索后清理 Android App 失败: {udid}")
    for udid in ios_devices:
        if not _stop_ios_app(udid, pkg):
            log.warning(f"探索后清理 iOS App 失败: {udid}")


def grant_ios_network_permission(udid: str, bundle_id: str) -> bool:
    """执行可选的 iOS 网络权限预授权。

    iOS 没有类似 Android pm grant 的稳定本地网络权限授权命令。默认跳过外部
    预授权，依赖运行时 WDA alert API 兜底；如环境提供可靠工具，可通过
    ORCH_IOS_NETWORK_PERMISSION_CMD 显式接入。
    """
    template = os.environ.get("ORCH_IOS_NETWORK_PERMISSION_CMD", "").strip()
    if not template:
        log.info(f"iOS 网络权限无可用预授权命令，跳过外部授权并由系统弹窗兜底: {udid}")
        return True
    try:
        cmd = shlex.split(template.format(udid=udid, bundle_id=bundle_id))
    except Exception as exc:
        log.warning(f"iOS 网络权限命令模板非法: {exc}")
        return False
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        log.warning(f"iOS 网络权限命令不存在: {cmd[0] if cmd else template}")
        return False
    except subprocess.TimeoutExpired:
        log.warning(f"iOS 网络权限授予超时(>60s): {udid}")
        return False

    if result.returncode == 0:
        return True

    tail = ((result.stdout or "") + " " + (result.stderr or "")).strip()
    log.warning(f"iOS 网络权限授予失败: {udid}, code={result.returncode}, output={tail}")
    return False


def _create_ios_session_resilient(port: int, bundle_id: str, wda_recover=None,
                                  attempts: int = 3, backoff: float = 1.5) -> str:
    """在 8100 上建 WDA session，失败即用 ensure_wda_ready 自愈后重试。

    重装期 WDA/proxy 刚重启未 settle 时，单次 POST /session 会 60s 超时返回空，
    直接硬跳过预热。此处失败先调 wda_recover(健康则秒返、僵尸则重启 proxy/WDA)，
    退避后再试，把瞬时 WDA-down 变成自愈重试而非硬失败。wda_recover 为空则退化为纯重试。"""
    for attempt in range(attempts):
        session_id = orch_case_runtime_ios._create_session(port, bundle_id)
        if session_id:
            return session_id
        if attempt + 1 >= attempts:
            break
        if callable(wda_recover):
            try:
                wda_recover()
            except Exception as exc:
                log.warning(f"iOS 建 session 前 WDA 自愈异常: port={port}, err={exc}")
        time.sleep(backoff)
    return ""


def prepare_ios_network_permission(udid: str, bundle_id: str, port: int,
                                   timeout: int = 30, interval: float = 1.0,
                                   wda_recover=None) -> bool:
    """启动 App 并接受盖在隐私弹窗上的 iOS「无线数据」系统 alert。

    首启第一个联网请求会弹「允许"高途"使用无线数据?」三选一 alert,盖住隐私弹窗的
    「同意」键;必须点「无线局域网与蜂窝网络」放行(点「不允许」会连 WiFi 一起断,App 落到
    网络错误页,首个 ASSERT 失败)。alert 出现时机随冷启动快慢浮动,故轮询到出现再接、接住
    即返回,而非固定窗口盲等。窗口内始终没弹(通常=已授权)也不硬失败。"""
    if not bundle_id:
        log.warning(f"iOS 网络权限预热缺少 bundleId: {udid}")
        return False
    if not grant_ios_network_permission(udid, bundle_id):
        log.warning(f"iOS {udid} 外部网络权限预授权失败，改用 WDA alert 兜底")

    session_id = _create_ios_session_resilient(port, bundle_id, wda_recover)
    if not session_id:
        log.warning(f"iOS 网络权限预热建 session 失败: {udid}, port={port}")
        return False

    deadline = time.monotonic() + timeout
    accepted_network = False
    try:
        while time.monotonic() < deadline:
            alert = orch_case_runtime_ios._alert_text(port, session_id)
            if alert:
                button = orch_case_runtime_ios._known_dialog_action_text(
                    alert, _KNOWN_DIALOG_TEXT_ACTIONS)
                if not orch_case_runtime_ios._accept_alert(port, session_id, button or None):
                    log.warning(f"iOS 网络权限弹窗处理失败: {udid}, alert={alert[:120]}")
                    return False
                if "无线数据" in alert:
                    # 关键 alert 已放行,隐私弹窗已暴露,无需再等
                    accepted_network = True
                    break
                continue
            time.sleep(interval)
        if not accepted_network:
            log.info(f"iOS 首启无线数据 alert 未在 {timeout}s 内出现: {udid}(可能已授权)")
        return True
    finally:
        orch_case_runtime_ios._delete_session(port, session_id)
        _stop_ios_app(udid, bundle_id)


def ensure_ios_network_permission_ready(app_id: str, udid: str, bundle_id: str,
                                        port: int) -> bool:
    # iOS 首启第一个联网请求会弹「允许"高途"使用无线数据?」系统 alert,盖在隐私弹窗上、挡住
    # 「同意」键(点「不允许」会连 WiFi 一起断,App 落到网络错误页)。真机验证:唯一稳的授权方式
    # 是启动 App、轮询到该 alert 出现后用 WDA 点「无线局域网与蜂窝网络」放行(见 prepare)。
    # (曾试过"先进设置主动勾选":该 per-App「无线数据」入口在首启请求前根本不存在,且 WDA 起
    #  com.apple.Preferences 的 session 极不稳、每条用例白烧 60s,纯累赘,已移除。)设备可用性
    # 以 prepare 能否建起 session 为准。
    wda = _resolve_ios_device_wda_config(app_id, udid)
    wda_recover = lambda: ios_wda.ensure_wda_ready(
        udid,
        wda.get("team", DEFAULT_WDA_TEAM),
        wda.get("bundle_id", DEFAULT_WDA_BUNDLE),
        port,
    )
    return prepare_ios_network_permission(udid, bundle_id, port, wda_recover=wda_recover)


def _resolve_ios_device_wda_config(app_id: str, udid: str) -> dict:
    devices = load_devices(app_id)
    for device in devices.get("ios", []):
        if device.get("udid") == udid:
            return device.get("wda", {}) or {}
    return {}


def _android_script_login(runtime: dict, package: str, account: str) -> bool:
    """Android 未登录态用验证码登录(走查账号 12 开头,验证码固定 1000)。步骤取自设备实录
    recvpYuTNMt9O6(android):输手机号→点获取验证码→协议弹窗点同意→输验证码→判底部 tab。
    只在确认登录成功(tab_title 出现)时返 True;任一步失败/无法确认一律 False,回退 agent,
    绝不伪装成功拿未登录页去断言。复用共享 runtime 的 tap/input/read_page_source 原语。"""
    code = orch_case_runtime_ios.sms_code_for_account(account)
    if not code or not package:
        return False
    read_page_source = runtime["read_page_source"]
    handle_known_dialogs = runtime.get("handle_known_dialogs")
    tap = runtime["tap"]
    input_text = runtime["input"]
    if callable(handle_known_dialogs):
        handle_known_dialogs({})
    source = read_page_source(True)
    if not _source_on_login_page(source) and "account_enter_et" not in source:
        return False  # 不在登录页,不硬来
    # 1. 输入手机号
    if not input_text({"by": "id", "value": f"{package}:id/account_enter_et", "text": account}):
        return False
    # 2. 获取验证码
    if not tap({
        "by": "id", "value": f"{package}:id/account_sign_btn",
        "fallbacks": [{"by": "text", "value": "获取验证码"}],
    }):
        return False
    # 3. 协议弹窗(请阅读并同意以下协议)点"同意",直到验证码框露出
    for _ in range(LOGIN_VERIFY_ATTEMPTS):
        src = read_page_source(True)
        if "verify_code_edit_text" in src:
            break
        if "请阅读并同意" in src or "customer_dialog_ok" in src:
            tap({
                "by": "id", "value": f"{package}:id/customer_dialog_ok",
                "fallbacks": [{"by": "text", "value": "同意"}],
            })
        time.sleep(LOGIN_VERIFY_INTERVAL)
    # 4. 输入验证码(四个方框,焦点自动前进,输一次即可)
    if not input_text({"by": "id", "value": f"{package}:id/verify_code_edit_text", "text": code}):
        return False
    # 5. 成功判据:轮询等登录回跳,底部 tab(tab_title)出现才算成功
    for _ in range(LOGIN_VERIFY_ATTEMPTS):
        if _source_logged_in(read_page_source(True)):
            return True
        time.sleep(LOGIN_VERIFY_INTERVAL)
    return False


def _script_runtime_context(udid: str, package: str = "") -> dict:
    runtime = orch_case_runtime.script_runtime_context(
        udid=udid,
        subprocess_module=subprocess,
        assert_evidence_present_fn=_assert_evidence_present,
        run_prepare_state_fn=_run_prepare_state,
        tap_with_locator_fn=lambda device_udid, step, source: _tap_with_locator(device_udid, step, source),
        adb_input_text_fn=_adb_input_text,
        tap_by_text_fn=lambda device_udid, text: _tap_by_text(device_udid, text),
        run_flow_fn=_run_flow,
        known_dialog_text_actions=_KNOWN_DIALOG_TEXT_ACTIONS,
    )
    # 自动登录原语注入(定义留在 orchestrate,避免共享 runtime 反向依赖 ios 模块致循环导入)。
    runtime["login"] = lambda account: _android_script_login(runtime, package, account)
    return runtime


def _parse_bounds_center(bounds: str):
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not match:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _find_bounds_by_locator(page_source: str, by: str, value: str):
    if not by or not value:
        return None
    if str(by).strip().lower() in {"coord", "coordinate", "coordinates"}:
        match = re.search(r"(\d+)\s*,\s*(\d+)", str(value))
        if match:
            return int(match.group(1)), int(match.group(2))
    if not page_source:
        return None
    if by == "id":
        pattern = re.compile(rf'resource-id="{re.escape(value)}"[^>]*bounds="([^"]+)"')
    elif by == "text":
        text_value = str(value)
        xpath_text = re.search(r"@text\s*=\s*[\"']([^\"']+)[\"']", text_value)
        if xpath_text:
            text_value = xpath_text.group(1)
        elif text_value.startswith("text="):
            text_value = text_value.split("=", 1)[1].strip()
        coord_match = re.match(r"coord(?:inate)?\s*=\s*(\d+)\s*,\s*(\d+)", text_value)
        if coord_match:
            return int(coord_match.group(1)), int(coord_match.group(2))
        value = text_value
        pattern = re.compile(rf'text="{re.escape(value)}"[^>]*bounds="([^"]+)"')
    else:
        return None
    match = pattern.search(page_source)
    return _parse_bounds_center(match.group(1)) if match else None


def _adb_tap(udid: str, x: int, y: int) -> bool:
    try:
        r = subprocess.run(
            ["adb", "-s", udid, "shell", "input", "tap", str(x), str(y)],
            capture_output=True, text=True, timeout=15
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _tap_with_locator(udid: str, step: dict, page_source: str) -> bool:
    locators = [{"by": step.get("by"), "value": step.get("value")}]
    for fallback in step.get("fallbacks") or []:
        if isinstance(fallback, dict):
            locators.append({"by": fallback.get("by"), "value": fallback.get("value")})
    for locator in locators:
        center = _find_bounds_by_locator(page_source, locator.get("by"), locator.get("value"))
        if center:
            return _adb_tap(udid, center[0], center[1])
    return False


def _tap_by_text(udid: str, text: str) -> bool:
    try:
        source = subprocess.run(
            ["adb", "-s", udid, "exec-out", "uiautomator", "dump", "/dev/tty"],
            capture_output=True, text=True, timeout=30
        ).stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return False
    center = _find_bounds_by_locator(source, "text", text)
    return _adb_tap(udid, center[0], center[1]) if center else False


def _adb_input_text(udid: str, text: str) -> bool:
    safe_text = str(text).replace(" ", "%s")
    try:
        r = subprocess.run(
            ["adb", "-s", udid, "shell", "input", "text", safe_text],
            capture_output=True, text=True, timeout=15
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _cleanup_ios_appium_mcp_wda(udid: str):
    # Appium MCP 可能拉起临时 WDA；脚本 UI 复核后恢复项目配置的 WDA。
    return None


def _script_ui_audit_entry(case_meta: dict, step: dict) -> dict:
    text = step.get("text") or "UI规范检查"
    screenshot = step.get("screenshot") or step.get("evidence") or ""
    page_source = step.get("page_source") or ""
    return {
        "record_id": case_meta.get("record_id", ""),
        "name": f"{case_meta.get('name', '')} {text}".strip(),
        "module": case_meta.get("module", ""),
        "steps": [{
            "type": "ASSERT",
            "text": (
                f"{text}。先自动处理已知系统弹窗；除这些已知弹窗外，"
                "不执行额外点击/输入/跳转动作，只基于当前截图和 page source 判断 UI 是否异常。"
            ),
            "verify_method": "vision",
            "evidence": screenshot,
            "page_source": page_source,
        }],
    }


def _assert_ui_via_agent(*args, **kwargs):
    return execute_case_via_agent(*args, **kwargs)


def _run_script_assert_ui(app_id: str, platform: str, udid: str,
                          ctx: dict, step: dict, wda_port: int = None) -> dict:
    handler = ctx.get("handle_known_dialogs")
    if callable(handler):
        handler(step)
    screenshot = ""
    capture = ctx.get("capture_screenshot")
    if callable(capture):
        screenshot = capture(step)
    reader = ctx.get("read_page_source")
    page_source = reader(True) if callable(reader) else ""
    checkpoints = ctx.setdefault("_script_ui_audit_checkpoints", [])
    index = len(checkpoints)
    checkpoints.append({
        "index": index,
        "text": step.get("text") or "UI规范检查",
        "screenshot": screenshot,
        "page_source": page_source,
    })
    return {
        "text": step.get("text") or "UI规范检查",
        "passed": True,
        "verify_method": "screenshot",
        "evidence": screenshot,
        "confidence": "low",
        "checkpoint_index": index,
        "note": "deferred ui audit checkpoint",
    }


def _assert_ui_checkpoints_via_agent(app_id: str, platform: str, udid: str,
                                     case_meta: dict, checkpoints: list,
                                     wda_port: int = None) -> list:
    results = []
    retries = int(os.environ.get("ORCH_SCRIPT_UI_AUDIT_RETRIES", "0") or "0")
    for checkpoint in checkpoints:
        entry = _script_ui_audit_entry(case_meta, {
            "text": checkpoint.get("text", ""),
            "screenshot": checkpoint.get("screenshot", ""),
            "page_source": checkpoint.get("page_source", ""),
        })
        last_case = {}
        for attempt in range(retries + 1):
            last_case = _assert_ui_via_agent(
                app_id=app_id,
                platform=platform,
                udid=udid,
                entry=entry,
                wda_port=wda_port,
                result_dir=os.path.join("/tmp", "script_ui_audit", udid, str(checkpoint.get("index", 0))),
            )
            assert_steps = [
                step for step in last_case.get("steps", [])
                if step.get("type") in {"ASSERT", "ASSERT_UI"}
            ]
            if assert_steps:
                step = assert_steps[0]
                # UI 审计子 agent 常把整体结论放在 case 级 passed + note，而 step 级
                # passed 留空(null)。此处 step 级为 None 时回退 case 级判定，否则
                # bool(None)=False 会把"UI 正常"的审计误判为 assert_ui failed。
                step_passed = step.get("passed", step.get("pass"))
                if step_passed is None:
                    step_passed = last_case.get("passed")
                results.append({
                    "checkpoint_index": checkpoint.get("index", 0),
                    "text": checkpoint.get("text", ""),
                    "passed": bool(step_passed),
                    "verify_method": step.get("verify_method", "vision"),
                    "evidence": step.get("evidence", checkpoint.get("screenshot", "")),
                    "confidence": step.get("confidence", "low"),
                    "note": step.get("note", last_case.get("note", "")),
                })
                break
            if attempt < retries:
                time.sleep(1)
        else:
            results.append({
                "checkpoint_index": checkpoint.get("index", 0),
                "text": checkpoint.get("text", ""),
                "passed": False,
                "verify_method": "vision",
                "evidence": checkpoint.get("screenshot", ""),
                "confidence": "low",
                "note": last_case.get("note", "assert_ui agent returned no assertion"),
            })
    return results


def _finalize_deferred_script_ui_audit(app_id: str, platform: str, udid: str,
                                       ctx: dict, result: dict,
                                       wda_port: int = None) -> dict:
    checkpoints = ctx.get("_script_ui_audit_checkpoints") or []
    if not checkpoints:
        return result
    audit_results = _assert_ui_checkpoints_via_agent(
        app_id, platform, udid, ctx.get("script_meta", {}), checkpoints, wda_port=wda_port
    )
    by_index = {item.get("checkpoint_index"): item for item in audit_results}
    failed_text = ""
    for step in result.get("steps", []):
        if step.get("type") != "ASSERT_UI" or "checkpoint_index" not in step:
            continue
        audit = by_index.get(step.get("checkpoint_index"))
        if not audit:
            continue
        audit_passed = audit.get("passed") if "passed" in audit else audit.get("pass")
        step.update({
            "passed": bool(audit_passed),
            "verify_method": audit.get("verify_method", step.get("verify_method", "vision")),
            "evidence": audit.get("evidence", step.get("evidence", "")),
            "confidence": audit.get("confidence", step.get("confidence", "low")),
            "note": audit.get("note", step.get("note", "")),
        })
        if not step["passed"] and not failed_text:
            failed_text = step.get("text") or audit.get("text") or "assert_ui"
    if failed_text:
        result["passed"] = False
        result["note"] = f"assert_ui failed: {failed_text}"
    if platform.lower() == "ios":
        _cleanup_ios_appium_mcp_wda(udid)
        wda = _resolve_ios_device_wda_config(app_id, udid)
        ios_wda.ensure_wda_ready(
            udid,
            wda.get("team", DEFAULT_WDA_TEAM),
            wda.get("bundle_id", DEFAULT_WDA_BUNDLE),
            wda.get("port", DEFAULT_WDA_PORT),
        )
    return result


def _script_runtime_context_for(app_id: str, platform: str, udid: str,
                                script_meta: dict = None) -> dict:
    meta = dict(script_meta or {})
    bundle_id = meta.get("bundle_id") or PKG_NAMES.get(app_id, "")
    normalized_platform = platform.lower()
    if normalized_platform == "ios":
        wda = _resolve_ios_device_wda_config(app_id, udid)
        port = wda.get("port", DEFAULT_WDA_PORT)
        ensure_ios_network_permission_ready(app_id, udid, bundle_id, port)
        ctx = orch_case_runtime_ios.script_runtime_context(
            udid=udid,
            port=port,
            bundle_id=bundle_id,
            assert_evidence_present_fn=_assert_evidence_present,
            run_prepare_state_fn=_run_prepare_state,
            run_flow_fn=_run_flow,
            known_dialog_text_actions=_KNOWN_DIALOG_TEXT_ACTIONS,
            recover_transport_fn=lambda: ios_wda.ensure_wda_ready(
                udid,
                wda.get("team", DEFAULT_WDA_TEAM),
                wda.get("bundle_id", DEFAULT_WDA_BUNDLE),
                port,
            ),
        )
    else:
        ctx = _script_runtime_context(udid, package=bundle_id)
        ctx.setdefault("route", lambda step: orch_case_runtime.adb_route(udid, step, subprocess))
        ctx.setdefault("assert_evidence_detail", lambda method, evidence: _assert_evidence_detail(ctx, method, evidence))
        ctx.setdefault("invalidate_state", lambda: True)
    ctx["script_meta"] = meta
    ctx["_assert_evidence_detail_fn"] = _assert_evidence_detail
    ctx["assert_ui"] = lambda step: _run_script_assert_ui(
        app_id, platform, udid, ctx, step,
        wda_port=_resolve_ios_device_wda_config(app_id, udid).get("port", DEFAULT_WDA_PORT)
        if normalized_platform == "ios" else None,
    )
    ctx["reinstall_app"] = lambda step: _reinstall_app_for_script(
        app_id, platform, udid, ctx
    )
    if "run_flow" not in ctx:
        ctx["run_flow"] = lambda meta, flow: _run_flow(meta, flow, ctx)
    return ctx


def _run_flow(meta: dict, flow: list, runtime: dict) -> dict:
    return orch_case_runtime.run_flow(meta, flow, runtime)


def run_case_script(app_id: str, platform: str, udid: str, script_path: str):
    spec = importlib.util.spec_from_file_location(
        f"case_script_{platform}_{udid}_{int(time.time() * 1000)}", script_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    started = time.time()
    script_meta = getattr(module, "META", {})
    ctx = _script_runtime_context_for(app_id, platform, udid, script_meta)
    if "run_flow" not in ctx:
        ctx["run_flow"] = lambda meta, flow: _run_flow(meta, flow, ctx)
    try:
        result = module.execute(ctx)
    finally:
        close_runtime = ctx.get("close")
        if callable(close_runtime):
            close_runtime()
    wda_port = None
    if platform.lower() == "ios":
        wda_port = _resolve_ios_device_wda_config(app_id, udid).get("port", DEFAULT_WDA_PORT)
    result = _finalize_deferred_script_ui_audit(app_id, platform, udid, ctx, result, wda_port=wda_port)
    result.setdefault("platform", platform.capitalize())
    result.setdefault("device", udid)
    result.setdefault("duration", int(time.time() - started))
    result.setdefault("script_source", "script")
    expected_version = (script_meta or {}).get("app_version", "")
    actual_version = (
        ctx.get("installed_app_version")
        or ctx.get("resolved_artifact_version")
        or ""
    )
    if expected_version and actual_version and expected_version != actual_version:
        mismatch_note = f"version mismatch: expected {expected_version}, actual {actual_version}"
        result["note"] = f"{result.get('note', '')} | {mismatch_note}".strip(" |")
        result["script_app_version"] = expected_version
        result["actual_app_version"] = actual_version
    return result


# 503「No available accounts」是网关瞬时并发/容量问题,agent 在动作前就被拒、设备现场未变,
# 可原样退避重试;429(日限额/限流)是硬墙,当天重试纯白烧,直接失败不重试。
AGENT_503_MAX_ATTEMPTS = 3            # 含首次,最多尝试 3 次
AGENT_503_BACKOFF_SECONDS = 30       # 退避基数,按尝试次线性放大(30/60s)
DEFAULT_CODEX_AGENT_TIMEOUT_SECONDS = 15 * 60


def _resolve_agent_timeout_seconds(timeout: int = 90 * 60) -> int:
    raw = os.environ.get("ORCH_AGENT_TIMEOUT_SECONDS", "").strip()
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            log.warning(f"忽略非法 ORCH_AGENT_TIMEOUT_SECONDS={raw!r}")
    if resolve_agent_runner() == "codex":
        return min(timeout, DEFAULT_CODEX_AGENT_TIMEOUT_SECONDS)
    return timeout


def _agent_failure_is_retryable_503(tail: str) -> bool:
    """从 agent 日志末尾判断本次失败是否为可重试的网关 503。
    仅 503「No available accounts」重试;429/日限额/限流一律不重试。"""
    t = (tail or "").lower()
    if "no available accounts" in t:
        return True
    return "503" in t and "overloaded" in t


def execute_case_via_agent(app_id: str, platform: str, udid: str, entry: dict,
                           version: str = None, current_account: str = "",
                           wda_port: int = None, result_dir: str = "/tmp",
                           timeout: int = 90 * 60):
    timeout = _resolve_agent_timeout_seconds(timeout)
    case_dir = os.path.join(result_dir, "case_results", udid, entry["record_id"])
    last_data = None
    last_tail = ""
    for attempt in range(1, AGENT_503_MAX_ATTEMPTS + 1):
        shutil.rmtree(case_dir, ignore_errors=True)
        os.makedirs(case_dir, exist_ok=True)
        proc = launch_agent_batch(
            app_id, udid, platform.capitalize(), [entry],
            wda_port=wda_port, version=version,
            current_account=current_account,
            batch_idx=0, batch_count=1,
            is_last_batch=True,
            result_dir=case_dir,
        )
        batch_results = collect_results(
            {udid: proc},
            result_dir=_batch_result_dir(case_dir, udid, 0),
            timeout=timeout,
            # 单用例内部收集静默(app_id/version=None → 不触发飞书报警),
            # 是否报警/重试由本函数依失败类型统一决定,避免重试中的 503 误报。
            app_id=None,
            version=None,
            poll_interval=10,
            device_totals={udid: {"total": 1, "platform": platform.capitalize()}},
        )
        data = batch_results.get(udid)
        case = _load_batch_cases_with_legacy(case_dir, udid, 0, [entry], data)
        if case:
            result = case[0]
            # agent 结果 schema 不含 record_id(prompt 只要 name/passed/steps…),
            # 单条路径必须像整批 hydrate 一样从 entry 回填 record_id/name/module/…,
            # 否则下游 generate_case_script 因缺 record_id 跳过固化、写表也丢 record_id。
            _hydrate_batch_cases([result], [entry])
            result["_current_account"] = _read_account_state(_batch_account_path(case_dir, udid, 0)) or current_account
            return result

        last_data = data
        last_tail = _tail_file(agent_log_path(udid))
        if _agent_failure_is_retryable_503(last_tail) and attempt < AGENT_503_MAX_ATTEMPTS:
            backoff = AGENT_503_BACKOFF_SECONDS * attempt
            log.warning(
                f"[{udid}] 网关 503 无可用账号,{backoff}s 后重试用例 "
                f"{entry['record_id']}(第 {attempt}/{AGENT_503_MAX_ATTEMPTS - 1} 次重试)"
            )
            time.sleep(backoff)
            continue
        break

    _notify(
        app_id, version,
        f"⚠️ 设备 {udid} 用例 {entry['name']} agent 执行失败({last_data})。日志末尾：{last_tail}",
    )
    return {
        "record_id": entry["record_id"],
        "name": entry["name"],
        "module": entry.get("module", ""),
        "platform": platform.capitalize(),
        "device": udid,
        "passed": False,
        "note": f"agent execution failed: {last_data} | {last_tail[-200:]}",
        "steps": [],
        "_current_account": current_account,
    }


def _is_script_mechanism_failure(script_result: dict) -> bool:
    """脚本失败是否属"机制类失败"——即脚本本身失效(动作步失败/定位器全 miss/不支持步),
    应回退 agent 自愈并刷新脚本；区别于"真实断言失败"(取到值但内容不匹配 / 视觉断言判异常),
    那是真实缺陷发现,不回退、直接如实报失败。"""
    if script_result.get("passed"):
        return False
    steps = script_result.get("steps") or []
    # 视觉断言判失败 = 真实 UI 发现,不回退
    if any(s.get("type") == "ASSERT_UI" and not s.get("passed") for s in steps):
        return False
    # 终态硬失败步(排除 soft_assert 软失败,后者不终止流程)
    hard_fail = None
    for s in steps:
        if s.get("passed"):
            continue
        if s.get("type") == "ASSERT" and s.get("soft_assert"):
            continue
        hard_fail = s
    if hard_fail is None:
        return False
    if hard_fail.get("type") == "ASSERT":
        # id/text 断言:定位器全 miss(matched=[])= 脚本失效→回退;取到值但不匹配=真实发现
        m = re.search(r"matched=(\[[^\]]*\])", hard_fail.get("note") or "")
        if m:
            return m.group(1).replace(" ", "") == "[]"
        return False
    # 动作步(TAP/INPUT/PREPARE_STATE/REINSTALL_APP…)或 unsupported = 机制类失败
    return True


def execute_case_with_fallback(app_id: str, platform: str, udid: str, entry: dict,
                               version: str = None, current_account: str = "",
                               wda_port: int = None, result_dir: str = "/tmp",
                               timeout: int = 90 * 60):
    normalized_platform = platform.lower()
    use_case_script = (
        normalized_platform in {"android", "ios"}
    )
    script_path = find_case_script(app_id, platform, entry["record_id"]) if use_case_script else ""
    script_error = ""
    script_failure_note = ""
    if script_path:
        try:
            script_result = run_case_script(app_id, platform, udid, script_path)
            script_result.setdefault("record_id", entry["record_id"])
            script_result.setdefault("name", entry["name"])
            script_result.setdefault("module", entry.get("module", ""))
            script_result.setdefault("order", entry.get("order", ""))
            script_result.setdefault("state_group", entry.get("state_group", ""))
            script_result.setdefault("platform", platform.capitalize())
            script_result.setdefault("device", udid)
            # 脚本通过 → 直接返回;脚本"真实失败"(断言语义不符/视觉异常)→ 如实返回失败。
            # 仅"机制类失败"(脚本失效)才回退 agent 自愈并刷新脚本。
            if script_result.get("passed") or not _is_script_mechanism_failure(script_result):
                # 脚本直接跑完(未回退)——脚本命中率的分子
                script_result["exec_source"] = "script"
                return script_result
            script_failure_note = script_result.get("note", "")
            log.info(
                f"[{udid}] 脚本机制类失败,回退 agent 执行并尝试刷新脚本: "
                f"{entry['record_id']} | {script_failure_note}"
            )
        except Exception:
            script_error = traceback.format_exc(limit=1).strip().splitlines()[-1]
            log.info(f"[{udid}] 脚本执行异常,回退 agent: {entry['record_id']} | {script_error}")

    agent_result = execute_case_via_agent(
        app_id=app_id, platform=platform, udid=udid, entry=entry,
        version=version, current_account=current_account,
        wda_port=wda_port, result_dir=result_dir, timeout=timeout,
    )
    if script_error:
        agent_result["script_fallback"] = True
        agent_result["script_error"] = script_error
    elif script_path and script_failure_note:
        agent_result["script_fallback"] = True
        agent_result["script_failure_note"] = script_failure_note
    # exec_source:有脚本却回退 → script_fallback(脚本失效);本就无脚本 → agent(从零跑)
    agent_result["exec_source"] = "script_fallback" if script_path else "agent"
    if normalized_platform in {"android", "ios"} and agent_result.get("passed"):
        generate_case_script(app_id, platform, agent_result, version=version)
    return agent_result


def run_exploration(app_id: str, version: str, android_udid: str):
    app_dir = os.path.join(PROJECT_ROOT, "apps", app_id)
    index_path = os.path.join(app_dir, "index.md")
    os.makedirs(app_dir, exist_ok=True)
    force_explore = os.environ.get("ORCH_FORCE_EXPLORE", "").strip().lower() in ("1", "true", "yes", "on")
    if not force_explore and os.path.exists(index_path) and os.path.getsize(index_path) > 0:
        log.info(f"App map exists at {index_path}, skipping exploration")
        return
    prompt = (
        f"探索 {app_id} App，版本 {version}，设备 {android_udid}（Android）。"
        f"广度优先遍历各 Tab 和子页面（最大深度2），"
        f"为每个页面截图并分析 UI 树，"
        f"生成 apps/{app_id}/index.md 和 pages/*.md。"
        f"见 common/device.md 了解设备就绪检查规范。"
    )
    runner = resolve_agent_runner()
    skill_dir  = os.path.join(PROJECT_ROOT, ".claude", "skills", app_id)
    common_dir = os.path.join(PROJECT_ROOT, "common")
    cmd = build_agent_command(runner, prompt, skill_dir, common_dir)
    log_path = f"/tmp/explore_{app_id}_{version}.log"
    log.info(f"Starting exploration, log: {log_path}")
    try:
        with open(log_path, "w") as logf:
            r = subprocess.run(cmd, stdout=logf, stderr=logf, timeout=1800)
        if r.returncode == 0 and os.path.exists(index_path):
            log.info(f"Exploration done, index.md generated")
        else:
            log.warning(f"Exploration failed or index.md missing, continuing (fallback to visual)")
    except subprocess.TimeoutExpired:
        log.warning(f"Exploration timeout (30min), continuing")


def _prompt_cases_json(entries: list) -> str:
    return json.dumps(
        [
            {
                "record_id": entry["record_id"],
                "name": entry["name"],
                "module": entry["module"],
                "steps": entry["steps"],
            }
            for entry in entries
        ],
        ensure_ascii=False,
    )


def _prompt_batch_note(batch_idx: int, batch_count: int, current_account: str) -> str:
    return (
        f"\n【批次执行上下文】\n"
        f"当前执行的是该设备第 {batch_idx + 1}/{batch_count} 批，仅执行本批给出的用例。"
        f"已知当前设备账号态：{current_account or '未知或未登录'}。\n"
    )


def _prompt_handoff_note(account_state_path: str) -> str:
    if not account_state_path:
        return ""
    return (
        f"本批结束前，把当前 app 内最终停留的账号写入 `{account_state_path}`。"
        f"若已退出登录或无法确认，写空字符串即可。\n"
    )


def _prompt_batch_finish_note(is_last_batch: bool) -> str:
    if is_last_batch:
        return "本批是该设备最后一批：跑完本批后按正常单设备收尾即可。\n"
    return (
        "本批不是该设备最后一批：跑完本批后不要 delete_session，不要重启 App，不要额外清理首页，"
        "直接退出把现场交还主流程。\n"
    )


def _prompt_startup_completion_note(entries: list) -> str:
    state_groups = {(entry.get("state_group", "") or "").strip() for entry in entries}
    if "启动弹窗" in state_groups:
        return ""
    return (
        "\n【启动流程收口(启动弹窗批次除外)】\n"
        "若执行前发现 App 还停留在首次启动流程（如协议弹窗、青少年守护、首登分流页等），"
        "先主动完成启动流程，把 App 带到可正常执行用例的稳定页，再开始本批用例。"
        "不要把这类首启残留直接当成当前用例失败；只有启动流程完成后仍无法进入目标前置页，"
        "才按真实阻断记失败并继续下一条。\n"
    )


def _prompt_wda_note(platform: str, wda_port: int) -> str:
    if platform.lower() != "ios" or not wda_port:
        return ""
    return (
        f"\n【iOS WDA 已就绪(务必遵守)】\n"
        f"本机已确认设备可直接 create_session 建会话并接管，不要手工传 "
        f"appium:webDriverAgentUrl=http://127.0.0.1:{wda_port} 这类自定义地址；"
        f"现网自建 proxy 通路不稳定，会导致 ECONNREFUSED。\n"
        f"对 iOS 真机，直接调用 create_session（带 appium:udid / bundleId 等必要 capabilities）即可；"
        f"除非日志明确要求，否则不要额外自装/自连另一套 WDA。\n"
    )


def _prompt_reinstall_note(app_id: str, version: str, platform: str, udid: str) -> str:
    if not version:
        return ""
    is_ios = platform.lower() == "ios"
    pkg = PKG_NAMES.get(app_id, "")
    pkg_path = f"/tmp/{app_id}_{version}." + ("ipa" if is_ios else "apk")
    if is_ios:
        cmds = (f"卸载 `tidevice -u {udid} uninstall {pkg}`"
                f"(不在 PATH 时用 `python3 -m tidevice -u {udid} uninstall {pkg}`)；"
                f"重装(不启动) `tidevice -u {udid} install {pkg_path}`")
    else:
        cmds = (f"卸载 `adb -s {udid} uninstall {pkg}`；"
                f"重装(不启动) `adb -s {udid} install -r {pkg_path}`")
    return (
        f"\n【卸载重装类用例(PRECOND 含「卸载重装/重新安装/首次启动/首次安装」)执行前必做】\n"
        f"这类用例要求 App 处于「刚重装、尚未启动」态以重现首次启动弹窗。执行前依次：\n"
        f"① delete_session 结束当前会话；② {cmds}，装完不要 activate；\n"
        f"③ 新建 session 且不预先登录，让首次 activate 触发首启弹窗；④ 再按用例步骤验证首启流程。\n"
        f"连续多条此类用例：每条执行前都各自重装一次(测完上一条 App 已启动，须重新还原首启态)。\n"
        f"重装不影响 WDA(独立 app，保留)；本机安装包路径固定为 {pkg_path}，无需重新下载。\n"
    )


def _prompt_ui_audit_note() -> str:
    if not resolve_ui_audit_enabled():
        return ""
    return (
        "\n【UI 规范自动检查（默认开启，补充断言）】\n"
        "除用例自身的验证点和预期结果外，对本条用例实际经过并截图取证的关键页面追加 UI 规范检查："
        "文本是否截断、重叠、被遮挡，按钮/输入框是否明显不可见或不可点，弹窗是否缺主按钮或关闭出口，"
        "核心内容是否跑出安全区域，加载蒙层是否异常残留，是否存在白屏/黑屏/大面积空白/明显错位。\n"
        "发现 UI 规范问题时，必须把问题作为额外 ASSERT 写进该条 case 的 steps，并附截图或 page source 证据；"
        "没有可验证证据时不要主观判失败。\n"
        "UI 检查只记明显且可复核的问题，不要把轻微间距、颜色偏好、模糊视觉猜测当失败。\n"
    )


def _prompt_locator_note(platform: str) -> str:
    if platform.lower() != "ios":
        return (
            "ACTION/PRECOND 步也要写结构化轨迹字段，供后续生成可执行脚本："
            "script_action（如 tap/input/back/route/prepare_state）、locator（如 by=id/text,value=...）、"
            "locator_fallbacks（可选候选定位数组）、input_value（有输入时必填）、page_hint/route_target（有跳页时尽量填写）。\n\n"
        )
    return (
        "ACTION/PRECOND 步也要写结构化轨迹字段，供后续生成可执行脚本："
        "script_action（如 tap/input/back/route/prepare_state）、locator、locator_fallbacks、input_value、"
        "page_hint/route_target（有跳页时尽量填写）。\n"
        "iOS 定位优先级：优先写 `by=accessibility_id,value=...`，其次 `by=name` / `by=label`，"
        "再次 `by=predicate,value=...`，最后才用 `by=xpath`。避免只给裸文案；若只能给候选，请把稳定候选都写进 locator_fallbacks。\n\n"
    )


def build_prompt(app_id: str, udid: str, platform: str, entries: list,
                 wda_port: int = None, version: str = None,
                 result_path: str = None, current_account: str = "",
                 batch_idx: int = 0, batch_count: int = 1,
                 is_last_batch: bool = True,
                 account_state_path: str = None) -> str:
    shared_context = build_shared_execution_context(app_id)
    result_path = result_path or f"/tmp/result_{udid}.jsonl"
    legacy_result_path = f"/tmp/result_{udid}.jsonl"
    if os.path.realpath(result_path) == os.path.realpath(legacy_result_path):
        result_scope_note = f"结果文件为 {result_path}。"
    else:
        result_scope_note = (
            f"本批只允许写入 {result_path}；不得另写 {legacy_result_path}、"
            f"/private/tmp/result_{udid}.jsonl 或任何自造结果文件。"
        )
    cases_json = _prompt_cases_json(entries)
    batch_note = _prompt_batch_note(batch_idx, batch_count, current_account)
    handoff_note = _prompt_handoff_note(account_state_path)
    batch_finish_note = _prompt_batch_finish_note(is_last_batch)
    startup_completion_note = _prompt_startup_completion_note(entries)
    wda_note = _prompt_wda_note(platform, wda_port)
    reinstall_note = _prompt_reinstall_note(app_id, version, platform, udid)
    ui_audit_note = _prompt_ui_audit_note()
    locator_note = _prompt_locator_note(platform)
    return (
        f"{shared_context}\n\n"
        f"你是{app_id} App 自动化测试工程师。\n"
        f"设备：{udid}（{platform}）\n"
        f"{batch_note}"
        f"{wda_note}\n"
        f"⚠️ 跑的是【线上生产环境】重放动作纪律：\n"
        f"  - 导航/幂等类点击（同意/关闭弹窗、切 tab、页面跳转、打开 H5 等不写业务数据的点击）：若点后 UI 无变化（page source/截图仍停留原页、动作未生效，常见于 iOS WDA click 返回成功但界面未动），可重放该点击最多 2 次；仍无效再判失败。\n"
        f"  - 写操作（提交/下单/支付/发送/确认/保存/领取等会写线上数据的点击）：严禁重放做重试——首次点击服务端可能已成功、仅界面未跳转，重放会重复下单/扣款；这类只做只读断言轮询，不重放动作。\n\n"
        f"【ASSERT 判定契约（务必遵守，见 common/locator.md「ASSERT 取证链」）】\n"
        f"1. 每个 ASSERT 默认判失败，只有取到可验证证据才能判通过。禁止「看起来像/应该是/大概对了」式判定。\n"
        f"2. 取证优先级：① id 取证（appium_find_element，命中 elements.truth.json）"
        f"② 文本/属性取证（appium_get_text / get_element_attribute 比对）"
        f"③ 实在无 id 无文本时才用 appium_screenshot 视觉判定（标低可信）。\n"
        f"3. 反幻觉：声称看到的元素 id 必须存在于真相源 elements.truth.json，否则该 ASSERT 判可疑（不得记 pass）。\n"
        f"4. 断言轮询（只读、生产安全）：判失败前在同页 appium_get_page_source 短轮询 3 次×2s 等页面稳定再终判；这是重查页面，不是重试动作。\n"
        f"5. 每个 ASSERT 步在 steps 里额外记三字段：verify_method（id/text/vision）、evidence（命中的 selector 或截图路径）、confidence（high/low，仅 vision 为 low）。\n"
        f"6. {locator_note}"
        f"【执行纪律（无人值守模式，务必遵守）】\n"
        f"1. 严格按下方给定顺序逐条执行本批用例：不重排、不并行、不跳过。每条用例的前置状态依赖上一条执行后的结果，乱序即失效。\n"
        f"2. 严禁向用户提问或等待确认。你运行在无人值守（--print）模式，任何提问都无人应答，会导致进程空退、所有用例被判失败。遇到不确定项自行按最合理方案决策，并在该条 note 注明所做假设。\n"
        f"3. 遇到真正无法自动化或环境不满足的用例（如真实语音辅导、依赖特定后台数据、需人工介入的外部流程等），不要卡住或反问：直接把该条 passed=false、note 注明原因（如「环境不满足-未执行」「生产不可达-<原因>」），随即继续下一条。**注意：微信登录/微信授权不属于此类——设备上已装微信且已登录测试微信号，必须真实驱动执行，禁止直接判「环境不满足-未执行」跳过；具体操作见下方「微信登录用例」条。**\n"
        f"3b. 【微信登录用例】App 内点「微信登录」后系统会拉起微信 App 的授权确认页：① 若弹出「打开微信」系统 alert，`appium_alert action=accept` 确认跳转；② 切到微信授权页后，用 appium_find_element 找并点确认按钮（文案通常为「登录」「允许」「同意」，底部主按钮），完成授权；③ 微信会自动跳回高途 App，等待并 ASSERT 登录后落地页（首页/绑定手机号页等，按用例预期）。若用例要求「未绑定手机号」路径，授权回跳后应出现绑定/补充手机号引导页；「已绑定手机号」路径则直接进已登录态。全程真实执行（已授权用测试号驱动生产写），不要跳过。若微信侧确实找不到授权按钮或未拉起微信，才按 passed=false、note 注明具体卡点。\n"
        f"4. 账号：多数用例 PRECOND 标了账号（格式「账号：<手机号>」）。执行该用例前，若设备当前登录账号 ≠ 标注账号，就先切换到标注账号（未登录→直接登录；已登录别的账号→先退出登录再登），用验证码登录（矩阵测试账号均为 12 开头，短信验证码一律 1000；个别用例步骤明确给了密码如 Gaotu@123 才用密码）；当前已是该账号则不切换（对应「不切换账号」）。PRECOND 未标账号的用例（登录/首启/未登录类）按其自身步骤执行，不要强行预登录。\n"
        f"5. 仅当遇到【非预期内】的线上业务弹窗（即该弹窗不在当前用例步骤/预期/验证点内）且它会改写生产数据时，才启用弹窗兜底策略：优先寻找并点击最小副作用出口，如 `关闭`、`取消`、`放弃`、`暂不`、`返回`。像“放弃讲义”这类放弃/取消型按钮允许点击；若弹窗本身就是当前用例要验证的对象，则严格按用例步骤执行，不要套用该兜底策略。只有在不存在这些安全出口、剩余按钮都会提交/确认/保存/下单/填写/领取时，才按「生产不可达-弹窗阻断」记失败并继续后续可执行用例。\n"
        f"6. 不要输出阶段性总结、进度汇报、单条结果汇报或向用户复述当前已完成条数；这些内容会让 --print 模式提前结束。除非全部用例都已执行完成，否则只继续执行下一条，不要输出总结性自然语言。\n"
        f"7. {batch_finish_note}"
        f"8. {handoff_note}"
        f"9. Appium MCP 调用纪律：任何 Appium MCP 操作（创建/接管/删除 session、截图、取 page source、查找/点击/输入元素）"
        f"都必须实际调用 appium-mcp 工具；不得用 `true`、空 shell、`pwd/date/echo`、自然语言“准备调用/马上调用”"
        f"代替工具调用。需要创建/接管 session 时，连续 2 次无法发起 MCP 工具调用，立即把当前用例按 passed=false 写入 JSONL，"
        f"note 写明 `MCP session 创建未发起`；其他 MCP 操作连续 2 次无法发起时，note 写明 `MCP 工具调用未发起`，然后继续下一条，禁止空转。\n"
        f"{startup_completion_note}"
        f"{reinstall_note}\n"
        f"{ui_audit_note}\n"
        f"请依次执行以下用例，记录每条的执行结果（通过/失败、失败步骤与原因）。\n"
        f"【结果落盘：务必增量写，抗中途崩溃】每跑完一条用例，立即把该条作为**一行 JSON** "
        f"append 到 {result_path}（{result_scope_note} JSONL：一行一条、一行内不换行、不要包成数组、"
        f"更不要等全部跑完再一次性写）。每条含 name/platform/device/module/passed/duration/steps，"
        f"以及 screenshots（该用例截图的本地绝对路径数组，见 $SHOT_DIR），格式参考 common/parallel.md。"
        f"这样即使中途 429/进程崩溃，已跑完的用例也能被主流程回写。\n\n"
        f"用例列表：\n{cases_json}"
    )


def launch_agent_per_device(app_id: str, groups: dict, wda_ports: dict = None,
                            version: str = None) -> dict:
    runner = resolve_agent_runner()
    wda_ports = wda_ports or {}
    procs = {}
    skill_dir  = os.path.join(PROJECT_ROOT, ".claude", "skills", app_id)
    common_dir = os.path.join(PROJECT_ROOT, "common")

    for udid, group in groups.items():
        prompt   = build_prompt(app_id, udid, group["platform"], group["entries"],
                                wda_port=wda_ports.get(udid), version=version)
        log_path = agent_log_path(udid)
        cmd = build_agent_command(runner, prompt, skill_dir, common_dir)
        with open(log_path, "w") as logf:
            proc = subprocess.Popen(cmd, stdout=logf, stderr=logf)
        procs[udid] = proc
        log.info(f"Launched {group['platform']} {udid} (pid={proc.pid})")
    return procs


def launch_claude_per_device(app_id: str, groups: dict, wda_ports: dict = None,
                             version: str = None) -> dict:
    return launch_agent_per_device(app_id, groups, wda_ports=wda_ports, version=version)


def launch_agent_batch(app_id: str, udid: str, platform: str, entries: list,
                       wda_port: int = None, version: str = None,
                       current_account: str = "", batch_idx: int = 0,
                       batch_count: int = 1, is_last_batch: bool = True,
                       result_dir: str = "/tmp"):
    return orch_execution.launch_agent_batch(
        app_id=app_id,
        udid=udid,
        platform=platform,
        entries=entries,
        build_prompt_fn=build_prompt,
        build_agent_command_fn=build_agent_command,
        resolve_agent_runner_fn=resolve_agent_runner,
        agent_log_path_fn=agent_log_path,
        batch_result_dir_fn=_batch_result_dir,
        batch_result_path_fn=_batch_result_path,
        batch_account_path_fn=_batch_account_path,
        project_root=PROJECT_ROOT,
        log=log,
        wda_port=wda_port,
        version=version,
        current_account=current_account,
        batch_idx=batch_idx,
        batch_count=batch_count,
        is_last_batch=is_last_batch,
        result_dir=result_dir,
    )


def execute_device_batches(app_id: str, udid: str, group: dict,
                           wda_port: int = None, version: str = None,
                           run_id: str = None, result_dir: str = "/tmp",
                           batch_size: int = DEFAULT_BATCH_SIZE,
                           timeout: int = 90 * 60) -> list:
    timeout = _resolve_agent_timeout_seconds(timeout)
    batches = build_execution_batches(group["entries"], batch_size=batch_size)
    aggregate_path = os.path.join(result_dir, f"result_{udid}.jsonl")
    if os.path.exists(aggregate_path):
        os.remove(aggregate_path)

    current_account = ""
    aggregate_cases = []
    total = len(group["entries"])

    for batch_idx, batch in enumerate(batches):
        batch_dir = _batch_result_dir(result_dir, udid, batch_idx)
        shutil.rmtree(batch_dir, ignore_errors=True)
        os.makedirs(batch_dir, exist_ok=True)
        if run_id:
            run_status.update_device(run_id, udid, **{
                "state": "running",
                "total": total,
                "done": len(aggregate_cases),
                "pass": sum(1 for c in aggregate_cases if c.get("passed")),
                "fail": sum(1 for c in aggregate_cases if not c.get("passed")),
                "platform": group["platform"],
            })
        script_entries = [entry for entry in batch
                          if entry.get("record_id")
                          and find_case_script(app_id, group["platform"].lower(), entry["record_id"])]
        if not script_entries:
            proc = launch_agent_batch(
                app_id, udid, group["platform"], batch,
                wda_port=wda_port, version=version,
                current_account=current_account,
                batch_idx=batch_idx, batch_count=len(batches),
                is_last_batch=(batch_idx == len(batches) - 1),
                result_dir=result_dir,
            )
            batch_results = collect_results(
                {udid: proc},
                result_dir=batch_dir,
                timeout=timeout,
                app_id=app_id,
                version=version,
                run_id=run_id,
                poll_interval=10,
                device_totals={udid: {"total": len(batch), "platform": group["platform"]}},
            )
            batch_data = batch_results.get(udid)
            batch_cases = _load_batch_cases_with_legacy(
                result_dir, udid, batch_idx, batch, batch_data,
                already_done=len(aggregate_cases),
            )
            if batch_cases:
                # agent 结果只写 source_record_id（见 skill 结果 schema）；按 entries
                # backfill 出 record_id/name/module 等，否则下游固化与写表拿不到 record_id。
                # launch_agent_per_device 路径已 hydrate，此 execute_device_batches 路径此前漏了。
                batch_cases = _hydrate_batch_cases(batch_cases, batch)
                batch_cases = _dedupe_batch_cases(batch_cases, batch)
                for case in batch_cases:
                    # 本批无任何现成脚本(进入此分支的前提),全部从零跑 agent
                    case.setdefault("exec_source", "agent")
                    if case.get("passed"):
                        try:
                            generate_case_script(app_id, group["platform"].lower(), case)
                        except Exception as e:
                            # 固化是 best-effort 副产物，任何异常都不许拖垮本批/整轮执行
                            log.warning(f"用例脚本固化失败(已忽略): "
                                        f"record_id={case.get('record_id')!r} err={e}")
                _attach_execution_version(batch_cases, version)
                _append_jsonl(aggregate_path, batch_cases)
                aggregate_cases.extend(batch_cases)
                if batch_cases:
                    write_results_to_table(app_id, group["platform"].lower(), batch_cases)
                current_account = _read_account_state(_batch_account_path(result_dir, udid, batch_idx)) or current_account
            else:
                reason = (
                    f"agent 执行超时未落盘结果: batch {batch_idx + 1}/{len(batches)}"
                    if batch_data == "timeout"
                    else f"agent 执行异常未落盘结果: batch {batch_idx + 1}/{len(batches)}"
                )
                log.warning(f"{udid} {reason}，本批 {len(batch)} 条用例合成失败后继续后续批次")
                batch_cases = _build_agent_failure_cases(batch, udid, group["platform"], reason)
                _attach_execution_version(batch_cases, version)
                _append_jsonl(aggregate_path, batch_cases)
                aggregate_cases.extend(batch_cases)
                write_results_to_table(app_id, group["platform"].lower(), batch_cases)
                if run_id:
                    run_status.update_device(run_id, udid, **{
                        "state": "running",
                        "total": total,
                        "done": len(aggregate_cases),
                        "pass": sum(1 for c in aggregate_cases if c.get("passed")),
                        "fail": sum(1 for c in aggregate_cases if not c.get("passed")),
                        "platform": group["platform"],
                    })
            continue

        batch_cases = []
        for entry in batch:
            result = execute_case_with_fallback(
                app_id=app_id,
                platform=group["platform"].lower(),
                udid=udid,
                entry=entry,
                version=version,
                current_account=current_account,
                wda_port=wda_port,
                result_dir=result_dir,
                timeout=timeout,
            )
            current_account = result.pop("_current_account", current_account) or current_account
            batch_cases.append(result)
        _attach_execution_version(batch_cases, version)
        _append_jsonl(aggregate_path, batch_cases)
        aggregate_cases.extend(batch_cases)
        if batch_cases:
            write_results_to_table(app_id, group["platform"].lower(), batch_cases)

    if run_id:
        run_status.update_device(run_id, udid, **{
            "state": "done",
            "total": total,
            "done": len(aggregate_cases),
            "pass": sum(1 for c in aggregate_cases if c.get("passed")),
            "fail": sum(1 for c in aggregate_cases if not c.get("passed")),
            "platform": group["platform"],
        })
    return aggregate_cases


def execute_batches_for_groups(app_id: str, groups: dict, wda_ports: dict = None,
                               version: str = None, run_id: str = None,
                               result_dir: str = "/tmp",
                               batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    wda_ports = wda_ports or {}
    results = {}
    max_workers = max(1, len(groups))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                execute_device_batches,
                app_id, udid, group,
                wda_port=wda_ports.get(udid),
                version=version, run_id=run_id,
                result_dir=result_dir, batch_size=batch_size,
            ): udid
            for udid, group in groups.items()
        }
        for future in as_completed(future_map):
            results[future_map[future]] = future.result()
    return results


def _resolve_obj_token(app_token: str) -> str:
    """结果表可能挂在知识库（wiki）下，drive 媒体上传需真实 obj_token；普通 base 原样返回。"""
    return orch_result_table.resolve_obj_token(app_token, _get_token)


def _upload_bitable_image(parent_obj: str, file_path: str, token: str):
    """上传图片到 bitable，返回 file_token；失败返回 None。"""
    return orch_result_table.upload_bitable_image(parent_obj, file_path, token, log)
def _coerce_number_field(value):
    return orch_result_table.coerce_number_field(value, _text_field)


def _coerce_datetime_field(value=None):
    return orch_result_table.coerce_datetime_field(value, time.time)


def _attach_execution_version(cases: list, version: str = None) -> list:
    if not version:
        return cases
    for case in cases:
        case.setdefault("app_version", version)
    return cases


def write_results_to_table(app_id: str, platform: str, cases: list, version: str = None):
    """把某平台的执行结果 batch_create 写入对应结果表，含截图上传。"""
    cfg = RESULT_TABLES.get(app_id)
    table_id = cfg.get(platform.lower()) if cfg else None
    if not cfg or not table_id:
        log.warning(f"{app_id} 无 {platform} 结果表配置，跳过写入结果表")
        return

    token = _get_token()
    obj_token = _resolve_obj_token(cfg["app_token"])  # 截图上传用

    records = []
    for c in cases:
        execution_version = version or c.get("app_version", "")
        failed = [
            s for s in c.get("steps", [])
            if not (s.get("passed") if "passed" in s else s.get("pass", True))
        ]
        detail = "\n".join(
            f"{i}、[{s.get('type','')}] {s.get('text','')} ❌"
            + (f" 原因：{s['note']}" if s.get("note") else "")
            for i, s in enumerate(failed, 1)
        )
        passed = c.get("passed", True)

        # 视觉低可信通过 → 标注待人工复核
        review = _lowconf_review_steps(c)
        review_note = ""
        if review:
            review_note = "⚠️ 视觉判定待复核：\n" + "\n".join(
                f"・[{s.get('type','')}] {s.get('text','')}" for s in review)
        case_note = (c.get("note") or "").strip() if not passed else ""
        full_detail = "\n".join(x for x in (detail, case_note, review_note) if x) \
            or ("全部通过" if passed else "")

        fields = {
            "编号":     _coerce_number_field(c.get("order", "")),
            "执行版本": execution_version,
            "执行时间": _coerce_datetime_field(c.get("execution_time")),
            "状态组":   c.get("state_group", ""),
            "执行设备": c.get("device", ""),
            "用例名称": c.get("name", ""),
            "执行结果": "通过" if passed else "失败",
            "执行详情": full_detail,
        }
        if passed and c.get("record_id"):
            fields["record_id"] = c.get("record_id")
        fields = {k: v for k, v in fields.items() if v != ""}

        # 上传截图（最多 20 张/条）
        shots = (c.get("screenshots") or [])[:20]
        tokens = [{"file_token": t} for t in
                  (_upload_bitable_image(obj_token, p, token) for p in shots) if t]
        if tokens:
            fields["截图"] = tokens

        records.append({"fields": fields})

    url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps"
           f"/{cfg['app_token']}/tables/{table_id}/records/batch_create")
    written = 0
    for i in range(0, len(records), 100):
        chunk = records[i:i + 100]
        body  = json.dumps({"records": chunk}, ensure_ascii=False).encode("utf-8")
        req   = urllib.request.Request(
            url, data=body,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=utf-8"},
            method="POST")
        try:
            resp = json.load(urllib.request.urlopen(req))
            if resp.get("code") == 0:
                written += len(chunk)
            else:
                log.warning(f"结果表写入失败 code={resp.get('code')} msg={resp.get('msg')}")
        except Exception as e:
            log.warning(f"结果表写入异常：{e}")
    log.info(f"{platform} {written}/{len(records)} 条结果已写入结果表")


def archive_result_table(app_id: str, platform: str):
    return orch_result_table.archive_result_table(
        app_id=app_id,
        platform=platform,
        result_tables=RESULT_TABLES,
        get_token_fn=_get_token,
        log=log,
    )


def archive_result_tables(app_id: str, platforms: set):
    return orch_result_table.archive_result_tables(app_id, platforms, archive_result_table)


def _tail_file(path: str, n: int = 200) -> str:
    return orch_reporting.tail_file(path, n)


def _incr_status(run_id, udid, path):
    """进程仍存活时,仅用当前(可能是增量/半成品)结果文件刷新 /status,绝不判完成。"""
    if not run_id:
        return
    orch_reporting.incr_status(run_id, udid, path, _load_jsonl, run_status)


def collect_results(procs: dict, result_dir: str = "/tmp",
                    timeout: int = 90 * 60,
                    app_id: str = None, version: str = None,
                    run_id: str = None, poll_interval: int = 10,
                    device_totals: dict = None) -> dict:
    return orch_reporting.collect_results(
        procs=procs,
        load_jsonl_fn=_load_jsonl,
        incr_status_fn=_incr_status,
        tail_file_fn=_tail_file,
        agent_log_path_fn=agent_log_path,
        notify_fn=_notify,
        run_status_module=run_status,
        log=log,
        result_dir=result_dir,
        timeout=timeout,
        app_id=app_id,
        version=version,
        run_id=run_id,
        poll_interval=poll_interval,
        device_totals=device_totals,
    )


def generate_reports(app_id: str, version: str, results: dict, duration: int,
                     start_time_str: str = None, device_totals: dict = None,
                     interrupted: bool = False, write_tables: bool = True):
    return orch_reporting.generate_reports(
        app_id=app_id,
        version=version,
        results=results,
        duration=duration,
        project_root=PROJECT_ROOT,
        lowconf_review_steps_fn=_lowconf_review_steps,
        write_results_to_table_fn=write_results_to_table,
        notify_fn=_notify,
        subprocess_module=subprocess,
        log=log,
        start_time_str=start_time_str,
        device_totals=device_totals,
        interrupted=interrupted,
        write_tables=write_tables,
    )


# ---- 中断/崩溃兜底：存活跑状态 + 幂等 finalize ----
# _INFLIGHT 在进入执行阶段后填充，供信号处理器/异常兜底读取当前进度做收尾。
_INFLIGHT: dict = {}
_FINALIZED: bool = False


def _read_partial_results(udids, result_dir: str = "/tmp") -> dict:
    """从磁盘读取当前已有的 result 文件；缺失/损坏的跳过(交给 device_totals 算未执行)。"""
    out = {}
    for udid in udids:
        path = os.path.join(result_dir, f"result_{udid}.jsonl")
        cases = _load_jsonl(path)
        if cases:
            out[udid] = cases
    return out


def finalize(reason: str = None, results: dict = None, write_tables: bool = None) -> bool:
    """幂等收尾：回写结果表 + 发报告(必发,含未执行统计) + 清理 + finish。
    reason 非空表示中断/异常场景(报告加 ⚠️ 前缀)。返回 True 表示本次执行了收尾。"""
    global _FINALIZED
    if _FINALIZED or not _INFLIGHT:
        return False
    _FINALIZED = True
    info   = _INFLIGHT
    run_id = info["run_id"]
    dtot   = info["device_totals"]
    rdir   = info.get("result_dir", "/tmp")
    if write_tables is None:
        write_tables = info.get("write_tables", True)
    if results is None:  # 中断路径：collect_results 未正常返回，直接读磁盘现有结果
        results = _read_partial_results(list(dtot.keys()), rdir)
    duration = int(time.time() - info["start_time"])
    try:
        run_status.set_phase(run_id, "reporting",
                             "执行中断，生成部分报告" if reason else "生成报告")
        generate_reports(info["app_id"], info["version"], results, duration,
                         start_time_str=info["start_time_str"],
                         device_totals=dtot, interrupted=bool(reason),
                         write_tables=write_tables)
    except Exception as e:  # 报告失败不能吞掉 finish
        log.exception(f"finalize 生成报告失败：{e}")
    finally:
        for udid in dtot:
            path = os.path.join(rdir, f"result_{udid}.jsonl")
            if os.path.exists(path):
                os.remove(path)
        passed = sum(1 for d in results.values() if isinstance(d, list)
                     for c in d if c.get("passed"))
        total  = sum(v.get("total", 0) for v in dtot.values())
        run_status.finish(run_id, "interrupted" if reason else "done",
                          reason or "执行完成",
                          total=total, passed=passed, duration=duration)
    return True


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--app",     required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--apk-url", dest="apk_url", default="")
    p.add_argument("--ipa-url", dest="ipa_url", default="")
    p.add_argument("--platform", choices=["android", "ios"], default=None,
                   help="只跑指定单端；不传则按提供的 url 跑双端")
    return p.parse_args()


def _run(app_id, version, apk_url, ipa_url, platforms=None, run_id=None):
    # platforms: 要执行的平台集合，默认按传入的 url 决定
    if platforms is None:
        platforms = set()
        if apk_url:
            platforms.add("android")
        if ipa_url:
            platforms.add("ios")
    if not platforms:
        _notify(app_id, version, "❌ 未提供任何平台的下载地址，终止")
        run_status.finish(run_id, "failed", "未提供下载地址")
        return

    run_status.init_run(run_id, app_id, version, "/".join(sorted(platforms)))
    devices = load_devices(app_id)

    # 1. Download（仅下载要执行的平台）
    run_status.set_phase(run_id, "downloading", "下载安装包")
    apk_path = f"/tmp/{app_id}_{version}.apk"
    ipa_path = f"/tmp/{app_id}_{version}.ipa"
    prune_old_packages(app_id, version, platforms)
    if "android" in platforms:
        if not ensure_package(apk_url, apk_path, "APK"):
            _notify(app_id, version, "❌ APK 下载失败，终止")
            run_status.finish(run_id, "failed", "APK 下载失败")
            return
    if "ios" in platforms:
        ipa_dl = resolve_ios_ipa_url(ipa_url)
        if not ensure_package(ipa_dl, ipa_path, "IPA"):
            _notify(app_id, version, "❌ IPA 下载失败，终止")
            run_status.finish(run_id, "failed", "IPA 下载失败")
            return

    # 2. Install（仅安装要执行的平台）
    run_status.set_phase(run_id, "installing", "安装到设备")
    android_ok, ios_ok = [], []
    if "android" in platforms:
        for d in devices["android"]:
            if install_android(apk_path, d["udid"]):
                android_ok.append(d)
                log.info(f"Android {d['udid']} installed")
            else:
                log.warning(f"Android {d['udid']} install failed, skipping")

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
                bundle_id = PKG_NAMES.get(app_id, "")
                if not ensure_ios_network_permission_ready(app_id, d["udid"], bundle_id, port):
                    _notify(app_id, version,
                            f"⚠️ iOS {d['udid']} 网络权限预热失败，跳过该设备，避免 App 无网络权限异常执行")
                    log.warning(f"iOS {d['udid']} network permission prepare failed, skipping")
                    continue
                ios_ok.append(d)
                wda_ports[d["udid"]] = port
            else:
                _notify(app_id, version,
                        f"⚠️ iOS {d['udid']} WDA 未就绪，环境阻断，跳过（不写结果表）")
                log.warning(f"iOS {d['udid']} WDA not ready, skipping (env blocked)")

    if not android_ok and not ios_ok:
        _notify(app_id, version, "❌ 所有设备安装失败，终止")
        run_status.finish(run_id, "failed", "所有设备安装失败")
        return

    log.info(f"Install done: Android {len(android_ok)}, iOS {len(ios_ok)}")

    # 3. Explore (new version) —— 仅 Android 端触发
    if android_ok:
        run_status.set_phase(run_id, "exploring", "新版本探索建图")
        run_exploration(app_id, version, android_ok[0]["udid"])
        reset_apps_after_exploration(
            app_id,
            [d["udid"] for d in android_ok],
            [d["udid"] for d in ios_ok],
        )

    # 4. Read Bitable
    run_status.set_phase(run_id, "fetching_cases", "读取用例")
    log.info("Fetching Bitable cases...")
    try:
        entries = fetch_cases(app_id)
    except Exception as e:
        _notify(app_id, version, f"❌ Bitable 读取失败：{e}")
        run_status.finish(run_id, "failed", f"Bitable 读取失败：{e}")
        return
    groups = _prepare_executable_groups(app_id, version, entries, android_ok, ios_ok, platforms)
    if not groups:
        run_status.finish(run_id, "done", "无可执行用例")
        return

    total = sum(len(g["entries"]) for g in groups.values())
    log.info(f"{total} cases across {len(groups)} devices")

    archive_result_tables(app_id, platforms)

    # 5. Parallel execution
    run_status.set_phase(run_id, "executing", f"{total} 条用例 × {len(groups)} 台设备执行中")
    for udid, g in groups.items():
        run_status.update_device(run_id, udid, **{
            "state": "running", "total": len(g["entries"]),
            "done": 0, "pass": 0, "fail": 0, "platform": g["platform"]})
    _notify(app_id, version, f"▶️ 开始执行：{total} 条用例 × {len(groups)} 台设备（{'/'.join(sorted(platforms))}）")
    start_time_str = datetime.datetime.now().strftime("%H:%M:%S")
    start_time = time.time()

    # 登记存活跑状态，供信号/异常兜底做幂等收尾（崩溃/被杀也回写+发报告）
    global _INFLIGHT, _FINALIZED
    _FINALIZED = False
    _INFLIGHT = {
        "run_id": run_id, "app_id": app_id, "version": version,
        "start_time": start_time, "start_time_str": start_time_str,
        "result_dir": "/tmp",
        "write_tables": False,
        "device_totals": {u: {"total": len(g["entries"]), "platform": g["platform"]}
                          for u, g in groups.items()},
    }

    results = execute_batches_for_groups(app_id, groups, wda_ports=wda_ports,
                                         version=version, run_id=run_id,
                                         result_dir="/tmp")
    duration = int(time.time() - start_time)
    log.info(f"Execution done, total time {duration}s")

    # 6~7. 报告 + 回写 + 清理 + finish（正常路径带已收集结果）
    finalize(results=results, write_tables=False)
    log.info("Done")


def main():
    args    = parse_args()
    app_id  = args.app
    version = args.version
    platforms = {args.platform} if args.platform else None

    # pid 文件带平台后缀，允许 Android / iOS 同一版本并行独立执行
    suffix   = f"_{args.platform}" if args.platform else ""
    run_id   = f"{app_id}_{version}{suffix}"
    logging_setup.bind_run_id(run_id)

    # 注入仓库外本地凭据(headless claude 需要 ANTHROPIC_API_KEY)，子进程自动继承
    secret_keys = load_runner_secrets()
    if secret_keys:
        log.info(f"已加载 runner 凭据: {', '.join(secret_keys)}")
    else:
        log.info("未发现 runner 凭据文件(~/.config/appium-matrix/runner.env)")

    pid_file = f"/tmp/orchestrate_{app_id}_{version}{suffix}.pid"
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    # 被 kill(SIGTERM)/Ctrl-C(SIGINT) 时也收尾：回写已有结果 + 发报告，再退出
    def _sig_handler(signum, frame):
        name = signal.Signals(signum).name
        log.warning(f"收到信号 {name}，执行 finalize 收尾后退出")
        finalize(reason=f"⚠️ 执行中断（{name}），部分结果")
        sys.exit(128 + signum)
    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    try:
        _run(app_id, version, args.apk_url, args.ipa_url, platforms, run_id=run_id)
    except Exception as e:
        log.exception("orchestrate 未捕获异常")
        # _INFLIGHT 已登记则走 finalize（报告+finish）；否则说明崩在执行前，直接判失败
        if not finalize(reason=f"⚠️ 未捕获异常：{e}"):
            run_status.finish(run_id, "failed", f"未捕获异常：{e}")
        raise
    finally:
        if os.path.exists(pid_file):
            os.remove(pid_file)


if __name__ == "__main__":
    main()
