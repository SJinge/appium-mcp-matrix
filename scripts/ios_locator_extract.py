#!/usr/bin/env python3
"""iOS 运行时真相源抽取 —— 从 page_source 为每个元素算最优 locator。

iOS 无 resource-id(见记忆 [[project_element_truth_source]]),静态真相源不存在。
唯一可行的「真相源」是运行时探索:每到一页 appium_get_page_source → 本脚本抽出
每个可定位元素的最优 locator(name/-ios class chain/-ios predicate),按页累积到
apps/{app_id}/{version}/elements.ios.json,作为 iOS 版真相源 + 缓存来源 + 跨版本 diff。

locator 优先级(XCUITest 最佳实践):
    1. accessibility id  —— name 在整页唯一时最快(~name)
    2. -ios class chain  —— `**/XCUIElementTypeButton[`name == "登录"`]`,(type,name) 唯一时稳且快
    3. -ios predicate    —— name+type 仍不唯一时,附 index 说明歧义
    4. 无 name/label    —— 标记 needs_vision,交 AI 视觉

用法:
    appium_get_page_source 存成 page.xml,然后:
    python3 scripts/ios_locator_extract.py extract --page "上课" --xml page.xml
    python3 scripts/ios_locator_extract.py merge --app-id gaotu --version 5.91.80 \\
        --page "上课" --xml page.xml      # 抽取并累积到 elements.ios.json
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 结构性根节点,不作为定位目标
EXCLUDE_TYPES = {"XCUIElementTypeApplication", "XCUIElementTypeWindow"}

# 视为「可定位目标」的元素类型(交互控件 + 常见容器项)
INTERACTABLE = {
    "XCUIElementTypeButton", "XCUIElementTypeCell", "XCUIElementTypeTextField",
    "XCUIElementTypeSecureTextField", "XCUIElementTypeSearchField",
    "XCUIElementTypeStaticText", "XCUIElementTypeLink", "XCUIElementTypeSwitch",
    "XCUIElementTypeImage", "XCUIElementTypeTextView", "XCUIElementTypeSlider",
    "XCUIElementTypeTabBarButton", "XCUIElementTypeMenuItem",
}


# ---------- 纯函数(可单测) ----------

def parse_ios_elements(xml_text: str) -> list:
    """解析 iOS page_source,返回元素列表(type/name/label/value/visible)。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        t = el.tag
        if not t.startswith("XCUIElementType") or t in EXCLUDE_TYPES:
            continue
        name = (el.get("name") or "").strip()
        label = (el.get("label") or "").strip()
        if not (name or label):
            continue
        out.append({
            "type": t,
            "name": name,
            "label": label,
            "value": (el.get("value") or "").strip(),
            "visible": el.get("visible", "true") == "true",
        })
    return out


def _chain(t: str, attr: str, val: str) -> str:
    v = val.replace('"', '\\"')
    return f'**/{t}[`{attr} == "{v}"`]'


def best_locator(elem: dict, name_count: Counter, type_name_count: Counter) -> dict:
    """为单个元素算最优 locator。name_count/type_name_count 为整页统计。"""
    t, name, label = elem["type"], elem["name"], elem["label"]
    if name and name_count[name] == 1:
        return {"strategy": "accessibility id", "selector": name, "unique": True}
    if name and type_name_count[(t, name)] == 1:
        return {"strategy": "-ios class chain", "selector": _chain(t, "name", name), "unique": True}
    if name:
        return {"strategy": "-ios class chain", "selector": _chain(t, "name", name),
                "unique": False, "note": "name 在同类型下不唯一,定位首个;建议加 index 或上下文"}
    if label and type_name_count[(t, "L:" + label)] == 1:
        return {"strategy": "-ios class chain", "selector": _chain(t, "label", label), "unique": True}
    return {"strategy": "needs_vision", "selector": "", "unique": False,
            "note": "无唯一 name/label,交 AI 视觉"}


def extract_page(xml_text: str) -> list:
    """抽取整页元素 + 最优 locator,过滤不可见。"""
    elems = [e for e in parse_ios_elements(xml_text) if e["visible"]]
    name_count = Counter(e["name"] for e in elems if e["name"])
    tn_count = Counter()
    for e in elems:
        if e["name"]:
            tn_count[(e["type"], e["name"])] += 1
        if e["label"]:
            tn_count[(e["type"], "L:" + e["label"])] += 1
    result = []
    seen = set()
    for e in elems:
        loc = best_locator(e, name_count, tn_count)
        anchor = e["name"] or e["label"]
        key = (e["type"], anchor, loc["selector"])
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "anchor": anchor, "type": e["type"],
            "name": e["name"], "label": e["label"],
            **loc,
        })
    return result


def merge_page(truth: dict, page: str, elements: list) -> dict:
    """把一页结果并入 iOS 真相源结构(同页覆盖)。"""
    truth.setdefault("pages", {})
    truth["pages"][page] = elements
    return truth


# ---------- IO ----------

def _read_xml(path: str) -> str:
    if path:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    return sys.stdin.read()


def _truth_path(app_id: str, version: str) -> str:
    return os.path.join(PROJECT_ROOT, "apps", app_id, version, "elements.ios.json")


def cmd_extract(args):
    elements = extract_page(_read_xml(args.xml))
    print(json.dumps({"page": args.page, "count": len(elements), "elements": elements},
                     ensure_ascii=False, indent=2))


def cmd_merge(args):
    elements = extract_page(_read_xml(args.xml))
    p = _truth_path(args.app_id, args.version)
    truth = {}
    if os.path.exists(p):
        with open(p) as f:
            truth = json.load(f)
    truth.update({"app_id": args.app_id, "version": args.version,
                  "platform": "ios", "source": "runtime page_source"})
    merge_page(truth, args.page, elements)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(truth, f, ensure_ascii=False, indent=2, sort_keys=True)
    stable = sum(1 for e in elements if e["strategy"] != "needs_vision")
    print(json.dumps({"page": args.page, "merged": len(elements),
                      "stable": stable, "needs_vision": len(elements) - stable,
                      "file": os.path.relpath(p, PROJECT_ROOT)}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="iOS 运行时真相源抽取")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract")
    e.add_argument("--page", required=True)
    e.add_argument("--xml", help="page_source xml 路径,省略则读 stdin")
    e.set_defaults(func=cmd_extract)

    m = sub.add_parser("merge")
    m.add_argument("--app-id", required=True)
    m.add_argument("--version", required=True)
    m.add_argument("--page", required=True)
    m.add_argument("--xml")
    m.set_defaults(func=cmd_merge)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
