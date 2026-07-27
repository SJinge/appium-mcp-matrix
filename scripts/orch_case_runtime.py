import os
import re
import time


# 会写线上数据的点击(提交/下单/支付…):严禁重放做重试——首次点击服务端可能已成功、
# 仅界面未跳转,重放会重复下单/扣款。这类点击只点一次,不做"点后无变化→重放"。
WRITE_ACTION_KEYWORDS = (
    "提交", "下单", "支付", "付款", "购买", "发送", "确认", "保存", "领取", "结算", "兑换",
)


def is_write_action(step: dict) -> bool:
    parts = [str(step.get("value") or ""), str(step.get("text") or "")]
    for fallback in step.get("fallbacks") or []:
        if isinstance(fallback, dict):
            parts.append(str(fallback.get("value") or ""))
    haystack = " ".join(parts)
    return any(kw in haystack for kw in WRITE_ACTION_KEYWORDS)


def parse_bounds_center(bounds: str):
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not match:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def find_bounds_by_locator(page_source: str, by: str, value: str):
    if not page_source or not by or not value:
        return None
    if by == "id":
        pattern = re.compile(rf'resource-id="{re.escape(value)}"[^>]*bounds="([^"]+)"')
    elif by == "text":
        pattern = re.compile(rf'text="{re.escape(value)}"[^>]*bounds="([^"]+)"')
    elif by == "xpath":
        text_match = re.search(r"@text=['\"]([^'\"]+)['\"]", value)
        desc_match = re.search(r"@content-desc=['\"]([^'\"]+)['\"]", value)
        resource_match = re.search(r"@resource-id=['\"]([^'\"]+)['\"]", value)
        if text_match:
            pattern = re.compile(rf'text="{re.escape(text_match.group(1))}"[^>]*bounds="([^"]+)"')
        elif desc_match:
            pattern = re.compile(rf'content-desc="{re.escape(desc_match.group(1))}"[^>]*bounds="([^"]+)"')
        elif resource_match:
            pattern = re.compile(rf'resource-id="{re.escape(resource_match.group(1))}"[^>]*bounds="([^"]+)"')
        else:
            return None
    else:
        return None
    match = pattern.search(page_source)
    return parse_bounds_center(match.group(1)) if match else None


def adb_tap(udid: str, x: int, y: int, subprocess_module) -> bool:
    try:
        result = subprocess_module.run(
            ["adb", "-s", udid, "shell", "input", "tap", str(x), str(y)],
            capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except subprocess_module.TimeoutExpired:
        return False


def tap_with_locator(
    udid: str,
    step: dict,
    page_source: str,
    find_bounds_by_locator_fn,
    adb_tap_fn,
) -> bool:
    locators = [{"by": step.get("by"), "value": step.get("value")}]
    for fallback in step.get("fallbacks") or []:
        if isinstance(fallback, dict):
            locators.append({"by": fallback.get("by"), "value": fallback.get("value")})
    for locator in locators:
        center = find_bounds_by_locator_fn(page_source, locator.get("by"), locator.get("value"))
        if center:
            return adb_tap_fn(udid, center[0], center[1])
    return False


def tap_by_text(
    udid: str,
    text: str,
    subprocess_module,
    find_bounds_by_locator_fn,
    adb_tap_fn,
) -> bool:
    try:
        source = subprocess_module.run(
            ["adb", "-s", udid, "exec-out", "uiautomator", "dump", "/dev/tty"],
            capture_output=True, text=True, timeout=30
        ).stdout or ""
    except subprocess_module.TimeoutExpired:
        return False
    center = find_bounds_by_locator_fn(source, "text", text)
    return adb_tap_fn(udid, center[0], center[1]) if center else False


def adb_input_text(udid: str, text: str, subprocess_module) -> bool:
    safe_text = str(text).replace(" ", "%s")
    try:
        result = subprocess_module.run(
            ["adb", "-s", udid, "shell", "input", "text", safe_text],
            capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except subprocess_module.TimeoutExpired:
        return False


def resolve_route_component(udid: str, step: dict, subprocess_module) -> str:
    value = str(step.get("value") or "").strip()
    if "/" in value and " " not in value:
        return value
    for fallback in step.get("fallbacks") or []:
        if not isinstance(fallback, dict):
            continue
        candidate = str(fallback.get("value") or "").strip()
        if candidate.startswith("adb shell cmd package resolve-activity --brief "):
            package_name = candidate.rsplit(" ", 1)[-1].strip()
            if not package_name:
                continue
            try:
                result = subprocess_module.run(
                    ["adb", "-s", udid, "shell", "cmd", "package", "resolve-activity", "--brief", package_name],
                    capture_output=True, text=True, timeout=15
                )
            except subprocess_module.TimeoutExpired:
                continue
            if result.returncode != 0:
                continue
            for line in reversed((result.stdout or "").splitlines()):
                resolved = line.strip()
                if "/" in resolved and " " not in resolved:
                    return resolved
    return ""


def adb_route(udid: str, step: dict, subprocess_module) -> bool:
    component = resolve_route_component(udid, step, subprocess_module)
    if not component:
        return False
    try:
        result = subprocess_module.run(
            ["adb", "-s", udid, "shell", "am", "start", "-n", component],
            capture_output=True, text=True, timeout=20
        )
        return result.returncode == 0
    except subprocess_module.TimeoutExpired:
        return False


def page_matches_target(page_source: str, target: str) -> bool:
    if not page_source or not target:
        return False
    checks = {
        "home": (("首页",), ("发现",)),
        "my_tab": (("我的", "点击登录"),),
        "class_tab": (("上课",), ("我的课程",)),
        "login": (("手机号登录",), ("获取验证码",)),
    }
    groups = checks.get(target, ())
    return bool(groups) and any(all(needle in page_source for needle in group) for group in groups)


def run_prepare_state(udid: str, step: dict, runtime: dict, page_matches_target_fn) -> bool:
    target = step.get("target", "")
    if not target:
        return True
    if callable(runtime.get("handle_known_dialogs")) and not runtime["handle_known_dialogs"]({}):
        return False
    source = runtime["read_page_source"](True)
    if page_matches_target_fn(source, target):
        return True
    route_text = {
        "home": "首页",
        "my_tab": "我的",
        "class_tab": "上课",
    }.get(target)
    if route_text and callable(runtime.get("tap_text")):
        if not runtime["tap_text"](route_text):
            return False
        source = runtime["read_page_source"](True)
        if page_matches_target_fn(source, target):
            return True
    return target == "login" and "登录" in source


def _safe_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return label.strip("_")[:80] or "assert_ui"


def run_flow(meta: dict, flow: list, runtime: dict) -> dict:
    results = []
    soft_misses = []
    for item in flow:
        step_type = item.get("type", "")
        if step_type == "assert_ui":
            action_handler = runtime.get(step_type)
            if not callable(action_handler):
                results.append({
                    "type": "ASSERT_UI",
                    "text": item.get("text", step_type),
                    "passed": False,
                    "note": f"unsupported flow step: {step_type}",
                })
                return {
                    "record_id": meta.get("record_id", ""),
                    "name": meta.get("name", ""),
                    "module": meta.get("module", ""),
                    "passed": False,
                    "note": f"unsupported flow step: {step_type}",
                    "steps": results,
                    "script_source": "script",
                }
            raw = action_handler(item)
            if isinstance(raw, dict):
                ok = bool(raw.get("passed"))
                result_step = {
                    "type": "ASSERT_UI",
                    "text": raw.get("text") or item.get("text", step_type),
                    "passed": ok,
                    "verify_method": raw.get("verify_method", "vision"),
                    "evidence": raw.get("evidence", ""),
                    "confidence": raw.get("confidence", "low"),
                    "note": raw.get("note", ""),
                }
                if "checkpoint_index" in raw:
                    result_step["checkpoint_index"] = raw.get("checkpoint_index")
            else:
                ok = bool(raw)
                result_step = {
                    "type": "ASSERT_UI",
                    "text": item.get("text", step_type),
                    "passed": ok,
                    "verify_method": "vision",
                    "evidence": "",
                    "confidence": "low",
                    "note": "" if ok else "assert_ui failed",
                }
            results.append(result_step)
            if not ok:
                return {
                    "record_id": meta.get("record_id", ""),
                    "name": meta.get("name", ""),
                    "module": meta.get("module", ""),
                    "passed": False,
                    "note": result_step.get("note") or "assert_ui failed",
                    "steps": results,
                    "script_source": "script",
                }
            continue
        if step_type.startswith("assert_"):
            verify_method = step_type.split("_", 1)[1]
            refresh_page = runtime.get("read_page_source")
            detail_fn = runtime.get("assert_evidence_detail")
            handle_known_dialogs = runtime.get("handle_known_dialogs")
            ok = False
            detail = {}
            for attempt in range(3):
                if callable(handle_known_dialogs):
                    handle_known_dialogs({})
                if callable(refresh_page):
                    refresh_page(True)
                ok = runtime["assert_evidence_present"](verify_method, item.get("value", ""))
                if callable(detail_fn):
                    detail = detail_fn(verify_method, item.get("value", ""))
                if ok:
                    break
                if attempt < 2:
                    time.sleep(2)
            aux_detail = {}
            aux_text = item.get("aux_text", "")
            if aux_text and callable(detail_fn):
                aux_detail = detail_fn("text", aux_text)
            matched = detail.get("matched") or []
            missing = detail.get("missing") or []
            detail_note = ""
            if missing:
                detail_note = f"matched={matched}; missing={missing}"
            aux_missing = aux_detail.get("missing") or []
            aux_matched = aux_detail.get("matched") or []
            if aux_text:
                aux_note = f"aux_matched={aux_matched}; aux_missing={aux_missing}"
                detail_note = f"{detail_note} | {aux_note}" if detail_note else aux_note
            result_step = {
                "type": "ASSERT",
                "text": item.get("text", ""),
                "passed": ok,
                "verify_method": verify_method,
                "evidence": item.get("value", ""),
                "confidence": "high",
                "soft_assert": bool(item.get("soft_assert")),
                "note": detail_note,
            }
            results.append(result_step)
            if not ok and item.get("soft_assert"):
                soft_misses.append(item.get("text") or item.get("value", ""))
                continue
            if not ok:
                return {
                    "record_id": meta.get("record_id", ""),
                    "name": meta.get("name", ""),
                    "module": meta.get("module", ""),
                    "passed": False,
                    "note": f"script assertion failed: {item.get('value', '')}" + (f" | {detail_note}" if detail_note else ""),
                    "steps": results,
                    "script_source": "script",
                }
            continue

        action_handler = runtime.get(step_type)
        if callable(action_handler):
            ok = bool(action_handler(item))
            results.append({
                "type": step_type.upper(),
                "text": item.get("text", step_type),
                "passed": ok,
                "note": "" if ok else f"{step_type} failed",
            })
            if not ok:
                return {
                    "record_id": meta.get("record_id", ""),
                    "name": meta.get("name", ""),
                    "module": meta.get("module", ""),
                    "passed": False,
                    "note": f"{step_type} failed",
                    "steps": results,
                    "script_source": "script",
                }
            continue

        results.append({
            "type": step_type.upper() or "ACTION",
            "text": item.get("text", step_type),
            "passed": False,
            "note": f"unsupported flow step: {step_type}",
        })
        return {
            "record_id": meta.get("record_id", ""),
            "name": meta.get("name", ""),
            "module": meta.get("module", ""),
            "passed": False,
            "note": f"unsupported flow step: {step_type}",
            "steps": results,
            "script_source": "script",
        }

    return {
        "record_id": meta.get("record_id", ""),
        "name": meta.get("name", ""),
        "module": meta.get("module", ""),
        "passed": True,
        "note": ("toast/snackbar辅助断言未命中：" + "；".join(soft_misses)) if soft_misses else "",
        "steps": results,
        "script_source": "script",
    }


def script_runtime_context(
    udid: str,
    subprocess_module,
    assert_evidence_present_fn,
    run_prepare_state_fn,
    tap_with_locator_fn,
    adb_input_text_fn,
    tap_by_text_fn,
    run_flow_fn,
    known_dialog_text_actions,
) -> dict:
    page_source = {"value": None}
    system_allow_ids = (
        "com.android.permissioncontroller:id/permission_allow_button",
        "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
        "com.android.permissioncontroller:id/permission_allow_one_time_button",
    )

    def read_page_source(force_refresh: bool = False) -> str:
        if page_source["value"] is not None and not force_refresh:
            return page_source["value"]
        try:
            result = subprocess_module.run(
                ["adb", "-s", udid, "exec-out", "uiautomator", "dump", "/dev/tty"],
                capture_output=True, text=True, timeout=30
            )
            page_source["value"] = result.stdout or ""
        except subprocess_module.TimeoutExpired:
            page_source["value"] = ""
        return page_source["value"]

    def invalidate_state() -> bool:
        page_source["value"] = None
        return True

    def capture_screenshot(step: dict = None) -> str:
        label = _safe_label((step or {}).get("text", "assert_ui"))
        shot_dir = os.path.join("/tmp", "script_ui_checkpoints", udid)
        os.makedirs(shot_dir, exist_ok=True)
        path = os.path.join(shot_dir, f"{int(time.time() * 1000)}_{label}.png")
        try:
            result = subprocess_module.run(
                ["adb", "-s", udid, "exec-out", "screencap", "-p"],
                capture_output=True, timeout=30
            )
        except subprocess_module.TimeoutExpired:
            return ""
        if result.returncode != 0 or not result.stdout:
            return ""
        with open(path, "wb") as f:
            f.write(result.stdout)
        return path

    def assert_evidence_present(verify_method: str, evidence: str) -> bool:
        return assert_evidence_present_fn(runtime, verify_method, evidence)

    def assert_evidence_detail(verify_method: str, evidence: str) -> dict:
        detail_fn = runtime.get("_assert_evidence_detail_fn")
        if callable(detail_fn):
            return detail_fn(runtime, verify_method, evidence)
        return {}

    def prepare_state(step: dict) -> bool:
        return run_prepare_state_fn(udid, step, runtime)

    def _tap_system_allow_if_present(source: str) -> bool:
        for resource_id in system_allow_ids:
            center = find_bounds_by_locator(source, "id", resource_id)
            if center and adb_tap(udid, center[0], center[1], subprocess_module):
                return True
        return False

    def handle_known_dialogs(step: dict) -> bool:
        for _ in range(6):
            source = read_page_source(force_refresh=True)
            handled = False
            if _tap_system_allow_if_present(source):
                handled = True
            else:
                for marker, action_text in known_dialog_text_actions:
                    if marker not in source:
                        continue
                    if not tap_by_text_fn(udid, action_text):
                        return False
                    handled = True
                    break
                if not handled and "学习阶段" in source and "进入首页" in source:
                    if not tap_by_text_fn(udid, "进入首页"):
                        return False
                    handled = True
            if not handled:
                break
        return True

    def tap(step: dict) -> bool:
        if not handle_known_dialogs({}):
            return False
        before = read_page_source(force_refresh=True)
        ok = tap_with_locator_fn(udid, step, before)
        if not ok and handle_known_dialogs({}):
            before = read_page_source(force_refresh=True)
            ok = tap_with_locator_fn(udid, step, before)
        if not ok:
            return False
        # 导航/幂等类点击:点后 UI 无变化(动作未生效)则重放该点击,最多 2 次;
        # 写操作(提交/下单/支付…)不重放,防重复写线上数据。
        if not is_write_action(step):
            for _ in range(2):
                time.sleep(1)
                after = read_page_source(force_refresh=True)
                if after and after != before:
                    break
                handle_known_dialogs({})
                if not tap_with_locator_fn(udid, step, read_page_source(force_refresh=True)):
                    break
        return True

    def route(step: dict) -> bool:
        if not handle_known_dialogs({}):
            return False
        ok = adb_route(udid, step, subprocess_module)
        if ok:
            read_page_source(force_refresh=True)
            return handle_known_dialogs({})
        return ok

    def input_text(step: dict) -> bool:
        if not handle_known_dialogs({}):
            return False
        if not tap_with_locator_fn(udid, step, read_page_source(force_refresh=True)):
            if not handle_known_dialogs({}):
                return False
            if not tap_with_locator_fn(udid, step, read_page_source(force_refresh=True)):
                return False
        text = step.get("text", "")
        if text == "":
            return False
        return adb_input_text_fn(udid, text)

    runtime = {"assert_evidence_present": assert_evidence_present}
    runtime["assert_evidence_detail"] = assert_evidence_detail
    runtime["prepare_state"] = prepare_state
    runtime["handle_known_dialogs"] = handle_known_dialogs
    runtime["route"] = route
    runtime["tap"] = tap
    runtime["input"] = input_text
    runtime["tap_text"] = lambda text: tap_by_text_fn(udid, text)
    runtime["run_flow"] = lambda meta, flow: run_flow_fn(meta, flow, runtime)
    runtime["read_page_source"] = read_page_source
    runtime["capture_screenshot"] = capture_screenshot
    runtime["invalidate_state"] = invalidate_state
    return runtime
