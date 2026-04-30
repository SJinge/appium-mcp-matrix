#!/usr/bin/env python3
"""
创建矩阵 App 自动化测试 Wiki 报告并发送群通知。

Usage (表格模式，推荐):
  python3 wiki_report.py \
    --app gaotu --version 5.91.50 \
    --platform Android --device 26KUT24202013751 \
    --account 12100000000 --time "14:30:22" --duration "2m 35s" \
    --total 3 --passed 3 --failed 0 --rate 100 \
    --cases '[
      {"name":"用例2 AI搜索-快问模式","passed":true,"duration":120,"steps":[
        {"text":"进入 app 首页","type":"PRECOND","pass":true},
        {"text":"点击顶部搜索框","type":"ACTION","pass":true},
        {"text":"默认进入快问模式，有返回结果且正确","type":"ASSERT","pass":true,
         "note":"AI响应内容：1+1=2"}
      ]}
    ]'

Usage (纯文本模式，兼容旧版):
  python3 wiki_report.py \
    --app gaotu --version 5.91.50 --platform Android \
    --device ce67d979 --account 12100000000 \
    --time "14:30" --duration "2m 35s" \
    --total 5 --passed 4 --failed 1 --rate 80 \
    --results "• 用例1：AI搜索-快问模式 ✅ 通过（45s）\n• 用例2：上课tab展示 ❌ 失败（120s）"
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

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--app",      default="gaotu",  help="app_id，如 gaotu / tutu / jingpin")
    p.add_argument("--version",  required=True,    help="App 版本，如 5.91.50")
    p.add_argument("--platform", required=True,    help="Android 或 iOS")
    p.add_argument("--device",   required=True,    help="设备 UDID 或名称")
    p.add_argument("--account",  required=True,    help="登录账号（手机号）")
    p.add_argument("--time",     required=True,    help="执行开始时间，如 14:30:22")
    p.add_argument("--duration", required=True,    help="总耗时，如 2m 35s")
    p.add_argument("--total",    required=True,    help="用例总数")
    p.add_argument("--passed",   required=True,    help="通过数")
    p.add_argument("--failed",   required=True,    help="失败数")
    p.add_argument("--rate",     required=True,    help="通过率（不含%）")
    p.add_argument("--cases",    help="JSON 格式用例步骤详情（表格模式）")
    p.add_argument("--results",  help="纯文本用例明细（兼容旧版，\\n 分隔）")
    return p.parse_args()

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
    headers = {"Authorization": f"Bearer {TOKEN}",
               "Content-Type": "application/json; charset=utf-8"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"[WARN] HTTP {e.code}: {e.read().decode()[:200]}")
        return None

def get_child_count(doc_token):
    r = feishu("GET",
        f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_token}/blocks")
    return len(r["data"]["items"]) - 1

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

def cell_block(content, bold=False):
    return {"block_type": 34, "children": [text_block(content, bold)]}

def row_block(cells, bold=False):
    return {"block_type": 33, "children": [cell_block(c, bold) for c in cells]}

def table_block(headers, rows, col_widths=None):
    if col_widths is None:
        col_widths = [int(400 / len(headers))] * len(headers)
    all_rows = [row_block(headers, bold=True)] + [row_block(r) for r in rows]
    return {
        "block_type": 31,
        "table": {
            "property": {
                "column_size": len(headers),
                "row_size": len(all_rows),
                "column_width": col_widths,
                "header_row": True,
                "merge_info": []
            },
            "cells": []
        },
        "children": all_rows
    }

def add_block(doc_token, block):
    n = get_child_count(doc_token)
    url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_token}/blocks/{doc_token}/children"
    feishu("POST", url, {"children": [block], "index": n})

def add_case_section(doc_token, case_data):
    status   = "✅ 通过" if case_data.get("passed", True) else "❌ 失败"
    duration = case_data.get("duration", "")
    dur_str  = f"   ⏱ {duration}s" if duration else ""
    add_block(doc_token, heading_block(2, f"{case_data['name']}   {status}{dur_str}"))

    steps = case_data.get("steps", [])
    rows  = [[s.get("text",""), s.get("type",""),
              "✅ PASS" if s.get("pass", True) else "❌ FAIL"] for s in steps]
    add_block(doc_token, table_block(["步骤", "类型", "结果"], rows, col_widths=[280, 120, 120]))

    notes = [(s["text"], s["note"]) for s in steps
             if s.get("type") == "ASSERT" and s.get("note")]
    if notes:
        add_block(doc_token, text_block(
            "ASSERT 验证说明：  " + "  |  ".join(f"{t}：{n}" for t, n in notes)
        ))
    add_block(doc_token, divider_block())

def add_summary_table(doc_token, cases):
    rows = []
    total_pass = total_fail = 0
    for c in cases:
        steps = c.get("steps", [])
        p = sum(1 for s in steps if s.get("pass", True))
        f = sum(1 for s in steps if not s.get("pass", True))
        total_pass += p
        total_fail += f
        rows.append([c["name"],
                     "✅ 通过" if c.get("passed", True) else "❌ 失败",
                     f"{p} / {len(steps)}", str(f)])
    passed_cases = sum(1 for c in cases if c.get("passed", True))
    rows.append(["合计",
                 f"{passed_cases} / {len(cases)} 通过",
                 f"{total_pass} / {total_pass + total_fail}",
                 str(total_fail)])
    add_block(doc_token, heading_block(2, "汇总"))
    add_block(doc_token, table_block(
        ["用例", "结果", "通过步骤", "失败步骤"], rows,
        col_widths=[240, 100, 120, 100]
    ))

def main():
    args     = parse_args()
    app_name = APP_NAMES.get(args.app, args.app)
    platform_cn = PLATFORM_CN.get(args.platform.lower(), args.platform)
    today    = datetime.date.today().strftime("%Y%m%d")
    title    = f"{app_name}{args.version}-{platform_cn}自动化报告-{today}"
    cases    = json.loads(args.cases) if args.cases else []

    # 创建 Wiki 节点
    create_resp = feishu("POST",
        f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes",
        {"obj_type": "docx", "node_type": "origin",
         "parent_node_token": PARENT_NODE, "title": title}
    )
    node_token = create_resp["data"]["node"]["node_token"]
    doc_token  = create_resp["data"]["node"]["obj_token"]

    # 报告头部
    add_block(doc_token, heading_block(1, f"{app_name}自动化测试报告"))
    add_block(doc_token, text_block(f"执行时间：  {today} {args.time}  |  总耗时：{args.duration}"))
    add_block(doc_token, text_block(
        f"平台：  {args.platform}　设备：  {args.device}　账号：  {args.account}"
    ))
    add_block(doc_token, divider_block())

    # 用例详情
    if cases:
        for case in cases:
            add_case_section(doc_token, case)
        add_summary_table(doc_token, cases)
    elif args.results:
        add_block(doc_token, heading_block(2, "用例明细"))
        add_block(doc_token, text_block(args.results.replace("\\n", "\n")))
        add_block(doc_token, divider_block())

    # 群消息
    wiki_url = f"https://gaotuedu.feishu.cn/wiki/{node_token}"
    results_summary = (
        "\n".join(
            f"• {c['name']} {'✅ 通过' if c.get('passed') else '❌ 失败'}"
            + (f"（{c['duration']}s）" if c.get("duration") else "")
            for c in cases
        ) if cases else (args.results or "").replace("\\n", "\n")
    )
    msg_text = (
        f"📈 {app_name} {args.version} 自动化测试报告\n\n"
        f"📅 执行日期：{today}  执行时间：{args.time}\n"
        f"📱 平台：{args.platform}  设备：{args.device}\n"
        f"👤 账号：{args.account}\n"
        f"⏱ 总耗时：{args.duration}\n\n"
        f"📊 执行概要\n"
        f"• 用例总数：{args.total}\n"
        f"• 通过：{args.passed} ✅\n"
        f"• 失败：{args.failed} ❌\n"
        f"• 通过率：{args.rate}%\n\n"
        f"📝 用例明细\n{results_summary}\n\n"
        f"📄 详细报告：{wiki_url}"
    )
    feishu("POST",
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        {"receive_id": GROUP_CHAT_ID, "msg_type": "text",
         "content": json.dumps({"text": msg_text})}
    )

    print(f"✓ Wiki 报告已创建：{wiki_url}")
    print(f"✓ 群消息已发送至 {app_name}自动化实践")

if __name__ == "__main__":
    main()
