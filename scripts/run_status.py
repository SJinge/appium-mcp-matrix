#!/usr/bin/env python3
"""run 运行状态读写 —— 把触发到完成之间的黑盒变成可查的结构化状态。

每个 run（app_version[_platform]）一份 JSON 写到持久目录 runs/{run_id}.json：
    phase / started_at / updated_at / 各设备进度 / current 文字描述。
orchestrate 在每个阶段切换时更新，collect_results 落地一台 result 就刷新该设备计数。
server 的 GET /status 读 runs/ 目录即可回答「现在跑到哪、几台几条、卡没卡」。

所有写入走临时文件 + os.replace 原子替换，避免 /status 读到半截 JSON。
run 结束 append 一行到 runs/history.jsonl，供趋势分析（哪些用例跨版本反复 flaky）。

环境变量 RUN_STATUS_DIR 可覆盖目录（orchestrate 与 server 必须一致；默认同仓库 runs/）。
"""
import json
import os
import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.environ.get("RUN_STATUS_DIR", os.path.join(PROJECT_ROOT, "runs"))


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _path(run_id: str) -> str:
    return os.path.join(RUNS_DIR, f"{run_id}.json")


def _read(run_id: str) -> dict:
    try:
        with open(_path(run_id)) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write(run_id: str, data: dict):
    os.makedirs(RUNS_DIR, exist_ok=True)
    data["updated_at"] = _now()
    tmp = _path(run_id) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _path(run_id))  # 原子替换，避免读到半截


def init_run(run_id: str, app_id: str, version: str, platform: str, devices=None) -> dict:
    data = {
        "run_id":     run_id,
        "app_id":     app_id,
        "version":    version,
        "platform":   platform,
        "phase":      "starting",
        "current":    "已触发，准备下载",
        "started_at": _now(),
        "devices":    {},
    }
    for udid in (devices or []):
        data["devices"][udid] = {"state": "pending", "done": 0, "total": 0, "pass": 0, "fail": 0}
    _write(run_id, data)
    return data


def set_phase(run_id: str, phase: str, note: str = ""):
    data = _read(run_id)
    if not data:
        return
    data["phase"] = phase
    if note:
        data["current"] = note
    _write(run_id, data)


def update_device(run_id: str, udid: str, **fields):
    data = _read(run_id)
    if not data:
        return
    dev = data.setdefault("devices", {}).setdefault(udid, {})
    dev.update(fields)
    _write(run_id, data)


def finish(run_id: str, phase: str = "done", note: str = "", **summary):
    data = _read(run_id)
    if not data:
        data = {"run_id": run_id}
    data["phase"] = phase
    if note:
        data["current"] = note
    if summary:
        data.setdefault("summary", {}).update(summary)
    data["finished_at"] = _now()
    _write(run_id, data)
    # 追加历史（趋势分析用），失败不影响主流程
    try:
        os.makedirs(RUNS_DIR, exist_ok=True)
        row = {k: data.get(k) for k in
               ("run_id", "app_id", "version", "platform",
                "started_at", "finished_at", "phase")}
        row.update(data.get("summary", {}))
        with open(os.path.join(RUNS_DIR, "history.jsonl"), "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load(run_id: str) -> dict:
    return _read(run_id)


def load_all(limit: int = 50) -> list:
    try:
        files = [f for f in os.listdir(RUNS_DIR) if f.endswith(".json")]
    except OSError:
        return []
    runs = []
    for fn in files:
        try:
            with open(os.path.join(RUNS_DIR, fn)) as f:
                runs.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            continue
    runs.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
    return runs[:limit]
