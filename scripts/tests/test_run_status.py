import sys, os, json, threading
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


def test_write_is_safe_under_concurrent_replace(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    barrier = threading.Barrier(2)
    real_replace = run_status.os.replace

    def delayed_replace(src, dst):
        barrier.wait(timeout=2)
        real_replace(src, dst)

    monkeypatch.setattr(run_status.os, "replace", delayed_replace)

    errors = []

    def writer(idx):
        try:
            run_status._write("race", {"writer": idx})
        except Exception as exc:  # pragma: no cover - failure path asserted below
            errors.append(exc)

    t1 = threading.Thread(target=writer, args=(1,))
    t2 = threading.Thread(target=writer, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == []
    data = run_status.load("race")
    assert data["writer"] in {1, 2}


def test_update_device_preserves_multiple_devices_under_concurrency(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    run_status.init_run("r3", "gaotu", "1.0", "android", devices=["a1", "a2"])

    t1 = threading.Thread(target=run_status.update_device,
                          args=("r3", "a1"),
                          kwargs={"state": "done", "done": 20, "pass": 18, "fail": 2})
    t2 = threading.Thread(target=run_status.update_device,
                          args=("r3", "a2"),
                          kwargs={"state": "done", "done": 15, "pass": 10, "fail": 5})
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    data = run_status.load("r3")
    assert data["devices"]["a1"]["done"] == 20
    assert data["devices"]["a2"]["done"] == 15


def test_write_retries_when_replace_hits_missing_tmp(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    real_replace = run_status.os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FileNotFoundError(src)
        return real_replace(src, dst)

    monkeypatch.setattr(run_status.os, "replace", flaky_replace)

    run_status._write("retry", {"phase": "executing"})
    data = run_status.load("retry")
    assert data["phase"] == "executing"
    assert calls["n"] == 2
