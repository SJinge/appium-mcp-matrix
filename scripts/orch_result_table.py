import json
import os
import re
import time
import urllib.parse
import urllib.request


def resolve_obj_token(app_token: str, get_token_fn) -> str:
    url = (f"https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"
           f"?token={app_token}&obj_type=wiki")
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {get_token_fn()}"})
        node = json.load(urllib.request.urlopen(req)).get("data", {}).get("node", {})
        return node.get("obj_token") or app_token
    except Exception:
        return app_token


def upload_bitable_image(parent_obj: str, file_path: str, token: str, log):
    if not file_path or not os.path.exists(file_path):
        return None
    with open(file_path, "rb") as file_obj:
        data = file_obj.read()
    fname = os.path.basename(file_path)
    boundary = "----orchestrateBoundary7MA4YWxkTrZu0gW"

    def field(name, value):
        return (f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{name}"\r\n\r\n{value}\r\n').encode()

    body = (field("file_name", fname) + field("parent_type", "bitable_image")
            + field("parent_node", parent_obj) + field("size", str(len(data)))
            + (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
               f"filename=\"{fname}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
            + data + b"\r\n" + f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
        data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    try:
        resp = json.load(urllib.request.urlopen(req))
        if resp.get("code") == 0:
            return resp["data"]["file_token"]
        log.warning(f"截图上传失败 {fname}: {resp.get('msg')}")
    except Exception as exc:
        log.warning(f"截图上传异常 {fname}: {exc}")
    return None


def lowconf_review_steps(case: dict) -> list:
    return [s for s in case.get("steps", [])
            if s.get("type") == "ASSERT"
            and s.get("verify_method") == "vision"
            and s.get("confidence") == "low"
            and s.get("pass", True)]


def coerce_number_field(value, text_field_fn):
    if isinstance(value, (int, float)):
        return value
    text = text_field_fn(value).strip()
    if not text:
        return ""
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def coerce_datetime_field(value=None, time_fn=time.time):
    if isinstance(value, (int, float)) and value:
        return int(value if value > 10_000_000_000 else value * 1000)
    return int(time_fn() * 1000)


def write_results_to_table(
    app_id: str,
    platform: str,
    cases: list,
    result_tables: dict,
    get_token_fn,
    resolve_obj_token_fn,
    upload_bitable_image_fn,
    coerce_number_field_fn,
    lowconf_review_steps_fn,
    log,
    version: str = None,
):
    cfg = result_tables.get(app_id)
    table_id = cfg.get(platform.lower()) if cfg else None
    if not cfg or not table_id:
        log.warning(f"{app_id} 无 {platform} 结果表配置，跳过写入结果表")
        return

    token = get_token_fn()
    obj_token = resolve_obj_token_fn(cfg["app_token"])

    records = []
    for case in cases:
        failed = [s for s in case.get("steps", []) if not s.get("pass", True)]
        detail = "\n".join(
            f"{i}、[{s.get('type','')}] {s.get('text','')} ❌"
            + (f" 原因：{s['note']}" if s.get("note") else "")
            for i, s in enumerate(failed, 1)
        )
        passed = case.get("passed", True)

        review = lowconf_review_steps_fn(case)
        review_note = ""
        if review:
            review_note = "⚠️ 视觉判定待复核：\n" + "\n".join(
                f"・[{s.get('type','')}] {s.get('text','')}" for s in review)
        case_note = (case.get("note") or "").strip() if not passed else ""
        full_detail = "\n".join(x for x in (detail, case_note, review_note) if x) \
            or ("全部通过" if passed else "")

        fields = {
            "编号": coerce_number_field_fn(case.get("order", "")),
            "执行版本": version or case.get("app_version", ""),
            "执行时间": coerce_datetime_field(case.get("execution_time")),
            "状态组": case.get("state_group", ""),
            "执行设备": case.get("device", ""),
            "用例名称": case.get("name", ""),
            "执行结果": "通过" if passed else "失败",
            "执行详情": full_detail,
        }
        if passed:
            fields["record_id"] = case.get("record_id", "")
        fields = {k: v for k, v in fields.items() if v != ""}

        shots = (case.get("screenshots") or [])[:20]
        tokens = [{"file_token": t} for t in
                  (upload_bitable_image_fn(obj_token, p, token) for p in shots) if t]
        if tokens:
            fields["截图"] = tokens

        records.append({"fields": fields})

    url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps"
           f"/{cfg['app_token']}/tables/{table_id}/records/batch_create")
    written = 0
    for i in range(0, len(records), 100):
        chunk = records[i:i + 100]
        body = json.dumps({"records": chunk}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=utf-8"},
            method="POST")
        try:
            resp = json.load(urllib.request.urlopen(req))
            if resp.get("code") == 0:
                written += len(chunk)
            else:
                log.warning(f"结果表写入失败 code={resp.get('code')} msg={resp.get('msg')}")
        except Exception as exc:
            log.warning(f"结果表写入异常：{exc}")
    log.info(f"{platform} {written}/{len(records)} 条结果已写入结果表")


def clear_result_table(app_id: str, platform: str, result_tables: dict, get_token_fn, log):
    cfg = result_tables.get(app_id)
    table_id = cfg.get(platform.lower()) if cfg else None
    if not cfg or not table_id:
        log.warning(f"{app_id} 无 {platform} 结果表配置，跳过清空")
        return

    token = get_token_fn()
    page_token = ""
    deleted = 0
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps/"
               f"{cfg['app_token']}/tables/{table_id}/records?"
               f"{urllib.parse.urlencode(params)}")
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}"}, method="GET")
        resp = json.load(urllib.request.urlopen(req))
        data = resp.get("data", {})
        items = data.get("items", [])
        ids = [item.get("record_id") for item in items if item.get("record_id")]
        if ids:
            body = json.dumps({"records": ids}, ensure_ascii=False).encode("utf-8")
            del_req = urllib.request.Request(
                f"https://open.feishu.cn/open-apis/bitable/v1/apps/{cfg['app_token']}/tables/{table_id}/records/batch_delete",
                data=body,
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json; charset=utf-8"},
                method="POST")
            del_resp = json.load(urllib.request.urlopen(del_req))
            if del_resp.get("code") != 0:
                raise RuntimeError(f"清空结果表失败 code={del_resp.get('code')} msg={del_resp.get('msg')}")
            deleted += len(ids)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    log.info(f"{platform} 结果表已清空，共删除 {deleted} 条")


def clear_result_tables(app_id: str, platforms: set, clear_result_table_fn):
    for platform in sorted(platforms):
        clear_result_table_fn(app_id, platform)
