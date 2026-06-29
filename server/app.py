import re, json, os, sys, subprocess
from typing import Optional
from flask import Flask, request, jsonify

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import run_status
import logging_setup

log = logging_setup.get_logger("webhook", logfile="webhook.log")

app = Flask(__name__)

APP_IDS = {"gaotu", "tutu", "jingpin", "gongkao", "xinli", "ketang"}

# 仅这些 App 触发自动化执行（逗号分隔，默认只跑 gaotu）。其余 App 的构建消息照常解析但不触发。
ENABLED_APPS = {a.strip() for a in os.environ.get("ENABLED_APPS", "gaotu").split(",") if a.strip()}

# 文本消息触发格式（人工发送备用）
_MSG_RE = re.compile(
    r'(?P<app>' + '|'.join(APP_IDS) + r')\s+'
    r'(?P<version>\d+\.\d+(?:\.\d+)?)\s+'
    r'android:(?P<apk_url>https?://\S+)\s+'
    r'ios:(?P<ipa_url>https?://\S+)',
    re.IGNORECASE
)

# 卡片标题格式：【gaotu-android】构建完成！
_CARD_TITLE_RE = re.compile(
    r'【(' + '|'.join(APP_IDS) + r')-(android|ios)】',
    re.IGNORECASE
)

# Android / iOS 各自到达即独立触发，不再配对等待


def parse_message(text: str) -> Optional[dict]:
    m = _MSG_RE.search(text)
    if not m:
        return None
    return {
        "app_id":  m.group("app").lower(),
        "version": m.group("version"),
        "apk_url": m.group("apk_url"),
        "ipa_url": m.group("ipa_url"),
    }


def parse_card(content: str) -> Optional[dict]:
    """
    从飞书卡片消息中提取 app_id、platform、version、url。
    卡片标题格式：【gaotu-android】构建完成！
    版本号从卡片文本中用正则匹配，下载 URL 从卡片 JSON 中匹配 .apk/.ipa。
    """
    try:
        card = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None

    # 从 header.title 提取标题文本（兼容 v1/v2 卡片格式）
    title = ""
    header = card.get("header", {})
    title_obj = header.get("title", {})
    if isinstance(title_obj, dict):
        title = title_obj.get("content", "") or title_obj.get("text", "")
    elif isinstance(title_obj, str):
        title = title_obj

    title_m = _CARD_TITLE_RE.search(title)
    if not title_m:
        log.debug(f"Card title not matched: {title!r}")
        return None

    app_id   = title_m.group(1).lower()
    platform = title_m.group(2).lower()

    # 在整个卡片 JSON 文本里搜索版本号（紧跟"版本号"字样）
    card_text = json.dumps(card, ensure_ascii=False)
    version_m = re.search(r'版本号[^\d]{0,10}(\d+\.\d+(?:\.\d+)?)', card_text)
    if not version_m:
        version_m = re.search(r'\b(\d+\.\d+\.\d+)\b', card_text)
    if not version_m:
        log.debug(f"Version not found in card for {app_id}-{platform}")
        return None
    version = version_m.group(1)

    # 搜索 .apk 或 .ipa 下载链接
    ext = r"\.apk" if platform == "android" else r"\.ipa"
    url_m = re.search(r'https?://[^\s"\'\\]+' + ext, card_text)
    if not url_m:
        log.debug(f"Download URL (.{ext[2:]}) not found for {app_id}-{platform} {version}")
        return None

    return {"app_id": app_id, "platform": platform, "version": version, "url": url_m.group(0)}


def parse_template(data: dict) -> Optional[dict]:
    """
    解析轻舟打包系统的 template 格式 webhook。
    payload: {"type": "template", "data": {"template_variable": {...}}}
    template_variable 关键字段：appProduct(如 gaotu-android)、appVersion、downloadUrl。
    """
    tv = (data.get("data") or {}).get("template_variable") or {}
    product = (tv.get("appProduct") or "").lower()
    version = tv.get("appVersion") or ""
    url     = tv.get("downloadUrl") or ""

    if "-" not in product:
        log.debug(f"template appProduct unexpected: {product!r}")
        return None
    app_id, platform = product.split("-", 1)

    if app_id not in APP_IDS or platform not in ("android", "ios") or not version or not url:
        log.debug(f"template fields invalid: app_id={app_id!r} platform={platform!r} "
              f"version={version!r} url={url!r}")
        return None

    return {"app_id": app_id, "platform": platform, "version": version, "url": url}


def receive_card(content: str) -> Optional[dict]:
    """飞书卡片格式（人工备用）。返回单端 {app_id, platform, version, url}。"""
    return parse_card(content)


def receive_template(data: dict) -> Optional[dict]:
    """轻舟 template 格式（构建系统主路径）。返回单端 {app_id, platform, version, url}。"""
    return parse_template(data)


ORCHESTRATE_PATH = os.environ.get(
    "ORCHESTRATE_PATH",
    "/Users/mac/Documents/projects/appium-mcp-matrix/scripts/orchestrate.py"
)

# 已触发标记目录（每个 app+version+platform 只执行一次；删除对应 .triggered 文件可重跑）
MARKER_DIR = os.environ.get("ORCH_MARKER_DIR", "/tmp")


def _triggered_marker(app_id: str, version: str, platform: str) -> str:
    return os.path.join(MARKER_DIR, f"orchestrate_{app_id}_{version}_{platform}.triggered")


def local_trigger(app_id: str, version: str, platform: str, url: str) -> bool:
    """本机后台启动 orchestrate（单端）。orchestrate 自身负责写/删 pid 文件。"""
    log_path = f"/tmp/orchestrate_{app_id}_{version}_{platform}.log"
    url_flag = "--apk-url" if platform == "android" else "--ipa-url"
    cmd = ["python3", ORCHESTRATE_PATH,
           "--app", app_id, "--version", version,
           "--platform", platform, url_flag, url]
    with open(log_path, "w") as f:
        subprocess.Popen(cmd, stdout=f, stderr=f, start_new_session=True)
    return True


def _do_trigger(app_id: str, version: str, platform: str, url: str):
    if app_id not in ENABLED_APPS:
        log.info(f"{app_id} 不在执行白名单({','.join(sorted(ENABLED_APPS))})，跳过 {version} {platform}")
        return

    # 同一 app+version+platform 只执行一次：原子创建标记，已存在则说明触发过
    marker = _triggered_marker(app_id, version, platform)
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        log.info(f"{app_id} {version} {platform} 已触发过，跳过（删除 {marker} 可重跑）")
        return

    try:
        if local_trigger(app_id, version, platform, url):
            log.info(f"Triggered {app_id} {version} {platform}")
        else:
            os.remove(marker)  # 启动失败，撤销标记以便重试
            log.warning(f"Trigger failed for {app_id} {version} {platform}")
    except Exception as e:
        try:
            os.remove(marker)
        except OSError:
            pass
        log.warning(f"Trigger error for {app_id} {version} {platform}: {e}")


@app.route("/health", methods=["GET"])
def health():
    """存活探针：launchd KeepAlive 负责重启进程，外部/监控用此确认 webhook 在听。
    顺带回 enabled_apps 和当前在跑的 run 数(phase 非终态)。"""
    active = [r for r in run_status.load_all()
              if r.get("phase") not in ("done", "failed")]
    return jsonify({
        "status":       "ok",
        "enabled_apps": sorted(ENABLED_APPS),
        "active_runs":  len(active),
    })


@app.route("/status", methods=["GET"])
def status():
    """查所有在跑/最近 run 的阶段与进度，免 ssh grep /tmp。
    可选 ?run_id=gaotu_5.91.80_android 查单个。"""
    rid = request.args.get("run_id")
    if rid:
        return jsonify(run_status.load(rid))
    return jsonify({"runs": run_status.load_all()})


@app.route("/webhook", methods=["POST"])
@app.route("/webhook/feishu", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    if data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    # 轻舟打包系统：template 格式（构建系统主路径），单端到达即触发
    if data.get("type") == "template":
        p = receive_template(data)
        if p:
            _do_trigger(p["app_id"], p["version"], p["platform"], p["url"])
        return "ok"

    event = data.get("event", {})
    msg   = event.get("message", {})
    msg_type = msg.get("message_type", "")

    content_preview = (msg.get("content", "") or "")[:300]
    log.debug(f"Webhook received: event_type={data.get('header', {}).get('event_type') or data.get('type')!r} "
          f"msg_type={msg_type!r} content={content_preview!r}")

    # 卡片消息：Bot B 发的构建通知，单端到达即触发
    if msg_type == "interactive":
        p = receive_card(msg.get("content", "{}"))
        if p:
            _do_trigger(p["app_id"], p["version"], p["platform"], p["url"])
        return "ok"

    # 文本消息：人工备用触发（一条含双端 url，分别独立触发）
    if msg_type == "text":
        text   = json.loads(msg.get("content", "{}")).get("text", "")
        parsed = parse_message(text)
        if parsed:
            _do_trigger(parsed["app_id"], parsed["version"], "android", parsed["apk_url"])
            _do_trigger(parsed["app_id"], parsed["version"], "ios",     parsed["ipa_url"])
        else:
            log.debug(f"Text message did not match trigger format: {text!r}")
        return "ok"

    log.debug(f"Unhandled msg_type={msg_type!r}, ignored")
    return "ok"


if __name__ == "__main__":
    # launchd / 手动启动统一入口（端口 5001，见 deploy/launchd/）
    port = int(os.environ.get("PORT", "5001"))
    log.info(f"webhook server starting on :{port} (enabled_apps={sorted(ENABLED_APPS)})")
    app.run(host="0.0.0.0", port=port)
