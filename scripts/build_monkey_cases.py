#!/usr/bin/env python3
"""
Build cases JSON for wiki_report.py from monkey test anomaly and actions logs.

Usage:
  python3 scripts/build_monkey_cases.py <anomaly_log> <actions_log> <device> <platform>
"""
import json
import sys


def build_cases(anomaly_log_path, actions_log_path, device, platform):
    with open(anomaly_log_path) as f:
        anomalies = json.load(f)
    with open(actions_log_path) as f:
        actions = json.load(f)

    # 去重：同 type + logcat/description 前缀视为同一问题
    seen = {}
    for anomaly in anomalies:
        logcat_key = anomaly.get("logcat", "")[:200]
        desc_key = anomaly.get("description", "")[:80]
        key = f"{anomaly['type']}|{logcat_key if logcat_key else desc_key}"
        if key not in seen:
            seen[key] = dict(anomaly)
            seen[key]["occurrences"] = 1
        else:
            seen[key]["occurrences"] += 1
    anomalies = list(seen.values())

    if not anomalies:
        return [{
            "name": "Monkey Run — 无异常",
            "module": "Monkey",
            "platform": platform,
            "device": device,
            "seq": 1,
            "passed": True,
            "duration": 0,
            "steps": []
        }]

    cases = []
    for i, anomaly in enumerate(anomalies, 1):
        step = anomaly["step"]
        prev_steps = [s for s in actions if s["step"] <= step][-3:]
        path_parts = []
        for s in prev_steps:
            desc = s.get("element_desc", "")
            if desc:
                path_parts.append(f"{s['action']} {desc}")
            else:
                path_parts.append(s["action"])
        trigger_path = anomaly.get("repro_path") or (" → ".join(path_parts) if path_parts else "不明")

        occ = anomaly.get("occurrences", 1)
        occ_suffix = f" ×{occ}台设备" if occ > 1 else ""
        name = f"[step {step}] {anomaly['type']} — {anomaly['description'][:40]}{occ_suffix}"

        cases.append({
            "name": name,
            "module": "Monkey",
            "platform": platform,
            "device": device,
            "seq": i,
            "passed": False,
            "duration": 0,
            "screenshot": anomaly.get("screenshot", ""),
            "timestamp": anomaly.get("timestamp", ""),
            "steps": [{
                "type": "ANOMALY",
                "text": anomaly["description"],
                "pass": False,
                "note": f"触发路径: {trigger_path}"
            }]
        })

    return cases


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(f"Usage: {sys.argv[0]} <anomaly_log> <actions_log> <device> <platform>",
              file=sys.stderr)
        sys.exit(1)

    anomaly_log_path, actions_log_path, device, platform = sys.argv[1:]
    cases = build_cases(anomaly_log_path, actions_log_path, device, platform)
    print(json.dumps(cases, ensure_ascii=False))
