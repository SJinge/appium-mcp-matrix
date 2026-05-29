import re, json, os, subprocess, threading
from typing import Optional
from flask import Flask, request, jsonify

app = Flask(__name__)

APP_IDS = {"gaotu", "tutu", "jingpin", "gongkao", "xinli", "ketang"}

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

# 等待 Android + iOS 卡片配对
_pending_pairs: dict = {}
_pending_lock = threading.Lock()


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
        print(f"[DEBUG] Card title not matched: {title!r}")
        return None

    app_id   = title_m.group(1).lower()
    platform = title_m.group(2).lower()

    # 在整个卡片 JSON 文本里搜索版本号（紧跟"版本号"字样）
    card_text = json.dumps(card, ensure_ascii=False)
    version_m = re.search(r'版本号[^\d]{0,10}(\d+\.\d+(?:\.\d+)?)', card_text)
    if not version_m:
        version_m = re.search(r'\b(\d+\.\d+\.\d+)\b', card_text)
    if not version_m:
        print(f"[DEBUG] Version not found in card for {app_id}-{platform}")
        return None
    version = version_m.group(1)

    # 搜索 .apk 或 .ipa 下载链接
    ext = r"\.apk" if platform == "android" else r"\.ipa"
    url_m = re.search(r'https?://[^\s"\'\\]+' + ext, card_text)
    if not url_m:
        print(f"[DEBUG] Download URL (.{ext[2:]}) not found for {app_id}-{platform} {version}")
        return None

    return {"app_id": app_id, "platform": platform, "version": version, "url": url_m.group(0)}


def receive_card(content: str) -> Optional[tuple]:
    """
    暂存卡片信息；Android + iOS 都到齐后返回 (app_id, version, apk_url, ipa_url)，否则返回 None。
    """
    parsed = parse_card(content)
    if not parsed:
        return None

    app_id   = parsed["app_id"]
    version  = parsed["version"]
    platform = parsed["platform"]
    url      = parsed["url"]
    key      = f"{app_id}_{version}"

    with _pending_lock:
        if key not in _pending_pairs:
            _pending_pairs[key] = {}
        _pending_pairs[key][platform] = url
        pair = _pending_pairs[key]
        print(f"[INFO] Card received: {app_id} {version} {platform} — waiting: {set(pair.keys())}")

        if "android" in pair and "ios" in pair:
            apk_url = pair.pop("android")
            ipa_url = pair.pop("ios")
            del _pending_pairs[key]
            return app_id, version, apk_url, ipa_url

    return None


MAC_HOST         = os.environ.get("MAC_HOST", "")
MAC_USER         = os.environ.get("MAC_USER", "")
MAC_KEY          = os.environ.get("MAC_KEY", os.path.expanduser("~/.ssh/id_rsa"))
ORCHESTRATE_PATH = os.environ.get(
    "ORCHESTRATE_PATH",
    "/Users/mac/Documents/projects/appium-mcp-matrix/scripts/orchestrate.py"
)


def is_running(app_id: str, version: str) -> bool:
    pid_file = f"/tmp/orchestrate_{app_id}_{version}.pid"
    result = subprocess.run(
        ["ssh", "-i", MAC_KEY, "-o", "ConnectTimeout=5",
         f"{MAC_USER}@{MAC_HOST}",
         f"[ -f {pid_file} ] && ps -p $(cat {pid_file}) > /dev/null 2>&1 "
         f"&& echo running || echo idle"],
        capture_output=True, text=True, timeout=10
    )
    return "running" in result.stdout


def ssh_trigger(app_id: str, version: str, apk_url: str, ipa_url: str) -> bool:
    log      = f"/tmp/orchestrate_{app_id}_{version}.log"
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


def _do_trigger(app_id: str, version: str, apk_url: str, ipa_url: str):
    try:
        if is_running(app_id, version):
            print(f"[INFO] {app_id} {version} already running, skip")
            return
        ssh_trigger(app_id, version, apk_url, ipa_url)
        print(f"[INFO] Triggered {app_id} {version}")
    except Exception as e:
        print(f"[WARN] SSH error for {app_id} {version}: {e}")


@app.route("/webhook/feishu", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    if data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    event = data.get("event", {})
    msg   = event.get("message", {})
    msg_type = msg.get("message_type", "")

    # 卡片消息：Bot B 发的构建通知
    if msg_type == "interactive":
        result = receive_card(msg.get("content", "{}"))
        if result:
            _do_trigger(*result)
        return "ok"

    # 文本消息：人工备用触发
    if msg_type == "text":
        text   = json.loads(msg.get("content", "{}")).get("text", "")
        parsed = parse_message(text)
        if parsed:
            _do_trigger(parsed["app_id"], parsed["version"],
                        parsed["apk_url"], parsed["ipa_url"])

    return "ok"
