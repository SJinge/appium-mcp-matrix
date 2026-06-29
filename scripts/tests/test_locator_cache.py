import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import locator_cache as lc

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "locator_cache.py")


# ---------- 纯函数 ----------

def test_normalize_step():
    assert lc.normalize_step("  点击 登录按钮 。") == "点击 登录按钮"
    assert lc.normalize_step("输入手机号,") == "输入手机号"


def test_make_key_with_and_without_page():
    assert lc.make_key("点击登录按钮") == "点击登录按钮"
    assert lc.make_key("点击确定", "LoginActivity") == "点击确定@LoginActivity"


def test_selector_id():
    assert lc.selector_id("com.gaotu100.superclass:id/account_sign_btn") == "account_sign_btn"
    assert lc.selector_id("//*[@text='登录']") == ""


def test_survives_diff_id_strategy():
    e = {"strategy": "id", "selector": "p:id/account_sign_btn"}
    assert lc.survives_diff(e, {"account_sign_btn"}) is True
    assert lc.survives_diff(e, {"other"}) is False


def test_survives_diff_non_id_kept():
    e = {"strategy": "xpath", "selector": "//*[@text='x']"}
    assert lc.survives_diff(e, set()) is True


# ---------- CLI 端到端(隔离到 tmp 工程根) ----------

def _run(args, root):
    env = dict(os.environ)
    return subprocess.run([sys.executable, SCRIPT] + args,
                          capture_output=True, text=True, cwd=root,
                          env=env)


def _setup_truth(tmp_path, app="gaotu", ver="5.91.80", ids=None):
    d = tmp_path / "apps" / app / ver
    d.mkdir(parents=True)
    (d / "elements.truth.json").write_text(json.dumps({"ids": ids or ["account_sign_btn"]}))
    return d


def test_put_then_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "PROJECT_ROOT", str(tmp_path))
    _setup_truth(tmp_path)
    lc.cmd_put(type("A", (), dict(app_id="gaotu", version="5.91.80", step="点击登录按钮",
               page=None, selector="com.gaotu100.superclass:id/account_sign_btn",
               strategy="id", module="account", no_verify=False))())
    cache = lc.load_cache("gaotu", "5.91.80")
    assert "点击登录按钮" in cache
    assert cache["点击登录按钮"]["selector"].endswith("account_sign_btn")


def test_put_rejects_dirty_id(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "PROJECT_ROOT", str(tmp_path))
    _setup_truth(tmp_path, ids=["only_this"])
    args = type("A", (), dict(app_id="gaotu", version="5.91.80", step="x", page=None,
               selector="com.gaotu100.superclass:id/ghost_id", strategy="id",
               module=None, no_verify=False))()
    try:
        lc.cmd_put(args)
        assert False, "should have exited"
    except SystemExit as e:
        assert e.code == 2


def test_seed_from_diff_keeps_valid_drops_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "PROJECT_ROOT", str(tmp_path))
    # 旧版缓存:一个仍有效、一个被删
    _setup_truth(tmp_path, ver="5.91.70", ids=["keep_btn", "drop_btn"])
    _setup_truth(tmp_path, ver="5.91.80", ids=["keep_btn"])  # drop_btn 在新版没了
    lc.save_cache("gaotu", "5.91.70", {
        "保留步骤": {"selector": "p:id/keep_btn", "strategy": "id"},
        "丢弃步骤": {"selector": "p:id/drop_btn", "strategy": "id"},
    })
    a = type("A", (), {})()
    setattr(a, "app_id", "gaotu"); setattr(a, "from", "5.91.70"); setattr(a, "to", "5.91.80")
    lc.cmd_seed_from_diff(a)
    new = lc.load_cache("gaotu", "5.91.80")
    assert "保留步骤" in new
    assert "丢弃步骤" not in new
