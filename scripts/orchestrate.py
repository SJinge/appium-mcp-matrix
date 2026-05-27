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
