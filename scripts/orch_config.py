import os

PKG_NAMES = {
    "gaotu":   "com.gaotu100.superclass",
    "tutu":    "com.gaotu100.tutu",
    "jingpin": "com.gaotu100.jingpin",
    "gongkao": "com.gaotu100.gongkao",
    "xinli":   "com.gaotu100.xinli",
    "ketang":  "com.gaotu100.ketang",
}

APP_DISPLAY_NAMES = {
    "gaotu":   "高途",
    "tutu":    "途途课堂",
    "jingpin": "高途高中",
    "gongkao": "高途公职",
    "xinli":   "高途心理",
    "ketang":  "高途素养",
}

DEFAULT_WDA_TEAM = "LU2B796CHV"  # 高途组织付费团队(金鸽石 TV3FCP39YB),证书1年有效,比个人免费7天证书稳
DEFAULT_WDA_BUNDLE = "com.shijinge.WebDriverAgentRunner"
DEFAULT_WDA_PORT = 8100
DEFAULT_BATCH_SIZE = 20
DEFAULT_MAX_CONCURRENT_AGENT_PROCS = 20
DEFAULT_MAX_BATCH_PROMPT_CHARS = 24000


# headless runner 凭据(如 claude 的 ANTHROPIC_API_KEY)存放在仓库外的本地 env 文件，
# 绝不写进受版本控制的 plist/代码。默认 ~/.config/appium-matrix/runner.env，可用
# ORCH_SECRETS_FILE 覆盖。格式:每行 KEY=VALUE(# 开头为注释)。
DEFAULT_SECRETS_FILE = os.path.expanduser("~/.config/appium-matrix/runner.env")


def load_runner_secrets(environ=None) -> list:
    """把本地 env 文件里的凭据注入进程环境，返回已加载的 key 名列表(不含值，供日志用)。

    launchd 拉起的 webhook/orchestrate 进程环境没有 ANTHROPIC_* 变量，headless
    `claude --print` 会 403。在此把仓库外文件里的 key 注入 os.environ，所有 agent
    子进程(explore/batch/per-device)自动继承，无需改各启动点。
    """
    if environ is None:
        environ = os.environ
    path = environ.get("ORCH_SECRETS_FILE", "").strip() or DEFAULT_SECRETS_FILE
    if not path or not os.path.exists(path):
        return []
    loaded = []
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                environ[key] = val
                loaded.append(key)
    return loaded


def resolve_agent_runner() -> str:
    value = os.environ.get("ORCH_AGENT_CLI", "").strip().lower() or "claude"
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
