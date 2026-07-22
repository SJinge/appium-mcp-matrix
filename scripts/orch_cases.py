import json
import re

_ACCOUNT_PATTERNS = (
    re.compile(r"账号[:：]?\s*(1\d{10})"),
    re.compile(r"账号为\s*(1\d{10})"),
    re.compile(r"切换账号\s*(1\d{10})"),
    re.compile(r"登录账号\s*(1\d{10})"),
    re.compile(r"使用\s*(1\d{10})\s*登录"),
    re.compile(r"(1\d{10})\s*已登录"),
)
_PER_CASE_STATE_GROUPS = {"启动弹窗"}


def text_field(value) -> str:
    if isinstance(value, list):
        return "".join(item.get("text", "") for item in value)
    return str(value) if value else ""


def case_order_key(value) -> tuple:
    s = text_field(value).strip()
    if not s:
        return (1, ())
    parts = [int(x) if x.isdigit() else x.lower()
             for x in re.findall(r"\d+|[^\d]+", s)]
    return (0, tuple(parts))


def extract_udid(label: str) -> str:
    if not label:
        return ""
    s = label.replace("：", ":")
    return s.rsplit(":", 1)[-1].strip() if ":" in s else label.strip()


def parse_record(record: dict) -> dict:
    fields = record["fields"]
    order = text_field(fields.get("编号", "")).strip()
    num = text_field(fields.get("用例编号", "")).strip()
    name = text_field(fields.get("用例名称", ""))
    page = text_field(fields.get("所属页面", "")).strip()
    state_group = text_field(fields.get("状态组", "")).strip()
    legacy_module = text_field(fields.get("模块", "")).strip()
    steps = []

    for line in text_field(fields.get("预置条件", "")).splitlines():
        line = line.strip()
        if line:
            steps.append({"type": "PRECOND", "text": line})

    for line in text_field(fields.get("测试步骤", "")).splitlines():
        line = line.strip()
        if line:
            steps.append({"type": "ACTION", "text": line})

    for line in text_field(fields.get("验证点", "")).splitlines():
        line = line.strip()
        if line:
            steps.append({"type": "ASSERT", "text": line})

    result_text = text_field(fields.get("预期结果", "")).strip()
    if result_text:
        steps.append({"type": "ASSERT", "text": result_text})

    return {
        "record_id": record["record_id"],
        "name": f"{num} {name}".strip(),
        "order": order,
        "steps": steps,
        "android_device": extract_udid(text_field(fields.get("android执行设备", ""))),
        "ios_device": extract_udid(text_field(fields.get("ios执行设备", ""))),
        "module": page or legacy_module,
        "page": page,
        "state_group": state_group,
    }


def group_by_device(entries: list) -> dict:
    groups = {}
    for entry in entries:
        for platform, field in [("Android", "android_device"), ("iOS", "ios_device")]:
            udid = entry.get(field, "").strip()
            if not udid:
                continue
            if udid not in groups:
                groups[udid] = {"platform": platform, "entries": []}
            groups[udid]["entries"].append(entry)
    return groups


def entry_account_key(entry: dict) -> str:
    precond_text = "\n".join(
        step.get("text", "") for step in entry.get("steps", [])
        if step.get("type") == "PRECOND"
    )
    for pattern in _ACCOUNT_PATTERNS:
        match = pattern.search(precond_text)
        if match:
            return match.group(1)
    if "未登录" in precond_text:
        return "<UNLOGIN>"
    return "<NONE>"


def estimate_entry_prompt_chars(entry: dict) -> int:
    payload = {
        "record_id": entry.get("record_id", ""),
        "name": entry.get("name", ""),
        "module": entry.get("module", ""),
        "steps": entry.get("steps", []),
    }
    return len(json.dumps(payload, ensure_ascii=False))


def build_execution_batches(entries: list, batch_size: int, max_prompt_chars: int) -> list:
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")

    batches = []
    current = []
    current_key = None
    current_prompt_chars = 0
    for entry in entries:
        state_group = entry.get("state_group", "").strip() or "<EMPTY>"
        if state_group in _PER_CASE_STATE_GROUPS:
            if current:
                batches.append(current)
                current = []
                current_key = None
                current_prompt_chars = 0
            batches.append([entry])
            continue

        bucket_key = (state_group, entry_account_key(entry))
        entry_prompt_chars = estimate_entry_prompt_chars(entry)
        would_exceed_context_budget = current and (
            current_prompt_chars + entry_prompt_chars > max_prompt_chars
        )
        if current and (
            bucket_key != current_key
            or len(current) >= batch_size
            or would_exceed_context_budget
        ):
            batches.append(current)
            current = []
            current_prompt_chars = 0
        if not current:
            current_key = bucket_key
        current.append(entry)
        current_prompt_chars += entry_prompt_chars
    if current:
        batches.append(current)
    return batches


def chunk_entries(entries: list, batch_size: int) -> list:
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    return [entries[i:i + batch_size] for i in range(0, len(entries), batch_size)]
