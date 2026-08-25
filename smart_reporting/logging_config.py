from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FILE_HANDLER_MARKER = "_smart_reporting_file_handler"
_SENSITIVE_DEBUG_LOGGERS = ("starrocks.dialect",)


def configure_file_logging(
    path: str | None,
    *,
    debug: bool = False,
    max_bytes: int = 50 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """将服务日志追加到受控文件，同时保留现有 stdout 日志。"""

    normalized = str(path or "").strip()
    if not normalized:
        return
    if max_bytes < 1 or backup_count < 1:
        raise ValueError("日志轮转参数必须大于 0")

    log_path = Path(normalized)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(log_path.parent, 0o750)

    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, _FILE_HANDLER_MARKER, False):
            return

    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    os.chmod(log_path, 0o640)
    setattr(handler, _FILE_HANDLER_MARKER, True)
    handler.setLevel(logging.DEBUG if debug else logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # StarRocks dialect 的 DEBUG 事件包含完整 connect_args，其中包括数据库密码。
    # 即使应用开启调试日志，也必须在事件传播到控制台或持久文件前阻断该级别；
    # 部署方若已配置 WARNING/ERROR 等更严格级别，则保持原配置不变。
    for name in _SENSITIVE_DEBUG_LOGGERS:
        logger = logging.getLogger(name)
        if logger.level == logging.NOTSET or logger.level < logging.INFO:
            logger.setLevel(logging.INFO)

    # Agno 的默认 RichHandler 设置了 propagate=False，因此必须显式挂载同一个
    # 文件 handler；Uvicorn 日志通常通过 root 传播，仍列出以兼容自定义配置。
    for name in (
        "agno",
        "agno-team",
        "agno-workflow",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    ):
        logger = logging.getLogger(name)
        if handler not in logger.handlers:
            logger.addHandler(handler)
