#!/usr/bin/env python3
"""
高途 GPS 产品单元 + 子产品批量创建脚本

用法:
  python3 create_course.py <产品单元名称> <客户价值> <学年> <学季>

示例:
  python3 create_course.py "sjg-gps-数学" 数学 2025-2026 春
  python3 create_course.py "sjg-gps-英语" 英语 2026-2027 暑

客户价值可选: 语文 数学 英语 物理 化学 生物 历史 地理 政治
学年可选: 2025-2026  2026-2027
学季可选: 春 暑 秋 寒
"""

import json
import sys
import requests

# ── 固定配置 ──────────────────────────────────────────────
AUTH_FILE = "./auth.json"
BASE_URL = "https://test-os.baijia.com/api/teachProduct"

PRODUCT_LINE_NUMBER = "16843366157647942"
TEMPLATE_NUMBER = "16844709592105830"
TEMPLATE_VERSION = 8
SCHOOL_SYSTEM = 1
STUDY_STAGE_CODES = [10]
GRADE_CODES = [11, 12, 13, 14, 15, 16]
PRODUCT_DEPARTMENT = "10000329/10000004/10000355"
DEPARTMENT_STORE = {"departmentIdPath": "10000329/10000004/10000355", "storeId": "523613735500277760"}

# 小学全部品类（1-6年级所有科目）
CATEGORY_LIST = [
    "5/100/1010","5/100/1020","5/100/1030","5/100/1040","5/100/1050",
    "5/100/810745","5/100/810746","5/100/810747","5/100/811357",
    "5/110/1110","5/110/1120","5/110/1130","5/110/1140","5/110/1150",
    "5/110/810748","5/110/810749","5/110/810750","5/110/811358",
    "5/120/1210","5/120/1220","5/120/1230","5/120/1240","5/120/1250",
    "5/120/810751","5/120/810752","5/120/810753","5/120/811359","5/120/811500",
    "5/130/1310","5/130/1320","5/130/1330","5/130/1340","5/130/1350",
    "5/130/810754","5/130/810755","5/130/810756","5/130/811360",
    "5/140/1410","5/140/1420","5/140/1430","5/140/1440","5/140/1450",
    "5/140/810757","5/140/810758","5/140/810759","5/140/811361",
    "5/150/1510","5/150/1520","5/150/1530","5/150/1540","5/150/1550",
    "5/150/810760","5/150/810761","5/150/810762","5/150/811362",
    "5/810650/810651","5/810650/810652","5/810650/810653",
]

# SPU 模板属性（固定）
SPU_TEMPLATE_ATTRS = [
    {"attrId": "9", "attrValues": ["2"]},            # 产品体系性=系列课
    {"attrId": "8", "attrValues": ["2"]},            # 学习目的=系统学习
    {"attrId": "16963523223027850", "attrValues": ["auto"]},  # 接口自动化@文本
]

# 客户价值代码映射（K12学科 categoryEnumType=4）
SUBJECT_CODES = {
    "数学": "6/1",
    "化学": "6/2",
    "生物": "6/3",
    "英语": "6/4",
    "语文": "6/5",
    "物理": "6/6",
    "政治": "6/7",
    "道法": "6/7",
    "地理": "6/11",
    "历史": "6/12",
}

# 学年代码映射
YEAR_CODES = {
    "2025-2026": "2025",
    "2026-2027": "2026",
    "2027-2028": "2027",
    "2028-2029": "2028",
}

# 学季代码映射
SEASON_CODES = {
    "春": "1",
    "暑": "2",
    "秋": "3",
    "寒": "4",
}


def load_cookies():
    with open(AUTH_FILE) as f:
        data = json.load(f)
    return {c["name"]: c["value"] for c in data.get("cookies", []) if "baijia" in c.get("domain", "")}


def api_post(session, path, payload):
    resp = session.post(f"{BASE_URL}{path}", json=payload)
    resp.raise_for_status()
    r = resp.json()
    if r.get("code") not in (0, 200):
        raise RuntimeError(f"API error at {path}: code={r.get('code')} msg={r.get('msg')}")
    return r.get("data")


def create_spu(session, name, subject_code):
    print(f"[1/3] 创建产品单元: {name} ...")
    payload = {
        "name": name,
        "productLineNumber": PRODUCT_LINE_NUMBER,
        "templateNumber": TEMPLATE_NUMBER,
        "templateVersion": TEMPLATE_VERSION,
        "schoolSystem": SCHOOL_SYSTEM,
        "studyStageCodes": STUDY_STAGE_CODES,
        "gradeCodes": GRADE_CODES,
        "productDepartment": PRODUCT_DEPARTMENT,
        "categoryList": CATEGORY_LIST,
        "valueCategories": [{"categoryEnumType": 4, "categoryValueCodeList": [subject_code]}],
        "labelIds": [],
        "isTest": 0,
        "teachingApps": [1, 2],
        "templateAttrs": SPU_TEMPLATE_ATTRS,
    }
    data = api_post(session, "/teachProduct/spu/add", payload)
    spu_number = data.get("number") if isinstance(data, dict) else str(data)
    print(f"    ✓ 产品单元已创建，编号: {spu_number}")
    return spu_number


def create_sku(session, spu_number):
    print("[2/3] 创建子产品 ...")
    data = api_post(session, "/teachProductClazzType/sku/add", {"teachProductNumber": spu_number})
    sku_number = str(data)
    print(f"    ✓ 子产品已创建，编号: {sku_number}")
    return sku_number


def configure_sku(session, sku_number, year_code, season_code):
    print(f"[3/3] 配置子产品（学年={year_code} 学季={season_code}）...")
    payload = {
        "clazzTypeNumber": sku_number,
        "textBookIds": ["0"],
        "lessonType": 2,
        "replayDuration": 365,
        "teachingServiceDuration": 365,
        "attributeVOS": [
            {"attrId": "1", "attrValues": [year_code]},
            {"attrId": "2", "attrValues": [season_code]},
        ],
        "departmentStoreDTOList": [DEPARTMENT_STORE],
    }
    api_post(session, "/teachProductClazzType/sku/baseInfo/edit", payload)
    print(f"    ✓ 子产品配置完成")


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(1)

    _, spu_name, subject_name, year_str, season_str = sys.argv

    subject_code = SUBJECT_CODES.get(subject_name)
    if not subject_code:
        print(f"未知客户价值: {subject_name}，可选: {', '.join(SUBJECT_CODES.keys())}")
        sys.exit(1)

    year_code = YEAR_CODES.get(year_str)
    if not year_code:
        print(f"未知学年: {year_str}，可选: {', '.join(YEAR_CODES.keys())}")
        sys.exit(1)

    season_code = SEASON_CODES.get(season_str)
    if not season_code:
        print(f"未知学季: {season_str}，可选: {', '.join(SEASON_CODES.keys())}")
        sys.exit(1)

    cookies = load_cookies()
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        "Content-Type": "application/json",
        "Origin": "https://test-os.baijia.com",
        "Referer": "https://test-os.baijia.com/",
    })

    print(f"\n开始创建: {spu_name} / {subject_name} / {year_str}{season_str}\n")

    spu_number = create_spu(session, spu_name, subject_code)
    sku_number = create_sku(session, spu_number)
    configure_sku(session, sku_number, year_code, season_code)

    print(f"\n✓ 完成！")
    print(f"  产品单元编号: {spu_number}")
    print(f"  子产品编号:   {sku_number}")
    print(f"  子产品名称:   {year_str}{season_str}")
    print(f"  查看: https://test-os.baijia.com/gps/ces-teach/spu/detail?mode=create&productNumber={spu_number}")


if __name__ == "__main__":
    main()
