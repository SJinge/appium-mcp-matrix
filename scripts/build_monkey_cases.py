#!/usr/bin/env python3
"""
Build cases JSON for wiki_report.py from monkey test anomaly and actions logs.

Usage:
  python3 scripts/build_monkey_cases.py <anomaly_log> <actions_log> <device> <platform>
"""
import json
import sys


def build_cases(anomaly_log_path, actions_log_path, device, platform):
    anomalies = json.load(open(anomaly_log_path))
    actions = json.load(open(actions_log_path))

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
            desc = s.get("element_desc") or s.get("action", "")
            path_parts.append(f"{s['action']} {desc}".strip())
        trigger_path = " → ".join(path_parts) if path_parts else "不明"

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
