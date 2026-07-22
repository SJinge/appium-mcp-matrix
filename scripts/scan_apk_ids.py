#!/usr/bin/env python3
"""静态扫描 APK，抽取 resource-id 全集，生成元素真相源。

SDD `/case-scan` 的 Android 等价物：不跑 app，直接从 APK 静态抽 resource-id，
秒级、确定、可 diff。与运行时探索地图（apps/{app_id}/index.md）互补：
本脚本产出「元素 ID 全集」，探索地图产出「页面归属 + 导航路径」。

流程：adb pull base.apk → aapt2 dump resources → 解析 id/ 类型
     → apps/{app_id}/elements.truth.json
     → 更新 elements.diff.json，输出新增/废弃清单。

用法：
    python3 scripts/scan_apk_ids.py --app-id gaotu --udid cd5c614a
    python3 scripts/scan_apk_ids.py --app-id gaotu --apk /tmp/gaotu.apk --version 5.91.80
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PKG_NAMES = {
    "gaotu":   "com.gaotu100.superclass",
    "tutu":    "com.gaotu100.tutu",
    "jingpin": "com.gaotu100.jingpin",
    "gongkao": "com.gaotu100.gongkao",
    "xinli":   "com.gaotu100.xinli",
    "ketang":  "com.gaotu100.ketang",
}

# 第三方库 / 系统资源的 id 前缀，用于估算业务相关占比（不剔除，仅打标统计）
NOISE_RE = re.compile(
    r"^(abc_|m3_|mtrl_|design_|material|androidx|tt_|csj_|ksad_|gdt_|"
    r"sobot|umeng|jpush|umcsdk|wx[a-z0-9]|alivc|aliyun|ali_|glide|exo_|"
    r"svga|lottie|webrtc|agora|zego|bytedance|pag_|napi)"
)

# aapt2 dump 行格式：  resource 0x7f0a0001 id/account_sign_btn
ID_LINE_RE = re.compile(r"resource 0x[0-9a-f]+ id/([A-Za-z0-9_.]+)")


# ---------- 纯函数（可单测） ----------

def parse_ids_from_dump(dump_text: str) -> list:
    """从 aapt2 dump resources 输出中抽取去重、排序后的 id 名（不含 id/ 前缀）。"""
    ids = set()
    for line in dump_text.splitlines():
        m = ID_LINE_RE.search(line)
        if m:
            ids.add(m.group(1))
    return sorted(ids)


def is_noise(id_name: str) -> bool:
    """判断 id 是否来自第三方库 / 系统（非业务）。"""
    return bool(NOISE_RE.match(id_name))


def version_key(v: str):
    """把版本号转成可比较的元组，非数字段按 0 处理。"""
    parts = re.split(r"[.\-_]", v)
    key = []
    for p in parts:
        key.append((0, int(p)) if p.isdigit() else (1, 0))
    return tuple(key)


def pick_previous_version(versions: list, current: str):
    """在已有版本目录中挑出严格小于 current 的最高版本，没有则返回 None。"""
    lower = [v for v in versions if v != current and version_key(v) < version_key(current)]
    if not lower:
        return None
    return max(lower, key=version_key)


def diff_ids(old_ids: list, new_ids: list) -> dict:
    """对比两份 id 全集，返回新增 / 删除清单。"""
    old, new = set(old_ids), set(new_ids)
    return {
        "added":   sorted(new - old),
        "removed": sorted(old - new),
    }


def merge_truth_entries(previous_entries: list, current_ids: list) -> list:
    """合并旧真相源与本次扫描结果。"""
    current = set(current_ids)
    prev_map = {}
    for entry in previous_entries or []:
        rid = entry.get("id")
        if rid:
            prev_map[rid] = {"id": rid, "deprecated": bool(entry.get("deprecated", False))}
    merged_ids = sorted(set(prev_map) | current)
    return [{"id": rid, "deprecated": rid not in current} for rid in merged_ids]


def load_existing_truth(truth_path: str) -> dict:
    if not os.path.exists(truth_path):
        return {}
    with open(truth_path) as f:
        return json.load(f)


def truth_entries_from_payload(payload: dict) -> list:
    entries = payload.get("entries")
    if isinstance(entries, list) and entries:
        normalized = []
        for entry in entries:
            rid = entry.get("id")
            if rid:
                normalized.append({"id": rid, "deprecated": bool(entry.get("deprecated", False))})
        if normalized:
            return sorted(normalized, key=lambda item: item["id"])
    ids = payload.get("ids", [])
    return [{"id": rid, "deprecated": False} for rid in sorted(set(ids))]


def build_truth_payload(app_id: str, pkg: str, version: str, ids: list,
                        previous: dict = None) -> dict:
    ids = sorted(set(ids))
    previous = previous or {}
    entries = merge_truth_entries(truth_entries_from_payload(previous), ids)
    active_ids = [entry["id"] for entry in entries if not entry["deprecated"]]
    deprecated_ids = [entry["id"] for entry in entries if entry["deprecated"]]
    noise = [i for i in active_ids if is_noise(i)]
    business = len(active_ids) - len(noise)
    return {
        "app_id": app_id,
        "package": pkg,
        "version": version,
        "platform": "android",
        "source": "aapt2 dump resources",
        "selector_template": f"{pkg}:id/{{id}}",
        "total": len(entries),
        "active_count": len(active_ids),
        "deprecated_count": len(deprecated_ids),
        "business_count": business,
        "noise_count": len(noise),
        "ids": active_ids,
        "active_ids": active_ids,
        "deprecated_ids": deprecated_ids,
        "entries": entries,
    }


# ---------- 副作用（设备 / 文件 / 外部工具） ----------

def find_aapt2() -> str:
    """定位 aapt2：$AAPT2 → PATH → SDK build-tools 取最高版本。"""
    if os.environ.get("AAPT2") and os.path.exists(os.environ["AAPT2"]):
        return os.environ["AAPT2"]
    found = shutil.which("aapt2")
    if found:
        return found
    roots = [
        os.environ.get("ANDROID_HOME", ""),
        os.environ.get("ANDROID_SDK_ROOT", ""),
        os.path.expanduser("~/Library/Android/sdk"),
        os.path.expanduser("~/Android/Sdk"),
        "/usr/local/share/android-commandlinetools",
    ]
    candidates = []
    for root in roots:
        if root:
            candidates += glob.glob(os.path.join(root, "build-tools", "*", "aapt2"))
    if not candidates:
        raise FileNotFoundError(
            "未找到 aapt2，请设置 AAPT2 环境变量或安装 Android SDK build-tools")
    # 目录名即 build-tools 版本，取最高
    return max(candidates, key=lambda p: version_key(os.path.basename(os.path.dirname(p))))


def extract_version_android(pkg: str, udid: str = None) -> str:
    cmd = ["adb"] + (["-s", udid] if udid else []) + ["shell", "dumpsys", "package", pkg]
    r = subprocess.run(cmd, capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if "versionName=" in line:
            return line.strip().split("=", 1)[1].strip()
    return "unknown"


def pull_apk(pkg: str, udid: str, dest: str) -> str:
    """取设备上该包的 base.apk 并拉到 dest，返回本地路径。"""
    cmd = ["adb"] + (["-s", udid] if udid else []) + ["shell", "pm", "path", pkg]
    r = subprocess.run(cmd, capture_output=True, text=True)
    remote = None
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("package:") and line.endswith("base.apk"):
            remote = line[len("package:"):]
            break
    if not remote:
        raise RuntimeError(f"设备上未找到 {pkg} 的 base.apk（应用是否已安装？）")
    pull = ["adb"] + (["-s", udid] if udid else []) + ["pull", remote, dest]
    r = subprocess.run(pull, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dest):
        raise RuntimeError(f"adb pull 失败：{r.stderr.strip()}")
    return dest


def dump_resources(aapt2: str, apk_path: str) -> str:
    r = subprocess.run([aapt2, "dump", "resources", apk_path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"aapt2 dump 失败：{r.stderr.strip()[:300]}")
    return r.stdout


def scan(app_id: str, udid: str = None, apk: str = None, version: str = None) -> dict:
    """完整扫描流程，写出 elements.truth.json 与 elements.diff.json，返回结果摘要。"""
    if app_id not in PKG_NAMES:
        raise ValueError(f"未知 app_id：{app_id}，可选 {list(PKG_NAMES)}")
    pkg = PKG_NAMES[app_id]
    aapt2 = find_aapt2()

    if apk:
        apk_path = apk
        if not version:
            version = extract_version_android(pkg, udid)
    else:
        if not version:
            version = extract_version_android(pkg, udid)
        tmp = f"/tmp/apkscan_{app_id}.apk"
        print(f"[1/4] 从设备拉取 {pkg} base.apk → {tmp}")
        apk_path = pull_apk(pkg, udid, tmp)

    print(f"[2/4] aapt2 dump resources（{os.path.basename(aapt2)} 所在 build-tools）")
    dump = dump_resources(aapt2, apk_path)

    print("[3/4] 解析 id 类型资源")
    ids = parse_ids_from_dump(dump)
    out_dir = os.path.join(PROJECT_ROOT, "apps", app_id)
    os.makedirs(out_dir, exist_ok=True)
    truth_path = os.path.join(out_dir, "elements.truth.json")
    previous = load_existing_truth(truth_path)
    truth = build_truth_payload(app_id, pkg, version, ids, previous=previous)
    with open(truth_path, "w") as f:
        json.dump(truth, f, ensure_ascii=False, indent=2)

    prev_ids = previous.get("active_ids") or previous.get("ids", [])
    d = diff_ids(prev_ids, truth["active_ids"])
    diff = {
        "from_version": previous.get("version", ""),
        "to_version": version,
        "added": d["added"],
        "deprecated": d["removed"],
        "added_count": len(d["added"]),
        "deprecated_count": len(d["removed"]),
    }
    with open(os.path.join(out_dir, "elements.diff.json"), "w") as f:
        json.dump(diff, f, ensure_ascii=False, indent=2)

    print(f"[4/4] 写出 {os.path.relpath(truth_path, PROJECT_ROOT)}")
    print(f"      当前有效 {truth['active_count']} / 累积总计 {truth['total']} 个 resource-id")
    print(f"      业务 ~{truth['business_count']} / 噪声 {truth['noise_count']} / 废弃 {truth['deprecated_count']}")
    if previous:
        print(f"      vs {previous.get('version', 'unknown')}：新增 {diff['added_count']} / 废弃 {diff['deprecated_count']}")
    else:
        print("      无历史真相源，已创建首份稳定文件")
    return {"truth": truth, "diff": diff}


def main():
    ap = argparse.ArgumentParser(description="静态扫描 APK 生成元素真相源")
    ap.add_argument("--app-id", required=True, choices=list(PKG_NAMES),
                    help="App 标识")
    ap.add_argument("--udid", help="设备 udid（不传则用默认 adb 设备）")
    ap.add_argument("--apk", help="本地 APK 路径，传则跳过从设备 pull")
    ap.add_argument("--version", help="版本号，不传则从设备读取")
    args = ap.parse_args()
    if not args.apk and not args.udid:
        # 无 udid 时仍可工作（单设备），但给出提示
        print("提示：未指定 --udid，使用默认 adb 设备", file=sys.stderr)
    try:
        scan(args.app_id, udid=args.udid, apk=args.apk, version=args.version)
    except Exception as e:
        print(f"扫描失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
