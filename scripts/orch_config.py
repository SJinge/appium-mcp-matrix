import os

PKG_NAMES = {
    "gaotu":   "com.gaotu100.superclass",
    "tutu":    "com.gaotu100.tutu",
    "jingpin": "com.gaotu100.jingpin",
    "gongkao": "com.gaotu100.gongkao",
    "xinli":   "com.gaotu100.xinli",
    "ketang":  "com.gaotu100.ketang",
}

DEFAULT_WDA_TEAM = "5YX44746D6"
DEFAULT_WDA_BUNDLE = "com.shijinge.WebDriverAgentRunner"
DEFAULT_WDA_PORT = 8100
DEFAULT_BATCH_SIZE = 20
DEFAULT_MAX_CONCURRENT_AGENT_PROCS = 20
DEFAULT_MAX_BATCH_PROMPT_CHARS = 24000


def resolve_agent_runner() -> str:
    value = os.environ.get("ORCH_AGENT_CLI", "").strip().lower() or "codex"
    if value not in {"codex", "claude"}:
        raise ValueError("ORCH_AGENT_CLI must be one of: codex, claude")
    return value


def resolve_max_concurrent_agent_procs() -> int:
    value = os.environ.get("ORCH_MAX_CONCURRENT_AGENT_PROCS", "").strip()
    if not value:
        return DEFAULT_MAX_CONCURRENT_AGENT_PROCS
    limit = int(value)
    if limit <= 0:
        raise ValueError("ORCH_MAX_CONCURRENT_AGENT_PROCS must be > 0")
    return limit


def resolve_max_batch_prompt_chars() -> int:
    value = os.environ.get("ORCH_MAX_BATCH_PROMPT_CHARS", "").strip()
    if not value:
        return DEFAULT_MAX_BATCH_PROMPT_CHARS
    limit = int(value)
    if limit <= 0:
        raise ValueError("ORCH_MAX_BATCH_PROMPT_CHARS must be > 0")
    return limit


def resolve_ui_audit_enabled() -> bool:
    value = os.environ.get("ORCH_ENABLE_UI_AUDIT", "").strip().lower()
    if not value:
        return True
    return value not in {"0", "false", "no", "off"}
