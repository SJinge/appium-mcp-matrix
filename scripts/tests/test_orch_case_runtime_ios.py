import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import orch_case_runtime_ios as ios_rt


def test_sms_code_for_walkthrough_account():
    # 走查账号(手机号 12 开头)验证码固定 1000。
    assert ios_rt.sms_code_for_account("12345679000") == "1000"
    assert ios_rt.sms_code_for_account("12000000000") == "1000"


def test_sms_code_empty_for_non_walkthrough_account():
    # 非 12 开头 / 哨兵 / 空 → 无法脚本自动登录,返回空串交回退 agent,绝不猜验证码。
    for account in ("13800138000", "<UNLOGIN>", "<NONE>", "", None):
        assert ios_rt.sms_code_for_account(account) == ""
