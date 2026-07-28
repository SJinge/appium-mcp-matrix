import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

from orch_case_runtime import is_write_action


def page_matches_target(page_source: str, target: str) -> bool:
    if not page_source or not target:
        return False
    checks = {
        "home": (("首页",), ("发现",)),
        "my_tab": (("我的", "点击登录"), ("我的", "登录")),
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


def _wda_request(port: int, method: str, path: str, payload: dict = None, timeout: int = 30):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8") or "{}"
    return json.loads(body)


def _create_session(port: int, bundle_id: str):
    payloads = [
        {"capabilities": {"alwaysMatch": {"bundleId": bundle_id}, "firstMatch": [{}]}},
        {"desiredCapabilities": {"bundleId": bundle_id}},
    ]
    for payload in payloads:
        try:
            body = _wda_request(port, "POST", "/session", payload=payload, timeout=60)
        except Exception:
            continue
        session_id = body.get("sessionId") or ((body.get("value") or {}).get("sessionId"))
        if session_id:
            return session_id
    return ""


def _delete_session(port: int, session_id: str) -> bool:
    if not session_id:
        return True
    try:
        _wda_request(port, "DELETE", f"/session/{session_id}", timeout=15)
        return True
    except Exception:
        return False


def _alert_text(port: int, session_id: str) -> str:
    """当前系统 alert 文案；无 alert 时 WDA 返回 404，捕获后回空串。"""
    try:
        body = _wda_request(port, "GET", f"/session/{session_id}/alert/text", timeout=10)
    except Exception:
        return ""
    value = body.get("value")
    return value if isinstance(value, str) else ""


def _accept_alert(port: int, session_id: str, button_name: str = None) -> bool:
    """接受系统 alert。button_name 指定按钮(如"无线局域网与蜂窝网络");
    指定失败则退回默认 accept(点默认按钮)。"""
    payload = {"name": button_name} if button_name else {}
    try:
        _wda_request(port, "POST", f"/session/{session_id}/alert/accept", payload=payload, timeout=10)
        return True
    except Exception:
        if not button_name:
            return False
        try:
            _wda_request(port, "POST", f"/session/{session_id}/alert/accept", payload={}, timeout=10)
            return True
        except Exception:
            return False


def _get_source(port: int, session_id: str) -> str:
    body = _wda_request(port, "GET", f"/session/{session_id}/source", timeout=30)
    value = body.get("value", "")
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _get_screenshot(port: int, session_id: str) -> bytes:
    body = _wda_request(port, "GET", f"/session/{session_id}/screenshot", timeout=30)
    encoded = body.get("value") if isinstance(body, dict) else ""
    return base64.b64decode(encoded) if encoded else b""


def _safe_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return label.strip("_")[:80] or "assert_ui"


def _map_locator(by: str, value: str):
    if by in {"id", "accessibility_id"}:
        return "accessibility id", value
    if by == "xpath":
        return "xpath", value
    if by == "predicate":
        return "-ios predicate string", value
    if by == "text":
        return "xpath", f'//*[@label="{value}" or @name="{value}" or @value="{value}"]'
    if by == "name":
        return "xpath", f'//*[@name="{value}"]'
    if by == "label":
        return "xpath", f'//*[@label="{value}"]'
    return "", ""


def _find_element(port: int, session_id: str, by: str, value: str):
    using, mapped = _map_locator(by, value)
    if not using or not mapped:
        return ""
    body = _wda_request(
        port,
        "POST",
        f"/session/{session_id}/element",
        payload={"using": using, "value": mapped},
        timeout=30,
    )
    val = body.get("value") or {}
    return val.get("ELEMENT") or val.get("element-6066-11e4-a52e-4f735466cecf") or ""


def _click_element(port: int, session_id: str, element_id: str) -> bool:
    if not element_id:
        return False
    _wda_request(port, "POST", f"/session/{session_id}/element/{element_id}/click", payload={}, timeout=15)
    return True


def _input_element(port: int, session_id: str, element_id: str, text: str) -> bool:
    if not element_id:
        return False
    payload = {"text": text, "value": list(text)}
    _wda_request(port, "POST", f"/session/{session_id}/element/{element_id}/value", payload=payload, timeout=30)
    return True


def _tap_with_locator(port: int, session_id: str, step: dict) -> bool:
    locators = [{"by": step.get("by"), "value": step.get("value")}]
    for fallback in step.get("fallbacks") or []:
        if isinstance(fallback, dict):
            locators.append({"by": fallback.get("by"), "value": fallback.get("value")})
    for locator in locators:
        element_id = _find_element(port, session_id, locator.get("by"), locator.get("value"))
        if element_id:
            return _click_element(port, session_id, element_id)
    return False


def _known_dialog_action_text(source: str, known_dialog_text_actions) -> str:
    if not source:
        return ""
    if "无线数据" in source or "无线局域网与蜂窝网络" in source:
        return "无线局域网与蜂窝网络"
    for marker, action_text in known_dialog_text_actions:
        if marker in source:
            return action_text
    return ""


def script_runtime_context(
    udid: str,
    port: int,
    bundle_id: str,
    assert_evidence_present_fn,
    run_prepare_state_fn,
    run_flow_fn,
    known_dialog_text_actions,
    recover_transport_fn=None,
) -> dict:
    page_source = {"value": None}
    session = {"id": ""}

    def ensure_session() -> bool:
        if session["id"]:
            return True
        session["id"] = _create_session(port, bundle_id)
        return bool(session["id"])

    def read_page_source(force_refresh: bool = False) -> str:
        if page_source["value"] is not None and not force_refresh:
            return page_source["value"]
        if not ensure_session():
            page_source["value"] = ""
            return page_source["value"]
        try:
            page_source["value"] = _get_source(port, session["id"])
        except Exception:
            page_source["value"] = ""
        return page_source["value"]

    def invalidate_state() -> bool:
        page_source["value"] = None
        session["id"] = ""
        return True

    def capture_screenshot(step: dict = None) -> str:
        if not ensure_session():
            return ""
        label = _safe_label((step or {}).get("text", "assert_ui"))
        shot_dir = os.path.join("/tmp", "script_ui_checkpoints", udid)
        os.makedirs(shot_dir, exist_ok=True)
        path = os.path.join(shot_dir, f"{int(time.time() * 1000)}_{label}.png")
        try:
            data = _get_screenshot(port, session["id"])
        except Exception:
            return ""
        if not data:
            return ""
        with open(path, "wb") as f:
            f.write(data)
        return path

    def recover_transport() -> bool:
        invalidate_state()
        if not callable(recover_transport_fn):
            return False
        try:
            return bool(recover_transport_fn())
        except Exception:
            return False

    def assert_evidence_present(verify_method: str, evidence: str) -> bool:
        return assert_evidence_present_fn(runtime, verify_method, evidence)

    def prepare_state(step: dict) -> bool:
        if not ensure_session():
            return False
        return run_prepare_state_fn(udid, step, runtime)

    def route(step: dict) -> bool:
        page_source["value"] = None
        return ensure_session()

    def tap(step: dict) -> bool:
        write_action = is_write_action(step)
        for attempt in range(2):
            if not ensure_session():
                if attempt == 0 and recover_transport():
                    continue
                return False
            before = read_page_source(force_refresh=True)
            try:
                clicked = _tap_with_locator(port, session["id"], step)
            except Exception:
                clicked = False
            if not clicked:
                if attempt == 0 and recover_transport():
                    continue
                return False
            # 导航/幂等类点击:点后 UI 无变化(常见 WDA click 返回 200 但界面未动)则重放该点击,
            # 最多 2 次;写操作(提交/下单/支付…)不重放,防重复写线上数据。
            if not write_action:
                for _ in range(2):
                    time.sleep(1)
                    after = read_page_source(force_refresh=True)
                    if after and after != before:
                        break
                    try:
                        if not _tap_with_locator(port, session["id"], step):
                            break
                    except Exception:
                        break
            return True
        return False

    def tap_text(text: str) -> bool:
        if not ensure_session():
            return False
        try:
            element_id = _find_element(port, session["id"], "text", text)
            return _click_element(port, session["id"], element_id) if element_id else False
        except Exception:
            return False

    def input_text(step: dict) -> bool:
        if not ensure_session():
            return False
        try:
            element_id = ""
            locators = [{"by": step.get("by"), "value": step.get("value")}]
            for fallback in step.get("fallbacks") or []:
                if isinstance(fallback, dict):
                    locators.append({"by": fallback.get("by"), "value": fallback.get("value")})
            for locator in locators:
                element_id = _find_element(port, session["id"], locator.get("by"), locator.get("value"))
                if element_id:
                    break
            if not element_id:
                return False
            if not _click_element(port, session["id"], element_id):
                return False
            text = step.get("text", "")
            if text == "":
                return False
            return _input_element(port, session["id"], element_id, text)
        except Exception:
            return False

    def _clear_system_alerts() -> None:
        # iOS 系统权限弹窗(使用无线数据/通知/本地网络/跟踪)在 SpringBoard 层，
        # 不进 app 的 page_source，且盖在最上层拦截点击。必须先用 WDA alert API 清掉，
        # 否则后续 tap 会"假 PASS"(元素在弹窗背后、click 返回 200 但页面不动)。
        for _ in range(5):
            alert = _alert_text(port, session["id"])
            if not alert:
                break
            button = _known_dialog_action_text(alert, known_dialog_text_actions)
            if not _accept_alert(port, session["id"], button or None):
                break
            page_source["value"] = None  # 弹窗已变化，作废 source 缓存

    def dismiss_system_alert(step: dict = None) -> bool:
        # 幂等的系统 alert 清除 step:重装/冷启后系统网络权限弹窗常盖在隐私弹窗之上，
        # 拦截"同意"点击致首个断言误判(见 memory: ios_startup_network_alert_blocker)。
        # 无弹窗/建 session 失败都视为已就绪返回 True,绝不因它中断整条 FLOW。
        if ensure_session():
            _clear_system_alerts()
        return True

    def handle_known_dialogs(step: dict) -> bool:
        if ensure_session():
            _clear_system_alerts()
        source = read_page_source(force_refresh=True)
        action_text = _known_dialog_action_text(source, known_dialog_text_actions)
        if action_text and not tap_text(action_text):
            return False
        if action_text:
            source = read_page_source(force_refresh=True)
        if "学习阶段" in source and "进入首页" in source:
            if not tap_text("进入首页"):
                return False
        return True

    def close() -> bool:
        ok = _delete_session(port, session["id"])
        session["id"] = ""
        return ok

    runtime = {"assert_evidence_present": assert_evidence_present}
    runtime["route"] = route
    runtime["prepare_state"] = prepare_state
    runtime["handle_known_dialogs"] = handle_known_dialogs
    runtime["dismiss_system_alert"] = dismiss_system_alert
    runtime["tap"] = tap
    runtime["input"] = input_text
    runtime["tap_text"] = tap_text
    runtime["run_flow"] = lambda meta, flow: run_flow_fn(meta, flow, runtime)
    runtime["read_page_source"] = read_page_source
    runtime["capture_screenshot"] = capture_screenshot
    runtime["invalidate_state"] = invalidate_state
    runtime["close"] = close
    return runtime
