import datetime
import json
import os
import time


def tail_file(path: str, n: int = 200) -> str:
    # agent 日志可能含非法 utf-8 字节(claude 输出截断的多字节字符),严格解码会抛
    # UnicodeDecodeError 冒泡到 _run 未捕获 → 整轮 orchestrate 崩溃。errors="replace" 兜底。
    try:
        with open(path, encoding="utf-8", errors="replace") as file_obj:
            return file_obj.read()[-n:].strip().replace("\n", " ")
    except OSError:
        return ""


def load_jsonl(path: str) -> list:
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as file_obj:
            for line in file_obj:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def incr_status(run_id, udid, path, load_jsonl_fn, run_status_module):
    if not (run_id and os.path.exists(path)):
        return
    cases = load_jsonl_fn(path)
    run_status_module.update_device(run_id, udid, **{
        "state": "running",
        "done": len(cases),
        "pass": sum(1 for c in cases if c.get("passed")),
        "fail": sum(1 for c in cases if not c.get("passed")),
    })


def collect_results(
    procs: dict,
    load_jsonl_fn,
    incr_status_fn,
    tail_file_fn,
    agent_log_path_fn,
    notify_fn,
    run_status_module,
    log,
    result_dir: str = "/tmp",
    timeout: int = 90 * 60,
    app_id: str = None,
    version: str = None,
    run_id: str = None,
    poll_interval: int = 10,
    device_totals: dict = None,
) -> dict:
    deadline = time.time() + timeout
    pending = set(procs.keys())
    results = {}

    while pending and time.time() < deadline:
        for udid in list(pending):
            path = os.path.join(result_dir, f"result_{udid}.jsonl")
            proc = procs.get(udid)
            alive = proc is not None and proc.poll() is None

            if alive:
                incr_status_fn(run_id, udid, path)
                continue

            if proc is None and not os.path.exists(path):
                continue

            cases = load_jsonl_fn(path)
            crashed = proc is not None and proc.returncode not in (0, None)
            expected_total = ((device_totals or {}).get(udid) or {}).get("total")
            partial = bool(cases) and expected_total is not None and len(cases) < expected_total

            if cases:
                results[udid] = cases
                pending.discard(udid)
                stat = {
                    "done": len(cases),
                    "pass": sum(1 for c in cases if c.get("passed")),
                    "fail": sum(1 for c in cases if not c.get("passed")),
                }
                if crashed or partial:
                    tail = tail_file_fn(agent_log_path_fn(udid))
                    reason = (f"进程异常退出(code={proc.returncode})"
                              if crashed else
                              f"进程提前退出(code={proc.returncode})，仅落盘 {len(cases)}/{expected_total} 条结果")
                    log.warning(f"{udid} {reason}，保留已落盘 {len(cases)} 条结果，其余判未执行。日志末尾：{tail}")
                    if run_id:
                        run_status_module.update_device(run_id, udid, state="crashed", **stat)
                    if app_id and version:
                        notify_fn(
                            app_id, version,
                            f"⚠️ 设备 {udid} {reason}，已保留 {len(cases)} 条结果，其余判未执行。日志末尾：{tail}",
                        )
                else:
                    log.info(f"{udid} done, {len(cases)} results read")
                    if run_id:
                        run_status_module.update_device(run_id, udid, state="done", **stat)
                continue

            if proc is not None:
                tail = tail_file_fn(agent_log_path_fn(udid))
                log.warning(f"{udid} 进程已退出(code={proc.returncode})却无结果，判失败。日志末尾：{tail}")
                results[udid] = "failed"
                pending.discard(udid)
                if run_id:
                    run_status_module.update_device(run_id, udid, state="crashed")
                if app_id and version:
                    notify_fn(
                        app_id, version,
                        f"⚠️ 设备 {udid} 执行进程异常退出(code={proc.returncode})，已判失败。日志末尾：{tail}",
                    )
        if pending:
            time.sleep(poll_interval)

    for udid in pending:
        log.warning(f"{udid} timeout, killing")
        proc = procs.get(udid)
        if proc and proc.poll() is None:
            proc.kill()
        results[udid] = "timeout"
        if run_id:
            run_status_module.update_device(run_id, udid, state="timeout")
        if app_id and version:
            notify_fn(app_id, version, f"⚠️ 设备 {udid} 执行超时({timeout // 60}分钟)，已终止")

    return results


def generate_reports(
    app_id: str,
    version: str,
    results: dict,
    duration: int,
    project_root: str,
    lowconf_review_steps_fn,
    write_results_to_table_fn,
    notify_fn,
    subprocess_module,
    log,
    start_time_str: str = None,
    device_totals: dict = None,
    interrupted: bool = False,
    write_tables: bool = True,
):
    start_time = start_time_str or datetime.datetime.now().strftime("%H:%M:%S")
    script = os.path.join(project_root, "scripts", "wiki_report.py")

    android_cases, ios_cases = [], []
    for _, data in results.items():
        if data in ("timeout", "failed"):
            continue
        for case in (data if isinstance(data, list) else []):
            if version:
                case.setdefault("app_version", version)
            platform = case.get("platform", "").lower()
            if platform == "android":
                android_cases.append(case)
            elif platform == "ios":
                ios_cases.append(case)

    planned = {"Android": 0, "iOS": 0}
    if device_totals:
        for info in device_totals.values():
            plat = "Android" if str(info.get("platform", "")).lower() == "android" else "iOS"
            planned[plat] += info.get("total", 0)

    if write_tables:
        for platform, cases in [("android", android_cases), ("ios", ios_cases)]:
            if cases:
                write_results_to_table_fn(app_id, platform, cases)

    wiki_urls = {}
    for platform, cases in [("Android", android_cases), ("iOS", ios_cases)]:
        if not cases:
            continue
        total = len(cases)
        passed = sum(1 for c in cases if c.get("passed"))
        failed = total - passed
        rate = int(passed / total * 100) if total else 0
        result = subprocess_module.run(
            ["python3", script,
             "--app", app_id, "--version", version,
             "--platform", platform,
             "--time", start_time, "--duration", f"{duration}s",
             "--total", str(total), "--passed", str(passed),
             "--failed", str(failed), "--rate", str(rate),
             "--cases", json.dumps(cases, ensure_ascii=False),
             "--no-notify"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if "Wiki 报告已创建" in line:
                url = line.split("：")[-1].strip()
                wiki_urls[platform] = url
                log.info(line)

    prefix = "⚠️ 执行中断，部分结果\n" if interrupted else ""
    head = "自动化测试中断" if interrupted else "自动化测试完成"
    lines = [f"{prefix}📱 {app_id} {version} {head}\n"]
    for platform, cases in [("Android", android_cases), ("iOS", ios_cases)]:
        plan = planned.get(platform, 0)
        if not cases and not plan:
            continue
        done = len(cases)
        passed = sum(1 for c in cases if c.get("passed"))
        denom = plan or done
        rate = int(passed / done * 100) if done else 0
        unexec = max(0, plan - done)
        url = wiki_urls.get(platform, "")
        review = sum(1 for c in cases if c.get("passed") and lowconf_review_steps_fn(c))
        parts = [f"{platform}：{passed}/{denom} 通过 ({rate}%)"]
        if unexec:
            parts.append(f"{unexec} 未执行")
        if review:
            parts.append(f"⚠️{review}条待复核")
        # 脚本命中率:有脚本的用例中,脚本直接跑完(未回退 agent)的占比。
        # 低命中 = 固化脚本没在稳定,需回头修脚本定位/时序。exec_source 由执行层打标。
        scripted = [c for c in cases if c.get("exec_source") in ("script", "script_fallback")]
        if scripted:
            via_script = sum(1 for c in scripted if c.get("exec_source") == "script")
            fell_back = len(scripted) - via_script
            hit_rate = int(via_script / len(scripted) * 100)
            seg_script = f"脚本命中 {via_script}/{len(scripted)} ({hit_rate}%)"
            if fell_back:
                seg_script += f"，回退 {fell_back}"
            parts.append(seg_script)
        seg = "，".join(parts)
        if url:
            seg += f"  📄 {url}"
        lines.append(seg)
    lines.append(f"\n总耗时：{duration // 60}分{duration % 60}秒")
    notify_fn(app_id, version, "\n".join(lines))


def read_partial_results(udids, load_jsonl_fn, result_dir: str = "/tmp") -> dict:
    out = {}
    for udid in udids:
        cases = load_jsonl_fn(os.path.join(result_dir, f"result_{udid}.jsonl"))
        if cases:
            out[udid] = cases
    return out


def finalize(
    inflight: dict,
    finalized: bool,
    run_status_module,
    generate_reports_fn,
    read_partial_results_fn,
    log,
    reason: str = None,
    results: dict = None,
    write_tables: bool = None,
):
    if finalized or not inflight:
        return False, finalized
    finalized = True
    run_id = inflight["run_id"]
    device_totals = inflight["device_totals"]
    result_dir = inflight.get("result_dir", "/tmp")
    if write_tables is None:
        write_tables = inflight.get("write_tables", True)
    if results is None:
        results = read_partial_results_fn(list(device_totals.keys()), result_dir)
    duration = int(time.time() - inflight["start_time"])
    try:
        run_status_module.set_phase(
            run_id, "reporting",
            "执行中断，生成部分报告" if reason else "生成报告",
        )
        generate_reports_fn(
            inflight["app_id"], inflight["version"], results, duration,
            start_time_str=inflight["start_time_str"],
            device_totals=device_totals,
            interrupted=bool(reason),
            write_tables=write_tables,
        )
    except Exception as exc:
        log.exception(f"finalize 生成报告失败：{exc}")
    finally:
        for udid in device_totals:
            path = os.path.join(result_dir, f"result_{udid}.jsonl")
            if os.path.exists(path):
                os.remove(path)
        passed = sum(
            1 for data in results.values() if isinstance(data, list)
            for case in data if case.get("passed")
        )
        total = sum(value.get("total", 0) for value in device_totals.values())
        run_status_module.finish(
            run_id,
            "interrupted" if reason else "done",
            reason or "执行完成",
            total=total,
            passed=passed,
            duration=duration,
        )
    return True, finalized
