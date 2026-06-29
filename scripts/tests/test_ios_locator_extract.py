import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ios_locator_extract as ix

SAMPLE = """
<XCUIElementTypeApplication name="高途">
  <XCUIElementTypeButton type="XCUIElementTypeButton" name="登录" label="登录" visible="true"/>
  <XCUIElementTypeButton type="XCUIElementTypeButton" name="上课" label="上课" visible="true"/>
  <XCUIElementTypeStaticText type="XCUIElementTypeStaticText" name="今日学习推荐" label="今日学习推荐" visible="true"/>
  <XCUIElementTypeCell type="XCUIElementTypeCell" name="课程项" label="课程项" visible="true"/>
  <XCUIElementTypeCell type="XCUIElementTypeCell" name="课程项" label="课程项" visible="true"/>
  <XCUIElementTypeImage type="XCUIElementTypeImage" name="" label="" visible="true"/>
  <XCUIElementTypeButton type="XCUIElementTypeButton" name="隐藏" label="隐藏" visible="false"/>
</XCUIElementTypeApplication>
"""


def test_parse_skips_no_name_and_non_xcui():
    elems = ix.parse_ios_elements(SAMPLE)
    anchors = {(e["type"], e["name"]) for e in elems}
    # 无 name/label 的 Image 被跳过
    assert ("XCUIElementTypeImage", "") not in anchors
    # 有 name 的都在
    assert ("XCUIElementTypeButton", "登录") in anchors


def test_parse_bad_xml_returns_empty():
    assert ix.parse_ios_elements("<not closed") == []


def test_parse_excludes_application_root():
    elems = ix.parse_ios_elements(SAMPLE)
    assert all(e["type"] != "XCUIElementTypeApplication" for e in elems)


def test_best_locator_unique_name_uses_accessibility_id():
    nc = Counter({"登录": 1})
    tnc = Counter({("XCUIElementTypeButton", "登录"): 1})
    loc = ix.best_locator({"type": "XCUIElementTypeButton", "name": "登录", "label": "登录"}, nc, tnc)
    assert loc["strategy"] == "accessibility id"
    assert loc["selector"] == "登录"
    assert loc["unique"] is True


def test_best_locator_dup_name_uses_class_chain_non_unique():
    nc = Counter({"课程项": 2})
    tnc = Counter({("XCUIElementTypeCell", "课程项"): 2})
    loc = ix.best_locator({"type": "XCUIElementTypeCell", "name": "课程项", "label": "课程项"}, nc, tnc)
    assert loc["strategy"] == "-ios class chain"
    assert loc["unique"] is False
    assert 'name == "课程项"' in loc["selector"]


def test_best_locator_no_anchor_needs_vision():
    loc = ix.best_locator({"type": "XCUIElementTypeImage", "name": "", "label": ""},
                          Counter(), Counter())
    assert loc["strategy"] == "needs_vision"


def test_class_chain_escaping():
    s = ix._chain("XCUIElementTypeButton", "name", '说"你好"')
    assert s == '**/XCUIElementTypeButton[`name == "说\\"你好\\""`]'


def test_extract_page_filters_invisible_and_dedups():
    res = ix.extract_page(SAMPLE)
    anchors = [e["anchor"] for e in res]
    assert "隐藏" not in anchors          # invisible 过滤
    assert anchors.count("课程项") == 1    # 重复去重
    assert "登录" in anchors


def test_extract_page_marks_dup_cell_non_unique():
    res = ix.extract_page(SAMPLE)
    cell = next(e for e in res if e["anchor"] == "课程项")
    assert cell["unique"] is False
    login = next(e for e in res if e["anchor"] == "登录")
    assert login["strategy"] == "accessibility id"


def test_merge_page():
    truth = {}
    ix.merge_page(truth, "上课", [{"anchor": "登录"}])
    assert truth["pages"]["上课"] == [{"anchor": "登录"}]
    ix.merge_page(truth, "上课", [{"anchor": "新"}])  # 同页覆盖
    assert truth["pages"]["上课"] == [{"anchor": "新"}]
