#!/usr/bin/env python3
"""定位缓存读写助手 —— 把「自然语言步骤 → selector」的解析结果沉淀下来。

执行层定位链的第 0 档:命中缓存直接 strategy=id,不走 AI 视觉、不抓 page_source。
缓存与元素真相源同目录:apps/{app_id}/{version}/locator_cache.json。
版本绑定:换版本自动 miss → 重新解析;可用 seed-from-diff 从上一版继承未变条目。

所有 I/O 走 CLI,结果只回小 JSON,避免缓存内容进 Claude 上下文。

子命令:
    get   --app-id gaotu --version 5.91.80 --step "点击登录按钮" [--page LoginActivity]
    put   --app-id gaotu --version 5.91.80 --step "点击登录按钮" [--page ...] \\
          --selector "com.gaotu100.superclass:id/account_sign_btn" --strategy id [--no-verify]
    seed-from-diff --app-id gaotu --from 5.91.70 --to 5.91.80
"""
import argparse
import json
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------- 纯函数(可单测) ----------

def normalize_step(text: str) -> str:
    """归一化步骤文本:去首尾空白、压缩内部空白、去结尾标点。中文原样保留。"""
    t = text.strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[。.!！?？、,，;；:：\s]+$", "", t)
    return t


def make_key(step: str, page: str = None) -> str:
    """缓存 key:归一化步骤文本,已知页面时加 @页面 后缀消歧。"""
    k = normalize_step(step)
    if page:
        k = f"{k}@{page}"
    return k


def selector_id(selector: str) -> str:
    """从 `pkg:id/xxx` 形式的 selector 取裸 id 名;非该形式返回空串。"""
    m = re.search(r":id/([A-Za-z0-9_.]+)$", selector or "")
    return m.group(1) if m else ""


def survives_diff(entry: dict, new_truth_ids: set) -> bool:
    """该缓存条目在新版本是否仍有效:strategy=id 时其 id 须仍在新真相源里;
    非 id 策略(xpath/ai 等)无法静态校验,保守保留。"""
    if entry.get("strategy") == "id":
        rid = selector_id(entry.get("selector", ""))
        return bool(rid) and rid in new_truth_ids
    return True


# ---------- IO ----------

def _cache_path(app_id: str, version: str) -> str:
    return os.path.join(PROJECT_ROOT, "apps", app_id, version, "locator_cache.json")


def _truth_path(app_id: str, version: str) -> str:
    versioned = os.path.join(PROJECT_ROOT, "apps", app_id, version, "elements.truth.json")
    stable = os.path.join(PROJECT_ROOT, "apps", app_id, "elements.truth.json")
    if os.path.exists(versioned):
        return versioned
    return stable


def _truth_ids(app_id: str, version: str) -> set:
    p = _truth_path(app_id, version)
    if not os.path.exists(p):
        return set()
    with open(p) as f:
        payload = json.load(f)
    active_ids = payload.get("active_ids")
    if isinstance(active_ids, list) and active_ids:
        return set(active_ids)
    entries = payload.get("entries")
    if isinstance(entries, list) and entries:
        return {entry["id"] for entry in entries if entry.get("id") and not entry.get("deprecated", False)}
    return set(payload.get("ids", []))


def load_cache(app_id: str, version: str) -> dict:
    p = _cache_path(app_id, version)
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def save_cache(app_id: str, version: str, cache: dict):
    p = _cache_path(app_id, version)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def cmd_get(args):
    cache = load_cache(args.app_id, args.version)
    key = make_key(args.step, args.page)
    entry = cache.get(key)
    if not entry:
        print("{}")
        sys.exit(1)  # miss → 调用方走下一档
    # 命中计数
    entry["hit_count"] = entry.get("hit_count", 0) + 1
    cache[key] = entry
    save_cache(args.app_id, args.version, cache)
    print(json.dumps({"selector": entry["selector"], "strategy": entry["strategy"]},
                     ensure_ascii=False))


def cmd_put(args):
    rid = selector_id(args.selector)
    if not args.no_verify and args.strategy == "id":
        truth = _truth_ids(args.app_id, args.version)
        if truth and rid not in truth:
            print(f"拒绝:{rid} 不在 {args.version} 真相源里(脏 id?)。"
                  f"确认无误用 --no-verify 跳过。", file=sys.stderr)
            sys.exit(2)
    cache = load_cache(args.app_id, args.version)
    key = make_key(args.step, args.page)
    cache[key] = {
        "selector": args.selector,
        "strategy": args.strategy,
        "module": args.module or "",
        "page": args.page or "",
        "verified_version": args.version,
        "hit_count": cache.get(key, {}).get("hit_count", 0),
    }
    save_cache(args.app_id, args.version, cache)
    print(json.dumps({"key": key, "saved": True}, ensure_ascii=False))


def cmd_seed_from_diff(args):
    """从上一版缓存继承仍有效的条目,只丢弃 id 已失效的(发版增量)。"""
    old = load_cache(args.app_id, getattr(args, "from"))
    if not old:
        print(json.dumps({"seeded": 0, "dropped": 0, "note": "上一版无缓存"}, ensure_ascii=False))
        return
    new_ids = _truth_ids(args.app_id, args.to)
    new_cache = load_cache(args.app_id, args.to)
    seeded = dropped = 0
    for key, entry in old.items():
        if key in new_cache:
            continue
        if survives_diff(entry, new_ids):
            e = dict(entry)
            e["verified_version"] = getattr(args, "from")  # 标记继承自旧版,待执行时复验
            e["hit_count"] = 0
            new_cache[key] = e
            seeded += 1
        else:
            dropped += 1
    save_cache(args.app_id, args.to, new_cache)
    print(json.dumps({"seeded": seeded, "dropped": dropped, "from": getattr(args, "from"),
                      "to": args.to}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="定位缓存读写")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get")
    g.add_argument("--app-id", required=True)
    g.add_argument("--version", required=True)
    g.add_argument("--step", required=True)
    g.add_argument("--page")
    g.set_defaults(func=cmd_get)

    p = sub.add_parser("put")
    p.add_argument("--app-id", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--step", required=True)
    p.add_argument("--page")
    p.add_argument("--selector", required=True)
    p.add_argument("--strategy", default="id")
    p.add_argument("--module")
    p.add_argument("--no-verify", action="store_true")
    p.set_defaults(func=cmd_put)

    s = sub.add_parser("seed-from-diff")
    s.add_argument("--app-id", required=True)
    s.add_argument("--from", required=True)
    s.add_argument("--to", required=True)
    s.set_defaults(func=cmd_seed_from_diff)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
