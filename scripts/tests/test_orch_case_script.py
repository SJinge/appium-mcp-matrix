import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import orch_case_script as s


# ---- Fix 1: split_evidence_tokens tolerates agent prose ----

def test_split_evidence_tokens_splits_commas():
    assert s.split_evidence_tokens("同意, 不同意, 简单浏览模式") == ["同意", "不同意", "简单浏览模式"]


def test_split_evidence_tokens_strips_page_source_contains_prefix():
    # text 断言只留屏显文案:元素 id logo_gaotu/privacy_slogan 非可见文本,丢弃。
    tokens = s.split_evidence_tokens(
        "page_source contains logo_gaotu/privacy_slogan, 同意, 不同意, 《高途隐私政策》"
    )
    assert tokens == ["同意", "不同意", "《高途隐私政策》"]


def test_split_evidence_tokens_strips_button_link_scaffolding():
    tokens = s.split_evidence_tokens(
        "page_source contains visible buttons 同意/简单浏览模式 and links 《服务协议》/《隐私政策》"
    )
    assert tokens == ["同意", "简单浏览模式", "《服务协议》", "《隐私政策》"]


def test_split_evidence_tokens_drops_trailing_english_scaffolding():
    tokens = s.split_evidence_tokens(
        "page_source contains 手机号登录, 获取验证码, 密码登录 and login agreement text"
    )
    assert tokens == ["手机号登录", "获取验证码", "密码登录"]


def test_split_evidence_tokens_splits_after_clicking():
    tokens = s.split_evidence_tokens(
        "page_source contains visible title 温馨提示 after clicking 不同意"
    )
    assert tokens == ["温馨提示", "不同意"]


def test_split_evidence_tokens_keeps_clean_semicolon_input_idempotent():
    assert s.split_evidence_tokens("同意；不同意") == ["同意", "不同意"]


def test_split_evidence_tokens_drops_ax_id_like_tokens():
    # ax-id / 语义名(下划线 ASCII)在 text 断言里永远 miss（page_source 渲染文案里没有它），
    # 会把本该通过的断言拖成必失败——必须丢弃；要断言元素存在应改用 id 断言。
    assert s.split_evidence_tokens("page_source contains logo_gaotu") == []
    assert s.split_evidence_tokens("logo_gaotu；privacy_slogan；同意") == ["同意"]


def test_split_evidence_tokens_drops_screenshot_path_fragments():
    # 截图路径整段抹掉,不被 / 拆成 Users;mac;… 残渣。
    ev = "同意；不同意；screenshot=/Users/mac/mcp_shots/gaotu/20260721_1340_x/01_privacy_dialog.png"
    assert s.sanitize_text_evidence(ev) == "同意；不同意"


def test_split_evidence_tokens_drops_attr_and_type_prefixes():
    # "StaticText name=温馨提示" / "value含X" 剥壳露文案;visible=false 这类属性键值丢弃。
    assert s.sanitize_text_evidence("StaticText name=温馨提示") == "温馨提示"
    assert s.sanitize_text_evidence("TextView value含『感谢您使用高途』") == "感谢您使用高途"
    assert "visible=false" not in s.sanitize_text_evidence("温馨提示；原节点 visible=false")


# ---- iOS: extract_ios_visible_tokens 把定位散文压回可见文案 ----

def test_ios_tokens_button_quotes():
    # 编号1 启动:两个按钮引号文案
    assert s.extract_ios_visible_tokens(
        "XCUIElementTypeButton name='同意' + name='不同意'"
    ) == ["同意", "不同意"]


def test_ios_tokens_mixed_links_and_locator_values():
    # 编号3:书名号链接 + accessibility id= 定位值,都要保留
    toks = s.extract_ios_visible_tokens(
        "《高途用户服务协议》《高途隐私政策》《儿童隐私保护声明》 & "
        "accessibility id=不同意 & accessibility id=同意"
    )
    assert "《高途用户服务协议》" in toks
    assert "《高途隐私政策》" in toks
    assert "《儿童隐私保护声明》" in toks
    assert "不同意" in toks and "同意" in toks


def test_ios_tokens_byval():
    assert s.extract_ios_visible_tokens("by=name,value=今日推荐") == ["今日推荐"]


def test_ios_tokens_xpath_name():
    assert s.extract_ios_visible_tokens(
        "//XCUIElementTypeStaticText[@name='手机号登录'] 命中"
    ) == ["手机号登录"]


def test_ios_tokens_strip_bracket_residue():
    # name='确定'] 不能把 ] 抓进 token
    assert s.extract_ios_visible_tokens(
        "//XCUIElementTypeButton[@name='确定'] and name='取消'"
    ) == ["确定", "取消"]


def test_ios_tokens_traits_dropped():
    # traits='Button, Selected' 是元素特征,非屏显文案,整段抹掉;只留 首页
    assert s.extract_ios_visible_tokens(
        "XCUIElementTypeButton name='首页' traits='Button, Selected'"
    ) == ["首页"]


def test_ios_tokens_fallback_bare_cjk():
    # 高精度全空时才回退裸 CJK,丢弃脚手架/描述词
    toks = s.extract_ios_visible_tokens("StaticText 温馨提示 出现")
    assert toks == ["温馨提示"]


def test_ios_tokens_screenshot_path_removed():
    toks = s.extract_ios_visible_tokens(
        "name='同意' screenshot=/Users/mac/mcp_shots/gaotu/x/01.png"
    )
    assert toks == ["同意"]


def test_ios_tokens_empty():
    assert s.extract_ios_visible_tokens("") == []
    assert s.extract_ios_visible_tokens(None) == []


# ---- Fix 2: generation sanitizes text evidence, keeps id evidence raw ----

def test_flow_step_from_assert_sanitizes_text_evidence():
    step = {
        "type": "ASSERT", "verify_method": "text", "confidence": "high", "passed": True,
        "text": "1. 隐私弹窗弹出",
        "evidence": "page_source contains 同意, 不同意, 《高途隐私政策》",
    }
    out = s.flow_step_from_assert(step)
    assert out["value"] == "同意；不同意；《高途隐私政策》"


def test_flow_step_from_assert_keeps_id_evidence_raw():
    step = {
        "type": "ASSERT", "verify_method": "id", "confidence": "high", "passed": True,
        "text": "打开首页",
        "evidence": "com.gaotu100.superclass:id/home",
    }
    out = s.flow_step_from_assert(step)
    # id evidence must NOT be split on '/', which would corrupt the resource-id
    assert out["value"] == "com.gaotu100.superclass:id/home"
