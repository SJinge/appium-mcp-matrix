import re, json, os, subprocess
from typing import Optional
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


@app.route("/webhook/feishu", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    if data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    event  = data.get("event", {})
    msg    = event.get("message", {})
    sender = event.get("sender", {})

    if msg.get("message_type") != "text":
        return "ok"
    if sender.get("sender_type") == "app":
        return "ok"

    text   = json.loads(msg.get("content", "{}")).get("text", "")
    parsed = parse_message(text)
    if not parsed:
        return "ok"

    app_id, version = parsed["app_id"], parsed["version"]

    if is_running(app_id, version):
        return "ok"

    ssh_trigger(app_id, version, parsed["apk_url"], parsed["ipa_url"])
    return "ok"
