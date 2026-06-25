#!/usr/bin/env python3
import argparse, json, os, subprocess, sys, time
import urllib.request, urllib.error, urllib.parse, datetime
import plistlib
import yaml

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
        print(f"[WARN] itms-services 链接无 url 参数：{url}")
        return url
    try:
        with urllib.request.urlopen(plist_url, timeout=30) as resp:
            manifest = plistlib.loads(resp.read())
        for item in manifest.get("items", []):
            for asset in item.get("assets", []):
                if asset.get("kind") == "software-package" and asset.get("url"):
                    return asset["url"]
    except Exception as e:
        print(f"[WARN] 解析 iOS manifest 失败：{e}")
    return url


def download_file(url: str, dest: str) -> bool:
    r = subprocess.run(["curl", "-L", "-o", dest, url], capture_output=True)
    return r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 1_000_000


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
        print(f"[WARN] Feishu notify failed: {e}")


def _notify(app_id: str, version: str, message: str):
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


def _text_field(value) -> str:
    if isinstance(value, list):
        return "".join(item.get("text", "") for item in value)
    return str(value) if value else ""


def _extract_udid(label: str) -> str:
    """
    设备字段是单选，选项名形如 '华为nova12pro：26KUT24202013751' 或
    'iphone12:00008101-001E28D436E0001E'，取冒号（全/半角）后的真实 UDID。
    """
    if not label:
        return ""
    s = label.replace("：", ":")
    return s.rsplit(":", 1)[-1].strip() if ":" in s else label.strip()


def parse_record(record: dict) -> dict:
    fields = record["fields"]
    num    = fields.get("用例编号", "")
    name   = _text_field(fields.get("用例名称", ""))
    steps  = []

    for line in _text_field(fields.get("预置条件", "")).splitlines():
        line = line.strip()
        if line:
            steps.append({"type": "PRECOND", "text": line})

    raw_steps = _text_field(fields.get("测试步骤", ""))
    for line in raw_steps.splitlines():
        line = line.strip()
        if line:
            steps.append({"type": "ACTION", "text": line})

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
        "android_device": _extract_udid(_text_field(fields.get("android执行设备", ""))),
        "ios_device":     _extract_udid(_text_field(fields.get("ios执行设备", ""))),
        "module":         _text_field(fields.get("模块", "")),
    }


def fetch_cases(app_id: str) -> list:
    cfg   = BITABLE_CONFIGS[app_id]
    token = _get_token()
    url   = (f"https://open.feishu.cn/open-apis/bitable/v1/apps"
             f"/{cfg['app_token']}/tables/{cfg['table_id']}/records/search")
    body  = json.dumps({
        "filter": {
            "conjunction": "and",
            "conditions": [{"field_name": "是否自动化执行", "operator": "is",
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


def run_exploration(app_id: str, version: str, android_udid: str):
    index_path = os.path.join(PROJECT_ROOT, "apps", app_id, version, "index.md")
    if os.path.exists(index_path):
        print(f"[INFO] App map exists at {index_path}, skipping exploration")
        return

    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    prompt = (
        f"探索 {app_id} App，版本 {version}，设备 {android_udid}（Android）。"
        f"广度优先遍历各 Tab 和子页面（最大深度2），"
        f"为每个页面截图并分析 UI 树，"
        f"生成 apps/{app_id}/{version}/index.md 和 pages/*.md。"
        f"见 common/device.md 了解设备就绪检查规范。"
    )
    skill_dir  = os.path.join(PROJECT_ROOT, ".claude", "skills", app_id)
    common_dir = os.path.join(PROJECT_ROOT, "common")
    cmd = ["claude", "--add-dir", skill_dir, "--add-dir", common_dir, "--print", prompt]
    log_path = f"/tmp/explore_{app_id}_{version}.log"
    print(f"[INFO] Starting exploration, log: {log_path}")
    try:
        with open(log_path, "w") as log:
            r = subprocess.run(cmd, stdout=log, stderr=log, timeout=1800)
        if r.returncode == 0 and os.path.exists(index_path):
            print(f"[INFO] Exploration done, index.md generated")
        else:
            print(f"[WARN] Exploration failed or index.md missing, continuing (fallback to visual)")
    except subprocess.TimeoutExpired:
        print(f"[WARN] Exploration timeout (30min), continuing")


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
        print(f"[INFO] Launched {group['platform']} {udid} (pid={proc.pid})")
    return procs


def _tail_file(path: str, n: int = 200) -> str:
    try:
        with open(path) as f:
            return f.read()[-n:].strip().replace("\n", " ")
    except OSError:
        return ""


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
                    print(f"[INFO] {udid} done, results read")
                except json.JSONDecodeError:
                    pass  # 文件还在写，下轮再读
                continue
            # 无结果文件且进程已退出 → 它没写结果就挂了（如 429 日限额），立即判失败，不空等
            proc = procs.get(udid)
            if proc and proc.poll() is not None:
                tail = _tail_file(f"/tmp/claude_{udid}.log")
                print(f"[WARN] {udid} 进程已退出(code={proc.returncode})却无结果，判失败。日志末尾：{tail}")
                results[udid] = "failed"
                pending.discard(udid)
        if pending:
            time.sleep(10)

    for udid in pending:
        print(f"[WARN] {udid} timeout, killing")
        proc = procs.get(udid)
        if proc and proc.poll() is None:
            proc.kill()
        results[udid] = "timeout"

    return results


def generate_reports(app_id: str, version: str, results: dict, duration: int, start_time_str: str = None):
    start_time = start_time_str or datetime.datetime.now().strftime("%H:%M:%S")
    script = os.path.join(PROJECT_ROOT, "scripts", "wiki_report.py")

    android_cases, ios_cases = [], []
    for udid, data in results.items():
        if data in ("timeout", "failed"):
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
             "--cases", json.dumps(cases, ensure_ascii=False),
             "--no-notify"],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if "Wiki 报告已创建" in line:
                url = line.split("：")[-1].strip()
                wiki_urls[platform] = url
                print(line)

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


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--app",     required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--apk-url", dest="apk_url", default="")
    p.add_argument("--ipa-url", dest="ipa_url", default="")
    p.add_argument("--platform", choices=["android", "ios"], default=None,
                   help="只跑指定单端；不传则按提供的 url 跑双端")
    return p.parse_args()


def _run(app_id, version, apk_url, ipa_url, platforms=None):
    # platforms: 要执行的平台集合，默认按传入的 url 决定
    if platforms is None:
        platforms = set()
        if apk_url:
            platforms.add("android")
        if ipa_url:
            platforms.add("ios")
    if not platforms:
        _notify(app_id, version, "❌ 未提供任何平台的下载地址，终止")
        return

    devices = load_devices(app_id)

    # 1. Download（仅下载要执行的平台）
    apk_path = f"/tmp/{app_id}_{version}.apk"
    ipa_path = f"/tmp/{app_id}_{version}.ipa"
    if "android" in platforms:
        print(f"[INFO] Downloading APK: {apk_url}")
        if not download_file(apk_url, apk_path):
            _notify(app_id, version, "❌ APK 下载失败，终止")
            return
    if "ios" in platforms:
        ipa_dl = resolve_ios_ipa_url(ipa_url)
        print(f"[INFO] Downloading IPA: {ipa_dl}")
        if not download_file(ipa_dl, ipa_path):
            _notify(app_id, version, "❌ IPA 下载失败，终止")
            return

    # 2. Install（仅安装要执行的平台）
    android_ok, ios_ok = [], []
    if "android" in platforms:
        for d in devices["android"]:
            if install_android(apk_path, d["udid"]):
                android_ok.append(d)
                print(f"[INFO] Android {d['udid']} installed")
            else:
                print(f"[WARN] Android {d['udid']} install failed, skipping")

    if "ios" in platforms:
        for d in devices["ios"]:
            if install_ios(ipa_path, d["udid"]):
                ios_ok.append(d)
                print(f"[INFO] iOS {d['udid']} installed")
            else:
                print(f"[WARN] iOS {d['udid']} install failed, skipping")

    if not android_ok and not ios_ok:
        _notify(app_id, version, "❌ 所有设备安装失败，终止")
        return

    print(f"[INFO] Install done: Android {len(android_ok)}, iOS {len(ios_ok)}")

    # 3. Explore (new version) —— 仅 Android 端触发
    if android_ok:
        run_exploration(app_id, version, android_ok[0]["udid"])

    # 4. Read Bitable
    print("[INFO] Fetching Bitable cases...")
    try:
        entries = fetch_cases(app_id)
    except Exception as e:
        _notify(app_id, version, f"❌ Bitable 读取失败：{e}")
        return
    groups  = group_by_device(entries)
    # 仅保留本次执行平台、且安装成功（已连接）的设备组，避免等待离线设备超时
    installed = {d["udid"] for d in android_ok} | {d["udid"] for d in ios_ok}
    skipped   = {u: g for u, g in groups.items()
                 if g["platform"].lower() in platforms and u not in installed}
    for udid, g in skipped.items():
        print(f"[WARN] 跳过 {g['platform']} 设备 {udid}（未连接/未安装），{len(g['entries'])} 条用例不执行")
    groups  = {u: g for u, g in groups.items()
               if g["platform"].lower() in platforms and u in installed}
    if not groups:
        _notify(app_id, version, f"⚠️ {app_id} {version} 无可执行用例（{'/'.join(sorted(platforms))}，已连接设备上无标记用例）")
        return

    cfg = BITABLE_CONFIGS[app_id]
    total = sum(len(g["entries"]) for g in groups.values())
    print(f"[INFO] {total} cases across {len(groups)} devices")

    # 5. Parallel execution
    start_time_str = datetime.datetime.now().strftime("%H:%M:%S")
    start_time = time.time()
    procs   = launch_claude_per_device(app_id, groups,
                                        cfg["app_token"], cfg["table_id"])
    results = collect_results(procs)
    duration = int(time.time() - start_time)
    print(f"[INFO] Execution done, total time {duration}s")

    # 6. Generate reports
    generate_reports(app_id, version, results, duration, start_time_str=start_time_str)

    # 7. Cleanup temp files
    for udid in groups:
        path = f"/tmp/result_{udid}.json"
        if os.path.exists(path):
            os.remove(path)
    print("[INFO] Done")


def main():
    args    = parse_args()
    app_id  = args.app
    version = args.version
    platforms = {args.platform} if args.platform else None

    # pid 文件带平台后缀，允许 Android / iOS 同一版本并行独立执行
    suffix   = f"_{args.platform}" if args.platform else ""
    pid_file = f"/tmp/orchestrate_{app_id}_{version}{suffix}.pid"
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    try:
        _run(app_id, version, args.apk_url, args.ipa_url, platforms)
    finally:
        if os.path.exists(pid_file):
            os.remove(pid_file)


if __name__ == "__main__":
    main()
