from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from loguru import logger as loguru_logger

_FILE_HANDLER_MARKER = "_smart_reporting_file_handler"
_LOGURU_SINK_MARKER = "_smart_reporting_loguru_sink_id"
_APPLICATION_LOGURU_SINK_ID: int | None = None
_DEFAULT_LOGURU_SINK_REMOVED = False
_INFO_LOGGERS = (
    "starrocks.dialect",
    "agno",
    "agno-team",
    "agno-workflow",
)
_WARNING_LOGGERS = (
    "openai._base_client",
    "httpx",
    "httpcore",
    "markdown_it",
)


def configure_application_logging(*, debug: bool = False) -> None:
    """按 AGENT_DEBUG 配置唯一的应用 Loguru 控制台 sink。"""

    global _APPLICATION_LOGURU_SINK_ID, _DEFAULT_LOGURU_SINK_REMOVED
    if not _DEFAULT_LOGURU_SINK_REMOVED:
        try:
            loguru_logger.remove(0)
        except ValueError:
            pass
        _DEFAULT_LOGURU_SINK_REMOVED = True
    if _APPLICATION_LOGURU_SINK_ID is not None:
        try:
            loguru_logger.remove(_APPLICATION_LOGURU_SINK_ID)
        except ValueError:
            pass
    _APPLICATION_LOGURU_SINK_ID = loguru_logger.add(
        sys.stderr,
        level="DEBUG" if debug else "INFO",
        backtrace=False,
        diagnose=False,
    )


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
    handler = next(
        (item for item in root.handlers if getattr(item, _FILE_HANDLER_MARKER, False)),
        None,
    )
    if handler is None:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        os.chmod(log_path, 0o640)
        setattr(handler, _FILE_HANDLER_MARKER, True)
        root.addHandler(handler)
    handler.setLevel(logging.DEBUG if debug else logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    # 应用代码统一使用 Loguru；第三方仍通过标准 logging。两者复用同一个受控
    # RotatingFileHandler，确保文件权限、轮转上限和保留数量只有一个事实来源。
    if getattr(handler, _LOGURU_SINK_MARKER, None) is None:
        sink_id = loguru_logger.add(
            handler,
            level="DEBUG" if debug else "INFO",
            format="{message}",
            backtrace=False,
            diagnose=False,
        )
        setattr(handler, _LOGURU_SINK_MARKER, sink_id)

    # StarRocks dialect 的 DEBUG 事件包含完整 connect_args，其中包括数据库密码。
    # 即使应用开启调试日志，也必须在事件传播到控制台或持久文件前阻断该级别；
    # 部署方若已配置 WARNING/ERROR 等更严格级别，则保持原配置不变。
    for names, minimum_level in (
        (_INFO_LOGGERS, logging.INFO),
        (_WARNING_LOGGERS, logging.WARNING),
    ):
        for name in names:
            logger = logging.getLogger(name)
            if logger.level == logging.NOTSET or logger.level < minimum_level:
                logger.setLevel(minimum_level)

    # Agno 可能由宿主配置为不向 root 传播；只有此时才直接挂文件 handler。
    # 向 root 传播时重复挂载会让同一条事件写入两次。
    for name in ("agno", "agno-team", "agno-workflow"):
        logger = logging.getLogger(name)
        if logger.propagate:
            if handler in logger.handlers:
                logger.removeHandler(handler)
        elif handler not in logger.handlers:
            logger.addHandler(handler)

    # uvicorn.error 传播到 uvicorn；文件 handler 只挂父 logger。access 不传播，
    # 因此单独挂载。
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.propagate = False
    if handler not in uvicorn_logger.handlers:
        uvicorn_logger.addHandler(handler)
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    if handler in uvicorn_error_logger.handlers:
        uvicorn_error_logger.removeHandler(handler)
    uvicorn_error_logger.propagate = True
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.propagate = False
    if handler not in uvicorn_access_logger.handlers:
        uvicorn_access_logger.addHandler(handler)
