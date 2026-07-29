import re
from typing import Optional


_TOAST_ASSERT_PATTERNS = (
    re.compile(r"\[TOAST\]", re.IGNORECASE),
    re.compile(r"\btoast\b", re.IGNORECASE),
    re.compile(r"\bsnackbar\b", re.IGNORECASE),
    re.compile(r"提示"),
)

_EVIDENCE_PREFIX_PATTERNS = (
    re.compile(r"^(实际标题|实际文案包含|文案含|文案|提示|按钮|标题|页面标题|页面文本|菜单文本|命中文案|链路实测|WebView 标题|协议链接文案|按钮文本|tv_label)\s*[：:]\s*"),
    re.compile(r"^(实际文案包含|文案含|文案|提示|按钮|标题|页面标题|页面文本|菜单文本|命中文案|协议链接文案|按钮文本)\s*"),
    # 英文脚手架前缀（agent 常把断言写成 "page_source contains X, buttons Y, links Z"
    # 这类自然语言描述）——逐词剥离，直到剩下真正的屏幕文案 token。
    re.compile(
        r"^(?:page[\s_]?source\s+contains|contains|visible|shows?|displays?|"
        r"includes?|page\s+title|title|buttons?|links?|labels?|texts?|elements?)\b[\s:：,，]*",
        re.IGNORECASE,
    ),
)

# 分隔符：中英文标点 + 英文连接词短语（and / after clicking … 等）。
# agent 用逗号/斜杠/"and"/"after clicking" 串联多个断言点，需全部切开成独立 token。
_EVIDENCE_SPLIT_PATTERN = re.compile(
    r"[；;|/、,，\n]+"
    r"|\s+(?:and|with|plus|including|includes?|"
    r"after\s+clicking|after\s+tapping|after)\s+",
    re.IGNORECASE,
)

_REINSTALL_PRECOND_PATTERNS = (
    re.compile(r"卸载重装"),
    re.compile(r"重新安装"),
    re.compile(r"首次安装"),
    re.compile(r"首次启动"),
    re.compile(r"刚重装"),
)

_STEP_INDEX_PATTERN = re.compile(r"^\s*(\d+)\s*[.、．]")

_ANDROID_AUTO_DIALOG_IDS = {
    "com.android.permissioncontroller:id/permission_allow_button",
    "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
    "com.android.permissioncontroller:id/permission_allow_one_time_button",
}


def step_passed(step: dict, default: bool = False) -> bool:
    if "passed" in step:
        return bool(step.get("passed"))
    if "pass" in step:
        return bool(step.get("pass"))
    return default


def passed_assert_steps(case: dict) -> list:
    return [
        step for step in case.get("steps", [])
        if step.get("type") == "ASSERT"
        and step_passed(step, True)
        and step.get("verify_method") in {"id", "text"}
        and step.get("confidence") == "high"
        and step.get("evidence")
    ]


def should_generate_case_script(case: dict) -> bool:
    return bool(case.get("passed") and passed_assert_steps(case))


def is_toast_like_assert(step: dict) -> bool:
    if step.get("verify_method") != "text":
        return False
    text = step.get("text", "") or ""
    evidence = step.get("evidence", "") or ""
    haystack = f"{text}\n{evidence}"
    return any(pattern.search(haystack) for pattern in _TOAST_ASSERT_PATTERNS)


def normalize_evidence_token(token: str) -> str:
    text = (token or "").strip()
    # 循环剥离脚手架前缀，一个 token 可能带多层（如 "visible buttons 同意"）。
    while True:
        stripped = text
        for pattern in _EVIDENCE_PREFIX_PATTERNS:
            stripped = pattern.sub("", stripped)
        stripped = stripped.strip("`\"'「」『』（）() ")
        if stripped == text:
            break
        text = stripped
    return text.strip("`\"'「」『』（）() ")


def _is_scaffold_only_token(token: str) -> bool:
    """判断 token 是否为纯英文脚手架残渣（如 'login agreement text'），应丢弃。
    含中文 / 《》书名号 / 下划线或 :id/ 的 token(真实 ax-id 如 logo_gaotu)一律保留。"""
    text = (token or "").strip()
    if not text:
        return True
    if re.search(r"[一-鿿]", text):
        return False
    if any(mark in text for mark in ("《", "》", "「", "」")):
        return False
    if "_" in text or ":id/" in text or "/id/" in text:
        return False
    # 纯 ASCII：多词英文短语视为脚手架残渣丢弃；单个英文词(可能是真实按钮名)保留。
    return len(text.split()) >= 2


def split_evidence_tokens(evidence: str) -> list:
    raw_tokens = _EVIDENCE_SPLIT_PATTERN.split(evidence or "")
    tokens = [normalize_evidence_token(token) for token in raw_tokens]
    return [token for token in tokens if token and not _is_scaffold_only_token(token)]


def infer_locator_strategy(value: str, platform: str = "") -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith("//") or text.startswith("("):
        return "xpath"
    if text.startswith("predicate="):
        return "predicate"
    if text.startswith("name="):
        return "name"
    if text.startswith("label="):
        return "label"
    if text.startswith("accessibility_id="):
        return "accessibility_id"
    if platform.lower() == "android" and (":id/" in text or "/id/" in text):
        return "id"
    if platform.lower() == "ios":
        return "accessibility_id"
    return "text"


def normalize_android_route_value(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    package_match = re.search(r"appPackage\s*=\s*([^,\s]+)", text, re.IGNORECASE)
    activity_match = re.search(r"appActivity\s*=\s*([^,\s]+)", text, re.IGNORECASE)
    if not package_match or not activity_match:
        return text
    package_name = package_match.group(1).strip()
    activity_name = activity_match.group(1).strip()
    if activity_name.startswith("."):
        return f"{package_name}/{activity_name}"
    if "/" in activity_name:
        return activity_name
    return f"{package_name}/{activity_name}"


def normalize_flow_locator(locator, text_field, platform: str = "") -> dict:
    if isinstance(locator, dict):
        explicit_by = ""
        if "name" in locator and locator.get("name"):
            explicit_by = "name"
        elif "label" in locator and locator.get("label"):
            explicit_by = "label"
        elif "id" in locator and locator.get("id"):
            explicit_by = "id"
        elif "text" in locator and locator.get("text"):
            explicit_by = "text"
        by = (
            locator.get("by")
            or locator.get("strategy")
            or locator.get("using")
            or explicit_by
            or ""
        )
        value = (
            locator.get("value")
            or locator.get("selector")
            or locator.get("text")
            or locator.get("id")
            or locator.get("name")
            or locator.get("label")
            or ""
        )
        if not by and value:
            by = infer_locator_strategy(value, platform)
            if by in {"predicate", "name", "label", "accessibility_id"} and "=" in value:
                value = value.split("=", 1)[1]
        return {"by": by, "value": value}
    text = text_field(locator).strip()
    if not text:
        return {}
    match = re.match(r"by=([^,]+),\s*value=(.+)", text)
    if match:
        return {"by": match.group(1).strip(), "value": match.group(2).strip()}
    by = infer_locator_strategy(text, platform)
    if by in {"predicate", "name", "label", "accessibility_id"} and "=" in text:
        text = text.split("=", 1)[1]
    return {"by": by, "value": text}


def normalize_flow_fallbacks(fallbacks, text_field, platform: str = "") -> list:
    normalized = []
    for item in fallbacks or []:
        flow_locator = normalize_flow_locator(item, text_field, platform)
        if flow_locator:
            normalized.append(flow_locator)
    return normalized


def is_auto_handled_locator(locator: dict, platform: str = "") -> bool:
    if platform.lower() != "android":
        return False
    if locator.get("by") != "id":
        return False
    return (locator.get("value") or "").strip() in _ANDROID_AUTO_DIALOG_IDS


def flow_step_from_action(step: dict, text_field, platform: str = "") -> dict:
    locator = normalize_flow_locator(step.get("locator"), text_field, platform)
    action_type = step.get("script_action")
    if not action_type or not locator:
        return {}
    if action_type == "tap" and is_auto_handled_locator(locator, platform):
        return {}
    if action_type == "route" and platform.lower() == "android":
        locator["value"] = normalize_android_route_value(locator.get("value"))
    flow_step = {
        "type": action_type,
        "by": locator.get("by"),
        "value": locator.get("value"),
    }
    if step.get("locator_fallbacks"):
        flow_step["fallbacks"] = normalize_flow_fallbacks(
            step.get("locator_fallbacks"), text_field, platform
        )
    if step.get("input_value") is not None:
        flow_step["text"] = step.get("input_value")
    if step.get("secret"):
        flow_step["secret"] = True
    if step.get("clear_first") is not None:
        flow_step["clear_first"] = bool(step.get("clear_first"))
    return {k: v for k, v in flow_step.items() if v not in ("", None, [])}


def sanitize_text_evidence(evidence: str) -> str:
    """把 agent 的自然语言证据("page_source contains 同意, 不同意, …")清洗成
    只含真实屏幕文案的 token，用 ；连接。仅用于 text 断言;id 断言原样保留(切/会毁 resource-id)。"""
    tokens = split_evidence_tokens(evidence)
    return "；".join(tokens) if tokens else (evidence or "")


def flow_step_from_assert(step: dict) -> dict:
    verify_method = step.get("verify_method")
    if verify_method not in {"id", "text"}:
        return {}
    evidence = step.get("evidence")
    if verify_method == "text":
        evidence = sanitize_text_evidence(evidence)
    flow_step = {
        "type": f"assert_{verify_method}",
        "value": evidence,
        "text": step.get("text", ""),
        "soft_assert": is_toast_like_assert(step),
    }
    return {k: v for k, v in flow_step.items() if v not in ("", None, []) and v is not False}


def flow_step_from_aux_text_assert(assert_id_value: str, step: dict) -> dict:
    flow_step = {
        "type": "assert_id",
        "value": assert_id_value,
        "text": step.get("text", ""),
        "aux_text": step.get("evidence", ""),
    }
    return {k: v for k, v in flow_step.items() if v not in ("", None, []) and v is not False}


def is_dialog_like_assert(step: dict) -> bool:
    haystack = f"{step.get('text', '')}\n{step.get('evidence', '')}\n{step.get('page_hint', '')}"
    markers = ("弹窗", "提示", "按钮", "标题", "协议链接", "青少年守护", "隐私弹窗", "温馨提示")
    return any(marker in haystack for marker in markers)


def is_summary_assert(step: dict) -> bool:
    text = step.get("text", "") or ""
    evidence = step.get("evidence", "") or ""
    haystack = f"{text}\n{evidence}"
    return (
        "\n" in text
        or "链路：" in evidence
        or "直接切换为" in haystack
        or "跳转至" in haystack
    )


def _step_locator(step: dict, text_field, platform: str = "") -> dict:
    locator = normalize_flow_locator(step.get("locator"), text_field, platform)
    return locator if locator else {}


def _neighbor_assert_id_value(steps: list, index: int, text_field, platform: str = "") -> str:
    for preferred_action in ("prepare_state", ""):
        for direction in (1, -1):
            seen = 0
            cursor = index + direction
            while 0 <= cursor < len(steps) and seen < 3:
                candidate = steps[cursor]
                cursor += direction
                if candidate.get("type") != "ACTION":
                    continue
                seen += 1
                if preferred_action and candidate.get("script_action") != preferred_action:
                    continue
                locator = _step_locator(candidate, text_field, platform)
                if is_auto_handled_locator(locator, platform):
                    continue
                if locator.get("by") == "id" and locator.get("value"):
                    return locator["value"]
    return ""


def _step_index(step: dict) -> Optional[int]:
    text = (step.get("text") or "").strip()
    match = _STEP_INDEX_PATTERN.match(text)
    return int(match.group(1)) if match else None


def _ordered_case_steps(case: dict) -> list:
    steps = case.get("steps", [])
    actions = [step for step in steps if step.get("type") == "ACTION"]
    asserts = [step for step in steps if step.get("type") == "ASSERT"]
    if not actions or not asserts:
        return steps
    indexed_actions = {_step_index(step): step for step in actions if _step_index(step) is not None}
    indexed_asserts = [step for step in asserts if _step_index(step) is not None]
    if not indexed_actions or not indexed_asserts:
        return steps
    ordered = []
    attached_assert_ids = set()
    for step in steps:
        if step.get("type") == "ASSERT":
            continue
        ordered.append(step)
        if step.get("type") != "ACTION":
            continue
        idx = _step_index(step)
        if idx is None:
            continue
        for assert_step in asserts:
            if id(assert_step) in attached_assert_ids:
                continue
            if _step_index(assert_step) == idx:
                ordered.append(assert_step)
                attached_assert_ids.add(id(assert_step))
    # 无同号 ACTION 的编号断言：按编号插到位——放在第一个"编号更大的 ACTION"之前
    # (即紧跟上一编号动作的现场之后),而不是全部堆到流程末尾造成断言错序。
    unmatched = [a for a in asserts if id(a) not in attached_assert_ids]
    indexed_unmatched = sorted(
        (a for a in unmatched if _step_index(a) is not None), key=_step_index
    )
    for assert_step in indexed_unmatched:
        k = _step_index(assert_step)
        pos = len(ordered)
        for i, candidate in enumerate(ordered):
            if candidate.get("type") == "ACTION":
                idx = _step_index(candidate)
                if idx is not None and idx > k:
                    pos = i
                    break
        ordered.insert(pos, assert_step)
    for assert_step in unmatched:
        if _step_index(assert_step) is None:
            ordered.append(assert_step)
    return ordered


def infer_prepare_state_target(precond_texts: list) -> str:
    joined = "\n".join(precond_texts)
    if "当前在我的tab" in joined or "当前在我的 tab" in joined:
        return "my_tab"
    if "当前在首页" in joined:
        return "home"
    if "当前在上课tab" in joined or "当前在上课 tab" in joined:
        return "class_tab"
    if "当前在登录页" in joined:
        return "login"
    return ""


def needs_reinstall_from_preconditions(precond_texts: list) -> bool:
    joined = "\n".join(precond_texts)
    return any(pattern.search(joined) for pattern in _REINSTALL_PRECOND_PATTERNS)


def prepare_state_from_case(case: dict, entry_account_key) -> dict:
    preconds = [
        step.get("text", "")
        for step in case.get("steps", [])
        if step.get("type") == "PRECOND" and step.get("text")
    ]
    target = infer_prepare_state_target(preconds)
    account = entry_account_key(case)
    if not target and account == "<NONE>":
        return {}
    step = {"type": "prepare_state"}
    if target:
        step["target"] = target
    if account and account != "<NONE>":
        step["account"] = account
    return step


def ui_audit_flow_step(anchor_text: str = "") -> dict:
    return {
        "type": "assert_ui",
        "text": f"UI规范检查：{anchor_text}" if anchor_text else "UI规范检查",
        "scope": "current_screen",
        "rules": ["no_blank", "no_overlap", "no_occlusion", "no_truncation", "safe_area"],
    }


def _insert_dismiss_system_alert_before_first_assert(flow: list) -> None:
    # 冷启(重装)后系统权限弹窗(iOS 使用无线数据/本地网络、Android 权限授权框)会盖在
    # 首启协议/隐私弹窗之上拦截点击,致首个断言误判(见 memory: ios_startup_network_alert_blocker)。
    # 弹窗在 app 拉起(reinstall_app / 首个 route 动作)之后才出现,故插在首个断言前——
    # 此刻 app 必已启动。step 幂等:无弹窗/已授权都安全跳过,不改变其余流程。
    for index, item in enumerate(flow):
        if str(item.get("type", "")).startswith("assert_"):
            flow.insert(index, {
                "type": "dismiss_system_alert",
                "text": "清除系统网络权限弹窗(无则跳过)",
            })
            return


def build_case_flow(case: dict, entry_account_key, text_field, ui_audit_enabled: bool = False) -> list:
    flow = []
    preconds = [
        step.get("text", "")
        for step in case.get("steps", [])
        if step.get("type") == "PRECOND" and step.get("text")
    ]
    did_reinstall = needs_reinstall_from_preconditions(preconds)
    if did_reinstall:
        flow.append({"type": "reinstall_app"})
    prepare_state = prepare_state_from_case(case, entry_account_key)
    if prepare_state:
        flow.append(prepare_state)
    platform = str(case.get("platform", "")).lower()
    ordered_steps = _ordered_case_steps(case)
    for index, step in enumerate(ordered_steps):
        step_type = step.get("type")
        item = {}
        if step_type == "ACTION":
            item = flow_step_from_action(step, text_field, platform)
        elif step_type == "ASSERT" and step_passed(step) and step.get("confidence") == "high":
            if step.get("verify_method") == "text" and is_summary_assert(step):
                continue
            if step.get("verify_method") == "text" and is_dialog_like_assert(step):
                assert_id_value = _neighbor_assert_id_value(ordered_steps, index, text_field, platform)
                if assert_id_value:
                    item = flow_step_from_aux_text_assert(assert_id_value, step)
                else:
                    item = flow_step_from_assert(step)
            else:
                item = flow_step_from_assert(step)
        if item:
            flow.append(item)
            if (
                ui_audit_enabled
                and item.get("type", "").startswith("assert_")
                and item.get("type") != "assert_ui"
                and not item.get("soft_assert")
            ):
                flow.append(ui_audit_flow_step(item.get("text", "")))
    if did_reinstall:
        _insert_dismiss_system_alert_before_first_assert(flow)
    return flow
