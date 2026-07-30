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


def _setup_truth(tmp_path, app="gaotu", ids=None):
    """app 级真相源:apps/{app}/elements.truth.json(不再按版本分目录)。"""
    d = tmp_path / "apps" / app
    d.mkdir(parents=True, exist_ok=True)
    (d / "elements.truth.json").write_text(json.dumps({"ids": ids or ["account_sign_btn"]}))
    return d


def test_put_then_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "PROJECT_ROOT", str(tmp_path))
    _setup_truth(tmp_path)
    lc.cmd_put(type("A", (), dict(app_id="gaotu", version="5.91.80", step="点击登录按钮",
               page=None, selector="com.gaotu100.superclass:id/account_sign_btn",
               strategy="id", module="account", no_verify=False))())
    cache = lc.load_cache("gaotu")
    assert "点击登录按钮" in cache
    assert cache["点击登录按钮"]["selector"].endswith("account_sign_btn")
    assert cache["点击登录按钮"]["verified_version"] == "5.91.80"


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


def test_get_evicts_entry_stale_vs_truth(tmp_path, monkeypatch):
    """升版后 id 已不在真相源:get 命中也按 miss 处理并剔除脏条目。"""
    monkeypatch.setattr(lc, "PROJECT_ROOT", str(tmp_path))
    _setup_truth(tmp_path, ids=["still_here"])  # gone_btn 已不在真相源
    lc.save_cache("gaotu", {
        "还在": {"selector": "p:id/still_here", "strategy": "id"},
        "没了": {"selector": "p:id/gone_btn", "strategy": "id"},
    })
    a = type("A", (), dict(app_id="gaotu", version=None, step="没了", page=None))()
    try:
        lc.cmd_get(a)
        assert False, "stale 条目应按 miss 退出 1"
    except SystemExit as e:
        assert e.code == 1
    cache = lc.load_cache("gaotu")
    assert "没了" not in cache  # 脏条目已被剔除
    assert "还在" in cache      # 有效条目保留


def test_get_hit_survives_when_id_in_truth(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "PROJECT_ROOT", str(tmp_path))
    _setup_truth(tmp_path, ids=["still_here"])
    lc.save_cache("gaotu", {"还在": {"selector": "p:id/still_here", "strategy": "id"}})
    a = type("A", (), dict(app_id="gaotu", version=None, step="还在", page=None))()
    lc.cmd_get(a)  # 不应抛出
    assert lc.load_cache("gaotu")["还在"]["hit_count"] == 1


def test_truth_ids_from_app_level_active_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "PROJECT_ROOT", str(tmp_path))
    d = tmp_path / "apps" / "gaotu"
    d.mkdir(parents=True)
    (d / "elements.truth.json").write_text(json.dumps({
        "entries": [
            {"id": "keep_btn", "deprecated": False},
            {"id": "old_btn", "deprecated": True},
        ]
    }))
    assert lc._truth_ids("gaotu") == {"keep_btn"}
