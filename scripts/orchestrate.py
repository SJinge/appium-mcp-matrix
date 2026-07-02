#!/usr/bin/env python3
import argparse, json, os, subprocess, sys, time
import urllib.request, urllib.error, urllib.parse, datetime
import plistlib
import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
from feishu_config import APP_ID, APP_SECRET, GROUP_CHAT_ID, BITABLE_CONFIGS, RESULT_TABLES
import run_status
import logging_setup
import ios_wda

log = logging_setup.get_logger("orchestrate", logfile="orchestrate.log")

PKG_NAMES = {
    "gaotu":   "com.gaotu100.superclass",
    "tutu":    "com.gaotu100.tutu",
    "jingpin": "com.gaotu100.jingpin",
    "gongkao": "com.gaotu100.gongkao",
    "xinli":   "com.gaotu100.xinli",
    "ketang":  "com.gaotu100.ketang",
}

DEFAULT_WDA_TEAM   = "5YX44746D6"
DEFAULT_WDA_BUNDLE = "com.shijinge.WebDriverAgentRunner"
DEFAULT_WDA_PORT   = 8100


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
    # tidevice CLI 常不在 PATH，用同解释器的 -m 调用更稳
    r = subprocess.run(
        [sys.executable, "-m", "tidevice", "-u", udid, "install", ipa_path],
        capture_output=True, text=True
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0 or "Complete" in out


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
        log.warning(f"Feishu notify failed: {e}")


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
        log.info(f"App map exists at {index_path}, skipping exploration")
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
        f"【ASSERT 判定契约（务必遵守，见 common/locator.md「ASSERT 取证链」）】\n"
        f"1. 每个 ASSERT 默认判失败，只有取到可验证证据才能判通过。禁止「看起来像/应该是/大概对了」式判定。\n"
        f"2. 取证优先级：① id 取证（appium_find_element，命中 elements.truth.json）"
        f"② 文本/属性取证（appium_get_text / get_element_attribute 比对）"
        f"③ 实在无 id 无文本时才用 appium_screenshot 视觉判定（标低可信）。\n"
        f"3. 反幻觉：声称看到的元素 id 必须存在于真相源 elements.truth.json，否则该 ASSERT 判可疑（不得记 pass）。\n"
        f"4. 断言轮询（只读、生产安全）：判失败前在同页 appium_get_page_source 短轮询 3 次×2s 等页面稳定再终判；这是重查页面，不是重试动作。\n"
        f"5. 每个 ASSERT 步在 steps 里额外记三字段：verify_method（id/text/vision）、evidence（命中的 selector 或截图路径）、confidence（high/low，仅 vision 为 low）。\n\n"
        f"请依次执行以下用例，记录每条的执行结果（通过/失败、失败步骤与原因）。\n"
        f"全部执行完成后，将结果写入 /tmp/result_{udid}.json"
        f"（JSON 数组，每条含 name/platform/device/module/passed/duration/steps，"
        f"以及 screenshots（该用例截图的本地绝对路径数组，见 $SHOT_DIR），"
        f"格式参考 common/parallel.md）。结果由主流程统一写入飞书结果表，无需回写 Bitable。\n\n"
        f"用例列表：\n{cases_json}"
    )


def launch_claude_per_device(app_id: str, groups: dict, wda_ports: dict = None) -> dict:
    wda_ports = wda_ports or {}
    procs = {}
    skill_dir  = os.path.join(PROJECT_ROOT, ".claude", "skills", app_id)
    common_dir = os.path.join(PROJECT_ROOT, "common")

    for udid, group in groups.items():
        prompt   = build_prompt(app_id, udid, group["platform"], group["entries"],
                                wda_port=wda_ports.get(udid))
        log_path = f"/tmp/claude_{udid}.log"
        cmd = ["claude", "--add-dir", skill_dir, "--add-dir", common_dir,
               "--print", prompt]
        with open(log_path, "w") as logf:
            proc = subprocess.Popen(cmd, stdout=logf, stderr=logf)
        procs[udid] = proc
        log.info(f"Launched {group['platform']} {udid} (pid={proc.pid})")
    return procs


def _resolve_obj_token(app_token: str) -> str:
    """结果表可能挂在知识库（wiki）下，drive 媒体上传需真实 obj_token；普通 base 原样返回。"""
    url = (f"https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"
           f"?token={app_token}&obj_type=wiki")
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_get_token()}"})
        node = json.load(urllib.request.urlopen(req)).get("data", {}).get("node", {})
        return node.get("obj_token") or app_token
    except Exception:
        return app_token


def _upload_bitable_image(parent_obj: str, file_path: str, token: str):
    """上传图片到 bitable，返回 file_token；失败返回 None。"""
    if not file_path or not os.path.exists(file_path):
        return None
    with open(file_path, "rb") as f:
        data = f.read()
    fname = os.path.basename(file_path)
    b = "----orchestrateBoundary7MA4YWxkTrZu0gW"

    def fld(name, value):
        return (f"--{b}\r\nContent-Disposition: form-data; "
                f'name="{name}"\r\n\r\n{value}\r\n').encode()

    body = (fld("file_name", fname) + fld("parent_type", "bitable_image")
            + fld("parent_node", parent_obj) + fld("size", str(len(data)))
            + (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; "
               f"filename=\"{fname}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
            + data + b"\r\n" + f"--{b}--\r\n".encode())
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
        data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": f"multipart/form-data; boundary={b}"},
        method="POST")
    try:
        resp = json.load(urllib.request.urlopen(req))
        if resp.get("code") == 0:
            return resp["data"]["file_token"]
        log.warning(f"截图上传失败 {fname}: {resp.get('msg')}")
    except Exception as e:
        log.warning(f"截图上传异常 {fname}: {e}")
    return None


def _lowconf_review_steps(case: dict) -> list:
    """靠视觉低可信判定为通过的 ASSERT 步——隐性失败风险，需人工复核。
    取证契约见 common/locator.md「ASSERT 取证链」：id/text 取证为 high，vision 为 low。"""
    return [s for s in case.get("steps", [])
            if s.get("type") == "ASSERT"
            and s.get("verify_method") == "vision"
            and s.get("confidence") == "low"
            and s.get("pass", True)]


def write_results_to_table(app_id: str, platform: str, cases: list):
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
        failed = [s for s in c.get("steps", []) if not s.get("pass", True)]
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
        full_detail = "\n".join(x for x in (detail, review_note) if x) \
            or ("全部通过" if passed else "")

        fields = {
            "模块":     c.get("module", ""),
            "执行设备": c.get("device", ""),
            "用例名称": c.get("name", ""),
            "执行结果": "通过" if passed else "失败",
            "执行详情": full_detail,
        }
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


def _tail_file(path: str, n: int = 200) -> str:
    try:
        with open(path) as f:
            return f.read()[-n:].strip().replace("\n", " ")
    except OSError:
        return ""


def collect_results(procs: dict, result_dir: str = "/tmp",
                    timeout: int = 90 * 60,
                    app_id: str = None, version: str = None,
                    run_id: str = None) -> dict:
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
                    log.info(f"{udid} done, results read")
                    if run_id:
                        cs = results[udid] if isinstance(results[udid], list) else []
                        run_status.update_device(run_id, udid, **{
                            "state": "done", "done": len(cs), "total": len(cs),
                            "pass":  sum(1 for c in cs if c.get("passed")),
                            "fail":  sum(1 for c in cs if not c.get("passed"))})
                except json.JSONDecodeError:
                    pass  # 文件还在写，下轮再读
                continue
            # 无结果文件且进程已退出 → 它没写结果就挂了（如 429 日限额），立即判失败，不空等
            proc = procs.get(udid)
            if proc and proc.poll() is not None:
                tail = _tail_file(f"/tmp/claude_{udid}.log")
                log.warning(f"{udid} 进程已退出(code={proc.returncode})却无结果，判失败。日志末尾：{tail}")
                results[udid] = "failed"
                pending.discard(udid)
                if run_id:
                    run_status.update_device(run_id, udid, state="crashed")
                if app_id and version:  # 崩溃即时报警，不等到全部结束
                    _notify(app_id, version,
                            f"⚠️ 设备 {udid} 执行进程异常退出(code={proc.returncode})，已判失败。日志末尾：{tail}")
        if pending:
            time.sleep(10)

    for udid in pending:
        log.warning(f"{udid} timeout, killing")
        proc = procs.get(udid)
        if proc and proc.poll() is None:
            proc.kill()
        results[udid] = "timeout"
        if run_id:
            run_status.update_device(run_id, udid, state="timeout")
        if app_id and version:
            _notify(app_id, version, f"⚠️ 设备 {udid} 执行超时({timeout // 60}分钟)，已终止")

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

    # 按平台写入飞书结果表
    for platform, cases in [("android", android_cases), ("ios", ios_cases)]:
        if cases:
            write_results_to_table(app_id, platform, cases)

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
                log.info(line)

    lines = [f"📱 {app_id} {version} 自动化测试完成\n"]
    for platform, cases in [("Android", android_cases), ("iOS", ios_cases)]:
        if not cases:
            continue
        total  = len(cases)
        passed = sum(1 for c in cases if c.get("passed"))
        rate   = int(passed / total * 100) if total else 0
        url    = wiki_urls.get(platform, "")
        review = sum(1 for c in cases if c.get("passed") and _lowconf_review_steps(c))
        suffix = f"  ⚠️{review}条待复核" if review else ""
        lines.append(f"{platform}：{passed}/{total} 通过 ({rate}%){suffix}  📄 {url}")
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
    if "android" in platforms:
        log.info(f"Downloading APK: {apk_url}")
        if not download_file(apk_url, apk_path):
            _notify(app_id, version, "❌ APK 下载失败，终止")
            run_status.finish(run_id, "failed", "APK 下载失败")
            return
    if "ios" in platforms:
        ipa_dl = resolve_ios_ipa_url(ipa_url)
        log.info(f"Downloading IPA: {ipa_dl}")
        if not download_file(ipa_dl, ipa_path):
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

    # 4. Read Bitable
    run_status.set_phase(run_id, "fetching_cases", "读取用例")
    log.info("Fetching Bitable cases...")
    try:
        entries = fetch_cases(app_id)
    except Exception as e:
        _notify(app_id, version, f"❌ Bitable 读取失败：{e}")
        run_status.finish(run_id, "failed", f"Bitable 读取失败：{e}")
        return
    groups  = group_by_device(entries)
    # 仅保留本次执行平台、且安装成功（已连接）的设备组，避免等待离线设备超时
    installed = {d["udid"] for d in android_ok} | {d["udid"] for d in ios_ok}
    skipped   = {u: g for u, g in groups.items()
                 if g["platform"].lower() in platforms and u not in installed}
    for udid, g in skipped.items():
        log.warning(f"跳过 {g['platform']} 设备 {udid}（未连接/未安装），{len(g['entries'])} 条用例不执行")
    groups  = {u: g for u, g in groups.items()
               if g["platform"].lower() in platforms and u in installed}
    if not groups:
        _notify(app_id, version, f"⚠️ {app_id} {version} 无可执行用例（{'/'.join(sorted(platforms))}，已连接设备上无标记用例）")
        run_status.finish(run_id, "done", "无可执行用例")
        return

    cfg = BITABLE_CONFIGS[app_id]
    total = sum(len(g["entries"]) for g in groups.values())
    log.info(f"{total} cases across {len(groups)} devices")

    # 5. Parallel execution
    run_status.set_phase(run_id, "executing", f"{total} 条用例 × {len(groups)} 台设备执行中")
    for udid, g in groups.items():
        run_status.update_device(run_id, udid, **{
            "state": "running", "total": len(g["entries"]),
            "done": 0, "pass": 0, "fail": 0, "platform": g["platform"]})
    _notify(app_id, version, f"▶️ 开始执行：{total} 条用例 × {len(groups)} 台设备（{'/'.join(sorted(platforms))}）")
    start_time_str = datetime.datetime.now().strftime("%H:%M:%S")
    start_time = time.time()
    procs   = launch_claude_per_device(app_id, groups, wda_ports=wda_ports)
    results = collect_results(procs, app_id=app_id, version=version, run_id=run_id)
    duration = int(time.time() - start_time)
    log.info(f"Execution done, total time {duration}s")

    # 6. Generate reports
    run_status.set_phase(run_id, "reporting", "生成报告")
    generate_reports(app_id, version, results, duration, start_time_str=start_time_str)

    # 7. Cleanup temp files
    for udid in groups:
        path = f"/tmp/result_{udid}.json"
        if os.path.exists(path):
            os.remove(path)

    passed = sum(1 for d in results.values() if isinstance(d, list)
                 for c in d if c.get("passed"))
    run_status.finish(run_id, "done", "执行完成",
                      total=total, passed=passed, duration=duration)
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
    pid_file = f"/tmp/orchestrate_{app_id}_{version}{suffix}.pid"
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    try:
        _run(app_id, version, args.apk_url, args.ipa_url, platforms, run_id=run_id)
    except Exception as e:
        run_status.finish(run_id, "failed", f"未捕获异常：{e}")
        raise
    finally:
        if os.path.exists(pid_file):
            os.remove(pid_file)


if __name__ == "__main__":
    main()
