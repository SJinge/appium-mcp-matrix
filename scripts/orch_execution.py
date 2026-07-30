import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed


def batch_result_dir(result_dir: str, udid: str, batch_idx: int) -> str:
    return os.path.join(result_dir, "batch_results", f"batch_{udid}_{batch_idx}")


def batch_result_path(result_dir: str, udid: str, batch_idx: int) -> str:
    return os.path.join(batch_result_dir(result_dir, udid, batch_idx), f"result_{udid}.jsonl")


def batch_account_path(result_dir: str, udid: str, batch_idx: int) -> str:
    return os.path.join(batch_result_dir(result_dir, udid, batch_idx), f"account_{udid}.txt")


def append_jsonl(path: str, cases: list):
    if not cases:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as file_obj:
        for case in cases:
            file_obj.write(json.dumps(case, ensure_ascii=False) + "\n")


def attach_execution_version(cases: list, version: str = None) -> list:
    if not version:
        return cases
    for case in cases:
        case.setdefault("app_version", version)
    return cases


def hydrate_batch_cases(batch_cases: list, entries: list) -> list:
    if not batch_cases:
        return batch_cases

    def merge(case: dict, entry: dict) -> dict:
        case.setdefault("record_id", entry.get("record_id", ""))
        case.setdefault("name", entry.get("name", ""))
        case.setdefault("module", entry.get("module", ""))
        case.setdefault("order", entry.get("order", ""))
        case.setdefault("state_group", entry.get("state_group", ""))
        return case

    indexed_entries = {}
    for idx, entry in enumerate(entries, 1):
        indexed_entries[idx] = entry

    for idx, case in enumerate(batch_cases, 1):
        entry = None
        seq = case.get("seq")
        if isinstance(seq, int) and seq in indexed_entries:
            entry = indexed_entries[seq]
        elif len(batch_cases) == len(entries):
            entry = entries[idx - 1]
        elif idx <= len(entries):
            entry = entries[idx - 1]
        if entry:
            merge(case, entry)
    return batch_cases


def select_legacy_batch_cases(legacy_cases: list, entries: list, already_done: int = 0) -> list:
    if not legacy_cases:
        return []
    record_ids = {entry.get("record_id") for entry in entries if entry.get("record_id")}
    if record_ids:
        matched = [case for case in legacy_cases if case.get("record_id") in record_ids]
        if matched:
            return matched
    if len(legacy_cases) == len(entries):
        return legacy_cases
    if len(legacy_cases) > already_done:
        return legacy_cases[already_done:already_done + len(entries)]
    return []


def load_batch_cases_with_legacy(
    result_dir: str,
    udid: str,
    batch_idx: int,
    entries: list,
    batch_data,
    already_done: int,
    batch_result_path_fn,
    load_jsonl_fn,
    log,
) -> list:
    batch_cases = load_jsonl_fn(batch_result_path_fn(result_dir, udid, batch_idx))
    if batch_cases:
        return batch_cases
    if isinstance(batch_data, list) and batch_data:
        return batch_data
    legacy_path = os.path.join(result_dir, f"result_{udid}.jsonl")
    legacy_cases = select_legacy_batch_cases(load_jsonl_fn(legacy_path), entries, already_done)
    if legacy_cases:
        log.warning(
            f"{udid} batch {batch_idx + 1} 未写入批结果文件，"
            f"已从 legacy 结果文件兜底读取 {len(legacy_cases)} 条: {legacy_path}"
        )
    return legacy_cases


def launch_agent_per_device(
    app_id: str,
    groups: dict,
    build_prompt_fn,
    build_agent_command_fn,
    resolve_agent_runner_fn,
    agent_log_path_fn,
    project_root: str,
    log,
    wda_ports: dict = None,
    version: str = None,
) -> dict:
    runner = resolve_agent_runner_fn()
    wda_ports = wda_ports or {}
    procs = {}
    skill_dir = os.path.join(project_root, ".claude", "skills", app_id)
    common_dir = os.path.join(project_root, "common")

    for udid, group in groups.items():
        prompt = build_prompt_fn(
            app_id, udid, group["platform"], group["entries"],
            wda_port=wda_ports.get(udid), version=version,
        )
        log_path = agent_log_path_fn(udid)
        cmd = build_agent_command_fn(runner, prompt, skill_dir, common_dir)
        with open(log_path, "w") as logf:
            proc = subprocess.Popen(cmd, stdout=logf, stderr=logf)
        procs[udid] = proc
        log.info(f"Launched {group['platform']} {udid} (pid={proc.pid})")
    return procs


def launch_agent_batch(
    app_id: str,
    udid: str,
    platform: str,
    entries: list,
    build_prompt_fn,
    build_agent_command_fn,
    resolve_agent_runner_fn,
    agent_log_path_fn,
    batch_result_dir_fn,
    batch_result_path_fn,
    batch_account_path_fn,
    project_root: str,
    log,
    wda_port: int = None,
    version: str = None,
    current_account: str = "",
    batch_idx: int = 0,
    batch_count: int = 1,
    is_last_batch: bool = True,
    result_dir: str = "/tmp",
):
    runner = resolve_agent_runner_fn()
    skill_dir = os.path.join(project_root, ".claude", "skills", app_id)
    common_dir = os.path.join(project_root, "common")
    batch_dir = batch_result_dir_fn(result_dir, udid, batch_idx)
    os.makedirs(batch_dir, exist_ok=True)
    result_path = batch_result_path_fn(result_dir, udid, batch_idx)
    account_state_path = batch_account_path_fn(result_dir, udid, batch_idx)
    prompt = build_prompt_fn(
        app_id, udid, platform, entries,
        wda_port=wda_port, version=version,
        result_path=result_path, current_account=current_account,
        batch_idx=batch_idx, batch_count=batch_count,
        is_last_batch=is_last_batch,
        account_state_path=account_state_path,
    )
    cmd = build_agent_command_fn(runner, prompt, skill_dir, common_dir)
    log_path = agent_log_path_fn(udid)
    with open(log_path, "a") as logf:
        logf.write(f"\n=== batch {batch_idx + 1}/{batch_count} ===\n")
        proc = subprocess.Popen(cmd, stdout=logf, stderr=logf)
    log.info(f"Launched {platform} {udid} batch {batch_idx + 1}/{batch_count} (pid={proc.pid})")
    return proc


def execute_device_batches(
    app_id: str,
    udid: str,
    group: dict,
    build_execution_batches_fn,
    batch_result_dir_fn,
    batch_result_path_fn,
    batch_account_path_fn,
    find_case_script_fn,
    launch_agent_batch_fn,
    collect_results_fn,
    load_jsonl_fn,
    hydrate_batch_cases_fn,
    generate_case_script_fn,
    append_jsonl_fn,
    write_results_to_table_fn,
    read_account_state_fn,
    execute_case_with_fallback_fn,
    run_status_module,
    log,
    wda_port: int = None,
    version: str = None,
    run_id: str = None,
    result_dir: str = "/tmp",
    batch_size: int = 1,
    timeout: int = 90 * 60,
) -> list:
    batches = build_execution_batches_fn(group["entries"], batch_size=batch_size)
    aggregate_path = os.path.join(result_dir, f"result_{udid}.jsonl")
    if os.path.exists(aggregate_path):
        os.remove(aggregate_path)

    current_account = ""
    aggregate_cases = []
    total = len(group["entries"])

    for batch_idx, batch in enumerate(batches):
        batch_dir = batch_result_dir_fn(result_dir, udid, batch_idx)
        shutil.rmtree(batch_dir, ignore_errors=True)
        os.makedirs(batch_dir, exist_ok=True)
        if run_id:
            run_status_module.update_device(run_id, udid, **{
                "state": "running",
                "total": total,
                "done": len(aggregate_cases),
                "pass": sum(1 for c in aggregate_cases if c.get("passed")),
                "fail": sum(1 for c in aggregate_cases if not c.get("passed")),
                "platform": group["platform"],
            })
        script_entries = [
            entry for entry in batch
            if entry.get("record_id")
            and find_case_script_fn(app_id, group["platform"].lower(), entry["record_id"])
        ]
        if not script_entries:
            proc = launch_agent_batch_fn(
                app_id, udid, group["platform"], batch,
                wda_port=wda_port, version=version,
                current_account=current_account,
                batch_idx=batch_idx, batch_count=len(batches),
                is_last_batch=(batch_idx == len(batches) - 1),
                result_dir=result_dir,
            )
            batch_results = collect_results_fn(
                {udid: proc},
                result_dir=batch_dir,
                timeout=timeout,
                app_id=app_id,
                version=version,
                poll_interval=10,
                device_totals={udid: {"total": len(batch), "platform": group["platform"]}},
            )
            batch_data = batch_results.get(udid)
            batch_cases = load_batch_cases_with_legacy(
                result_dir=result_dir,
                udid=udid,
                batch_idx=batch_idx,
                entries=batch,
                batch_data=batch_data,
                already_done=len(aggregate_cases),
                batch_result_path_fn=batch_result_path_fn,
                load_jsonl_fn=load_jsonl_fn,
                log=log,
            )
            if batch_cases:
                batch_cases = hydrate_batch_cases_fn(batch_cases, batch)
                attach_execution_version(batch_cases, version)
                for case in batch_cases:
                    if case.get("passed"):
                        generate_case_script_fn(app_id, group["platform"].lower(), case)
                append_jsonl_fn(aggregate_path, batch_cases)
                aggregate_cases.extend(batch_cases)
                if batch_cases:
                    write_results_to_table_fn(app_id, group["platform"].lower(), batch_cases)
                current_account = read_account_state_fn(
                    batch_account_path_fn(result_dir, udid, batch_idx)
                ) or current_account
            else:
                if run_id:
                    run_status_module.update_device(run_id, udid, **{
                        "state": "timeout" if batch_data == "timeout" else "crashed",
                        "total": total,
                        "done": len(aggregate_cases),
                        "pass": sum(1 for c in aggregate_cases if c.get("passed")),
                        "fail": sum(1 for c in aggregate_cases if not c.get("passed")),
                        "platform": group["platform"],
                    })
                return aggregate_cases if aggregate_cases else batch_data
            continue

        batch_cases = []
        for entry in batch:
            result = execute_case_with_fallback_fn(
                app_id=app_id,
                platform=group["platform"].lower(),
                udid=udid,
                entry=entry,
                version=version,
                current_account=current_account,
                wda_port=wda_port,
                result_dir=result_dir,
                timeout=timeout,
            )
            current_account = result.pop("_current_account", current_account) or current_account
            batch_cases.append(result)
        attach_execution_version(batch_cases, version)
        append_jsonl_fn(aggregate_path, batch_cases)
        aggregate_cases.extend(batch_cases)
        if batch_cases:
            write_results_to_table_fn(app_id, group["platform"].lower(), batch_cases)

    if run_id:
        run_status_module.update_device(run_id, udid, **{
            "state": "done",
            "total": total,
            "done": len(aggregate_cases),
            "pass": sum(1 for c in aggregate_cases if c.get("passed")),
            "fail": sum(1 for c in aggregate_cases if not c.get("passed")),
            "platform": group["platform"],
        })
    return aggregate_cases


def execute_batches_for_groups(
    app_id: str,
    groups: dict,
    execute_device_batches_fn,
    resolve_max_concurrent_agent_procs_fn,
    wda_ports: dict = None,
    version: str = None,
    run_id: str = None,
    result_dir: str = "/tmp",
    batch_size: int = 1,
) -> dict:
    wda_ports = wda_ports or {}
    results = {}
    max_workers = max(1, min(len(groups), resolve_max_concurrent_agent_procs_fn()))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                execute_device_batches_fn,
                app_id, udid, group,
                wda_port=wda_ports.get(udid),
                version=version, run_id=run_id,
                result_dir=result_dir, batch_size=batch_size,
            ): udid
            for udid, group in groups.items()
        }
        for future in as_completed(future_map):
            results[future_map[future]] = future.result()
    return results
