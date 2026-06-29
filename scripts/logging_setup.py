#!/usr/bin/env python3
"""统一结构化日志 —— 替代散落的 print()。

格式：2026-06-29 14:10:36 [INFO] [run_id] name: message
输出：① 控制台(StreamHandler，使 orchestrate 子进程的 /tmp 重定向仍能捕获)
     ② logs/{name}.log 滚动文件(RotatingFileHandler，持久、重启不丢、5MB×5)

run_id 关联：每个 orchestrate 进程只处理一个 run，bind_run_id() 设进程级 run_id，
之后所有日志行自动带上，server→orchestrate→各设备可按 run_id 串起来排查。
环境变量 LOG_DIR 可覆盖目录(默认同仓库 logs/)。
"""
import logging
import os
from logging.handlers import RotatingFileHandler

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.environ.get("LOG_DIR", os.path.join(PROJECT_ROOT, "logs"))

_FMT = "%(asctime)s [%(levelname)s] [%(run_id)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

# 进程级当前 run_id（orchestrate 一进程一 run；server 多为 "-"）
_current = {"run_id": "-"}


def bind_run_id(run_id: str):
    _current["run_id"] = run_id or "-"


class _RunIdFilter(logging.Filter):
    def filter(self, record):
        record.run_id = _current["run_id"]
        return True


def get_logger(name: str, logfile: str = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:          # 幂等：已配置直接复用，避免重复 handler
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter(_FMT, _DATEFMT)
    rid = _RunIdFilter()

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.addFilter(rid)
    logger.addHandler(sh)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = RotatingFileHandler(
            os.path.join(LOG_DIR, logfile or f"{name}.log"),
            maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.addFilter(rid)
        logger.addHandler(fh)
    except OSError:
        pass  # 文件 handler 建不起来也不影响控制台输出

    return logger
