import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import orch_case_script as s


# ---- Fix 1: split_evidence_tokens tolerates agent prose ----

def test_split_evidence_tokens_splits_commas():
    assert s.split_evidence_tokens("同意, 不同意, 简单浏览模式") == ["同意", "不同意", "简单浏览模式"]


def test_split_evidence_tokens_strips_page_source_contains_prefix():
    tokens = s.split_evidence_tokens(
        "page_source contains logo_gaotu/privacy_slogan, 同意, 不同意, 《高途隐私政策》"
    )
    assert tokens == ["logo_gaotu", "privacy_slogan", "同意", "不同意", "《高途隐私政策》"]


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


def test_split_evidence_tokens_keeps_id_like_underscore_tokens():
    # placeholder-looking names that are actually real accessibility ids must survive
    assert "logo_gaotu" in s.split_evidence_tokens("page_source contains logo_gaotu")


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
