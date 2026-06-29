import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run_status


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(run_status, "RUNS_DIR", str(tmp_path))


def test_init_and_load(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    run_status.init_run("gaotu_1.0_android", "gaotu", "1.0", "android", devices=["a1"])
    data = run_status.load("gaotu_1.0_android")
    assert data["phase"] == "starting"
    assert data["devices"]["a1"]["state"] == "pending"
    assert "updated_at" in data


def test_set_phase_and_update_device(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    run_status.init_run("r1", "gaotu", "1.0", "android", devices=["a1"])
    run_status.set_phase("r1", "executing", "跑起来了")
    run_status.update_device("r1", "a1", **{"state": "done", "done": 3, "pass": 2, "fail": 1})
    data = run_status.load("r1")
    assert data["phase"] == "executing"
    assert data["current"] == "跑起来了"
    assert data["devices"]["a1"]["pass"] == 2


def test_finish_appends_history(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    run_status.init_run("r2", "gaotu", "1.0", "android")
    run_status.finish("r2", "done", "完成", total=5, passed=4)
    data = run_status.load("r2")
    assert data["phase"] == "done"
    assert data["summary"]["passed"] == 4
    hist = (tmp_path / "history.jsonl").read_text().strip().splitlines()
    assert len(hist) == 1
    row = json.loads(hist[0])
    assert row["run_id"] == "r2" and row["passed"] == 4


def test_set_phase_on_missing_run_is_noop(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    run_status.set_phase("nope", "executing")  # 不存在不报错
    assert run_status.load("nope") == {}


def test_load_all_sorted(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    run_status.init_run("r_a", "gaotu", "1.0", "android")
    run_status.init_run("r_b", "gaotu", "2.0", "ios")
    runs = run_status.load_all()
    assert {r["run_id"] for r in runs} == {"r_a", "r_b"}
