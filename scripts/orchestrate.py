#!/usr/bin/env python3
import argparse, json, os, subprocess, sys, time
import urllib.request, urllib.error, datetime
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


def download_file(url: str, dest: str) -> bool:
    r = subprocess.run(["curl", "-L", "-o", dest, url], capture_output=True)
    return r.returncode == 0 and os.path.getsize(dest) > 1_000_000


def _notify(app_id: str, version: str, message: str):
    pass  # implemented in Task 10


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
        "android_device": _text_field(fields.get("Android设备", "")),
        "ios_device":     _text_field(fields.get("ios设备", "")),
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


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--app",     required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--apk-url", required=True, dest="apk_url")
    p.add_argument("--ipa-url", required=True, dest="ipa_url")
    return p.parse_args()


def _run(app_id, version, apk_url, ipa_url):
    devices = load_devices(app_id)

    # 1. Download
    apk_path = f"/tmp/{app_id}_{version}.apk"
    ipa_path = f"/tmp/{app_id}_{version}.ipa"
    print(f"[INFO] Downloading APK: {apk_url}")
    if not download_file(apk_url, apk_path):
        _notify(app_id, version, "❌ APK 下载失败，终止")
        return
    print(f"[INFO] Downloading IPA: {ipa_url}")
    if not download_file(ipa_url, ipa_path):
        _notify(app_id, version, "❌ IPA 下载失败，终止")
        return

    # 2. Install
    android_ok, ios_ok = [], []
    for d in devices["android"]:
        if install_android(apk_path, d["udid"]):
            android_ok.append(d)
            print(f"[INFO] Android {d['udid']} installed")
        else:
            print(f"[WARN] Android {d['udid']} install failed, skipping")

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


if __name__ == "__main__":
    main()
