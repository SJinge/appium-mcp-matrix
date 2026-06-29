#!/usr/bin/env python3
"""扫描 Android 源码,为元素真相源补「页面归属」层。

APK 扫描(scan_apk_ids.py)给出 id 全集但无页面归属;本脚本从源码抽:
    1. res/layout/*.xml      → 每个 id 在哪个 layout 声明      (id → layouts)
    2. *Activity/*Fragment   → 每个页面引用了哪些 R.layout.*    (layout → pages)
然后与 APK 真相源 join,产出带「模块 / 布局 / 页面」归属的富真相源。

诚实边界(源码扫无法解决的):
    - AB 实验布局 setContentView(abTestWorkflow.xmlSelector(...)) 非字面 R.layout.x,链不上
    - include 复用布局 → 一个 id 归属多页面(一对多)
    - Compose / WebView 页面无 resource-id,源码里也抽不到

用法:
    # 先准备好对应 release 分支的本地 checkout(可 sparse 只取某模块)
    python3 scripts/scan_source_ids.py \\
        --source-dir /tmp/asc_recon \\
        --apk-truth apps/gaotu/5.91.80/elements.truth.json \\
        --module account
"""
import argparse
import json
import os
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ID_DECL_RE = re.compile(r'android:id="@\+?id/([A-Za-z0-9_]+)"')
LAYOUT_REF_RE = re.compile(r'R\.layout\.([A-Za-z0-9_]+)')
# ViewBinding: FragmentPasswordLoginBinding → fragment_password_login
BINDING_RE = re.compile(r'\b([A-Z][A-Za-z0-9]+)Binding\b')


# ---------- 纯函数(可单测) ----------

def module_from_path(path: str) -> str:
    """从文件路径推断业务模块名。

    service/business/account/...  → account
    accessories/ketang/...        → ketang
    basic/library_ui/...          → library_ui
    其余取 src 之前的最后一段。
    """
    parts = path.replace("\\", "/").split("/")
    if "business" in parts:
        i = parts.index("business")
        if i + 1 < len(parts):
            return parts[i + 1]
    for anchor in ("accessories", "service", "basic", "business"):
        if anchor in parts:
            i = parts.index(anchor)
            if i + 1 < len(parts):
                return parts[i + 1]
    if "src" in parts:
        i = parts.index("src")
        if i >= 1:
            return parts[i - 1]
    return parts[0] if parts else "unknown"


def parse_layout_ids(xml_text: str) -> list:
    """从一个 layout xml 文本抽出声明的 id 列表(去重排序)。"""
    return sorted(set(ID_DECL_RE.findall(xml_text)))


def parse_layout_refs(source_text: str) -> set:
    """从页面源码抽出引用的 layout 名:R.layout.x + ViewBinding 推断。"""
    refs = set(LAYOUT_REF_RE.findall(source_text))
    for cls in BINDING_RE.findall(source_text):
        refs.add(camel_to_snake(cls))
    return refs


def camel_to_snake(name: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    return s.lower()


def page_name_from_path(path: str) -> str:
    """从源文件路径取页面类名(去扩展名)。"""
    base = os.path.basename(path)
    return re.sub(r"\.(kt|java)$", "", base)


def build_attribution(layout_to_ids: dict, layout_to_pages: dict,
                      id_to_module: dict) -> dict:
    """构建 id → {module, layouts, pages} 归属表。"""
    id_to_layouts = {}
    for layout, ids in layout_to_ids.items():
        for i in ids:
            id_to_layouts.setdefault(i, set()).add(layout)
    attribution = {}
    for i, layouts in id_to_layouts.items():
        pages = set()
        for lay in layouts:
            pages |= layout_to_pages.get(lay, set())
        attribution[i] = {
            "module": id_to_module.get(i, ""),
            "layouts": sorted(layouts),
            "pages": sorted(pages),
        }
    return attribution


def join_with_apk(apk_ids: list, attribution: dict, pkg: str) -> dict:
    """以 APK id 全集为准,join 源码归属。返回富条目 + 覆盖统计。"""
    enriched = []
    attributed = 0
    page_linked = 0
    for i in sorted(apk_ids):
        attr = attribution.get(i)
        entry = {
            "id": i,
            "selector": f"{pkg}:id/{i}",
            "module": attr["module"] if attr else "",
            "layouts": attr["layouts"] if attr else [],
            "pages": attr["pages"] if attr else [],
        }
        if attr:
            attributed += 1
            if attr["pages"]:
                page_linked += 1
        enriched.append(entry)
    return {
        "enriched": enriched,
        "stats": {
            "apk_total": len(apk_ids),
            "source_attributed": attributed,     # 在源码 layout 里找到声明
            "page_linked": page_linked,          # 进一步链到了具体页面
        },
    }


# ---------- IO ----------

def scan_source(source_dir: str, module: str = None):
    """遍历源码目录,返回 (layout_to_ids, layout_to_pages, id_to_module)。"""
    layout_to_ids = {}
    layout_to_pages = {}
    id_to_module = {}

    def in_scope(path: str) -> bool:
        return module is None or f"/{module}/" in path.replace("\\", "/") + "/"

    for root, _, files in os.walk(source_dir):
        if "/.git" in root:
            continue
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, source_dir)
            # layout xml
            if fn.endswith(".xml") and os.sep + "layout" in root and "res" in root:
                if not in_scope(rel):
                    continue
                try:
                    text = open(full, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                layout = re.sub(r"\.xml$", "", fn)
                ids = parse_layout_ids(text)
                if ids:
                    layout_to_ids[layout] = sorted(set(layout_to_ids.get(layout, [])) | set(ids))
                    mod = module_from_path(rel)
                    for i in ids:
                        id_to_module.setdefault(i, mod)
            # page source
            elif re.search(r"(Activity|Fragment)\.(kt|java)$", fn):
                if not in_scope(rel):
                    continue
                try:
                    text = open(full, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                refs = parse_layout_refs(text)
                page = page_name_from_path(fn)
                for lay in refs:
                    layout_to_pages.setdefault(lay, set()).add(page)
    return layout_to_ids, layout_to_pages, id_to_module


def main():
    ap = argparse.ArgumentParser(description="扫描源码补元素真相源的页面归属层")
    ap.add_argument("--source-dir", required=True, help="本地源码 checkout 目录")
    ap.add_argument("--apk-truth", required=True, help="APK 真相源 elements.truth.json 路径")
    ap.add_argument("--module", help="只扫某模块(如 account),不传则全量")
    ap.add_argument("--out", help="输出路径,默认与 apk-truth 同目录 elements.enriched.json")
    args = ap.parse_args()

    with open(args.apk_truth) as f:
        truth = json.load(f)
    pkg = truth["package"]
    apk_ids = truth["ids"]
    if args.module:
        # 样例验证:只 join 该模块 layout 涉及的 id,避免被全量稀释
        pass

    print(f"[1/3] 遍历源码 {args.source_dir}" + (f"(模块 {args.module})" if args.module else ""))
    layout_to_ids, layout_to_pages, id_to_module = scan_source(args.source_dir, args.module)
    print(f"      layout {len(layout_to_ids)} 个 / 页面引用 layout {len(layout_to_pages)} 个")

    print("[2/3] 构建归属并与 APK 真相源 join")
    attribution = build_attribution(layout_to_ids, layout_to_pages, id_to_module)
    result = join_with_apk(apk_ids, attribution, pkg)
    st = result["stats"]

    out = args.out or os.path.join(os.path.dirname(args.apk_truth), "elements.enriched.json")
    payload = {
        "app_id": truth["app_id"],
        "version": truth["version"],
        "package": pkg,
        "source": "aapt2(id 全集) ⨝ android-source(页面归属)",
        "module_filter": args.module or "all",
        "stats": st,
        # 只落有归属的条目,避免文件被无归属 id 撑爆;无归属的可由 apk-truth 兜底
        "elements": [e for e in result["enriched"] if e["module"] or e["pages"]],
    }
    with open(out, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[3/3] 写出 {os.path.relpath(out, PROJECT_ROOT)}")
    cov = (st["source_attributed"] / st["apk_total"] * 100) if st["apk_total"] else 0
    print(f"      APK id {st['apk_total']} / 源码归属 {st['source_attributed']} ({cov:.1f}%) / 链到页面 {st['page_linked']}")
    if args.module:
        sample = [e for e in payload["elements"] if e["pages"]][:5]
        print("      样例(带页面归属):")
        for e in sample:
            print(f"        {e['id']:32s} → {e['module']} / {','.join(e['pages'])}")


if __name__ == "__main__":
    main()
