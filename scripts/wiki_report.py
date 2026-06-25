#!/usr/bin/env python3
"""
创建矩阵 App 自动化测试 Wiki 报告并发送群通知。

Usage:
  python3 wiki_report.py \
    --app gaotu --version 5.91.51 \
    --platform Android --device 26KUT24202013751 \
    --account 12100000000 --time "14:30:22" --duration "709s" \
    --total 3 --passed 2 --failed 1 --rate 67 \
    --cases '[{"name":"用例名","module":"模块","passed":true,"duration":120,"steps":[...]}]'
"""
import json, urllib.request, urllib.error, datetime, argparse
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from feishu_config import APP_ID, APP_SECRET, SPACE_ID, PARENT_NODE, GROUP_CHAT_ID

APP_NAMES = {
    "gaotu":   "高途",
    "tutu":    "途途课堂",
    "jingpin": "高途高中",
    "gongkao": "高途公职",
    "xinli":   "高途心理",
    "ketang":  "高途素养",
}
PLATFORM_CN = {"android": "安卓", "ios": "iOS"}

# ─── 参数 ────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--app",       default="gaotu")
    p.add_argument("--version",   required=True)
    p.add_argument("--platform",  required=True)
    p.add_argument("--device",    default="")
    p.add_argument("--account",   default="多账号")
    p.add_argument("--time",      required=True)
    p.add_argument("--duration",  required=True)
    p.add_argument("--total",     required=True)
    p.add_argument("--passed",    required=True)
    p.add_argument("--failed",    required=True)
    p.add_argument("--rate",      required=True)
    p.add_argument("--cases",     help="JSON 格式用例列表")
    p.add_argument("--results",   help="纯文本明细（旧版兼容）")
    p.add_argument("--no-notify", action="store_true", help="跳过群消息（调试用）")
    return p.parse_args()

# ─── Feishu HTTP ─────────────────────────────────────────────────────────────

def get_token():
    data = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    return json.load(urllib.request.urlopen(req)).get("tenant_access_token", "")

TOKEN = get_token()

def feishu(method, url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    hdrs = {"Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json; charset=utf-8"}
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"[WARN] HTTP {e.code}: {e.read().decode()[:200]}")
        return None

# ─── 基础 block 工具 ──────────────────────────────────────────────────────────

def text_elem(content, bold=False):
    return {"text_run": {"content": content, "text_element_style": {
        "bold": bold, "inline_code": False, "italic": False,
        "strikethrough": False, "underline": False
    }}}

def text_block(content, bold=False):
    return {"block_type": 2, "text": {
        "elements": [text_elem(content, bold)],
        "style": {"align": 1, "folded": False}
    }}

def heading_block(level, content):
    key = f"heading{level}"
    return {"block_type": level + 2, key: {
        "elements": [text_elem(content)],
        "style": {"align": 1, "folded": False}
    }}

def divider_block():
    return {"block_type": 22, "divider": {}}

def add_block(doc_token, block, counter):
    """向文档追加一个 block，失败时不推进 counter。"""
    n = counter[0]
    url = (f"https://open.feishu.cn/open-apis/docx/v1/documents"
           f"/{doc_token}/blocks/{doc_token}/children")
    resp = feishu("POST", url, {"children": [block], "index": n})
    if resp is not None and resp.get("code") == 0:
        counter[0] += 1

# ─── 表格工具 ─────────────────────────────────────────────────────────────────

def _get_children_ids(doc_token, block_id):
    url = (f"https://open.feishu.cn/open-apis/docx/v1/documents"
           f"/{doc_token}/blocks/{block_id}/children?page_size=500")
    resp = feishu("GET", url)
    if resp and resp.get("code") == 0:
        return [item["block_id"] for item in resp["data"].get("items", [])]
    return []

def _add_text_to_cell(doc_token, cell_id, content, bold=False):
    if not content:
        return
    url = (f"https://open.feishu.cn/open-apis/docx/v1/documents"
           f"/{doc_token}/blocks/{cell_id}/children")
    feishu("POST", url, {"children": [text_block(str(content), bold)], "index": 0})

# 飞书单次建表的单元格上限约 63（实测 9 行×7 列 OK，10 行 FAIL）。
# 大表先建小表，再用 insert_table_row 逐行扩，避免一次性超限。
_MAX_TABLE_CELLS = 63


def add_table(doc_token, headers, rows, counter, col_widths=None):
    """
    建表：
      1. POST 表格容器（行数受单次单元格上限约束，先建初始行）
      2. insert_table_row 逐行扩到目标行数（绕过上限，保持单张连续表格）
      3. 逐 cell 写入文字
    """
    n_cols = len(headers)
    n_rows = 1 + len(rows)
    if col_widths is None:
        col_widths = [int(520 / n_cols)] * n_cols

    init_rows = max(1, min(n_rows, _MAX_TABLE_CELLS // n_cols))
    table_def = {
        "block_type": 31,
        "table": {
            "property": {
                "column_size": n_cols,
                "row_size":    init_rows,
            }
        }
    }

    n = counter[0]
    url = (f"https://open.feishu.cn/open-apis/docx/v1/documents"
           f"/{doc_token}/blocks/{doc_token}/children")
    resp = feishu("POST", url, {"children": [table_def], "index": n})

    if resp is None or resp.get("code") != 0:
        # 降级：文本行
        for row in [headers] + rows:
            add_block(doc_token, text_block("  |  ".join(str(c) for c in row)), counter)
        return

    counter[0] += 1

    created = resp.get("data", {}).get("children", [])
    if not created:
        return
    first = created[0]
    table_id = first if isinstance(first, str) else first.get("block_id", "")
    if not table_id:
        return

    # 逐行扩到目标行数
    patch_url = (f"https://open.feishu.cn/open-apis/docx/v1/documents"
                 f"/{doc_token}/blocks/{table_id}")
    for _ in range(n_rows - init_rows):
        feishu("PATCH", patch_url, {"insert_table_row": {"row_index": -1}})

    # Feishu table (31) children are cells (34) laid out flat: row0_col0, row0_col1, ..., row1_col0, ...
    all_cells = _get_children_ids(doc_token, table_id)
    all_rows  = [headers] + rows

    for r_idx, row in enumerate(all_rows):
        is_hdr = (r_idx == 0)
        for c_idx, val in enumerate(row):
            flat_idx = r_idx * n_cols + c_idx
            if flat_idx >= len(all_cells):
                break
            _add_text_to_cell(doc_token, all_cells[flat_idx], val, bold=is_hdr)

# ─── 报告主体 ─────────────────────────────────────────────────────────────────

def add_report_table(doc_token, cases, counter):
    """主汇总表：序号|模块|用例名称|结果|失败步骤详情|截图|耗时"""
    headers    = ["序号", "模块", "用例名称", "结果", "失败步骤详情", "截图", "耗时"]
    col_widths = [45,     75,     160,        75,     230,            75,     55]

    rows = []
    for fallback_seq, c in enumerate(cases, 1):
        steps  = c.get("steps", [])
        failed = [s for s in steps if not s.get("pass", True)]

        fail_lines = []
        for i, s in enumerate(failed, 1):
            line = f"{i}、步骤 [{s.get('type','')}]：{s.get('text','')} ❌"
            if s.get("note"):
                line += f"\n    原因：{s['note']}"
            fail_lines.append(line)
        fail_detail = "\n".join(fail_lines)

        dur = c.get("duration", "")
        seq = c.get("seq", fallback_seq)
        rows.append([
            str(seq),
            c.get("module", ""),
            c.get("name", ""),
            "✅ 通过" if c.get("passed", True) else "❌ 失败",
            fail_detail,
            "",
            f"{dur}s" if dur else ""
        ])

    add_table(doc_token, headers, rows, counter, col_widths=col_widths)

# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    args        = parse_args()
    app_name    = APP_NAMES.get(args.app, args.app)
    platform_cn = PLATFORM_CN.get(args.platform.lower(), args.platform)
    today       = datetime.date.today().strftime("%Y%m%d")
    title       = f"{app_name}{args.version}-{platform_cn}自动化报告-{today}"
    cases       = json.loads(args.cases) if args.cases else []

    devices_in_cases = list(dict.fromkeys(c["device"] for c in cases if c.get("device")))
    device_display   = "  ".join(devices_in_cases) if devices_in_cases else args.device

    # 创建 Wiki 节点
    create_resp = feishu("POST",
        f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes",
        {"obj_type": "docx", "node_type": "origin",
         "parent_node_token": PARENT_NODE, "title": title}
    )
    node_token = create_resp["data"]["node"]["node_token"]
    doc_token  = create_resp["data"]["node"]["obj_token"]

    counter = [0]

    # 报告头部
    add_block(doc_token, heading_block(1, f"{app_name}自动化测试报告"), counter)
    add_block(doc_token, text_block(
        f"执行时间：{today} {args.time}  |  总耗时：{args.duration}"
    ), counter)
    add_block(doc_token, text_block(
        f"平台：{args.platform}  设备：{device_display}  账号：{args.account}"
    ), counter)
    add_block(doc_token, divider_block(), counter)

    # 主表格
    if cases:
        add_report_table(doc_token, cases, counter)
    elif args.results:
        add_block(doc_token, heading_block(2, "用例明细"), counter)
        add_block(doc_token, text_block(args.results.replace("\\n", "\n")), counter)

    wiki_url = f"https://gaotuedu.feishu.cn/wiki/{node_token}"
    print(f"✓ Wiki 报告已创建：{wiki_url}")

    if getattr(args, "no_notify", False):
        print("[调试模式] 跳过群消息")
        return

    msg_text = (
        f"📈 {app_name} {args.version} 自动化测试报告\n\n"
        f"📅 执行日期：{today}  执行时间：{args.time}\n"
        f"📱 平台：{args.platform}  设备：{device_display}\n"
        f"👤 账号：{args.account}\n"
        f"⏱ 总耗时：{args.duration}\n\n"
        f"📊 执行概要\n"
        f"• 用例总数：{args.total}\n"
        f"• 通过：{args.passed} ✅\n"
        f"• 失败：{args.failed} ❌\n"
        f"• 通过率：{args.rate}%\n\n"
        f"📄 详细报告：{wiki_url}"
    )
    feishu("POST",
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        {"receive_id": GROUP_CHAT_ID, "msg_type": "text",
         "content": json.dumps({"text": msg_text})}
    )
    print(f"✓ 群消息已发送至 {app_name}自动化实践")

if __name__ == "__main__":
    main()
