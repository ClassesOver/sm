import logging
import subprocess
import sys

import pytest
from loguru import logger as loguru_logger

from smart_reporting.runtime.logging import configure_file_logging


@pytest.mark.parametrize(
    ("debug_value", "debug_count"),
    [("false", 0), ("true", 1)],
)
def test_configure_application_logging_uses_agent_debug_level_once(
    debug_value: str, debug_count: int
) -> None:
    script = f"""
from loguru import logger
from smart_reporting.runtime.logging import configure_application_logging
from smart_reporting.runtime.settings import AgentSettings

settings = AgentSettings.from_environment({{"AGENT_DEBUG": {debug_value!r}}}, load_env_file=False)
configure_application_logging(debug=settings.debug)
configure_application_logging(debug=settings.debug)
logger.debug("APPLICATION_DEBUG_MARKER")
logger.info("APPLICATION_INFO_MARKER")
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr.count("APPLICATION_DEBUG_MARKER") == debug_count
    assert completed.stderr.count("APPLICATION_INFO_MARKER") == 1


def test_configure_file_logging_writes_root_and_agno_logs(tmp_path):
    path = tmp_path / "logs" / "agentos.log"
    original_root_level = logging.getLogger().level
    starrocks_logger = logging.getLogger("starrocks.dialect")
    original_starrocks_level = starrocks_logger.level
    bounded_loggers = (
        "openai._base_client",
        "httpx",
        "httpcore",
        "markdown_it",
        "agno",
        "agno-team",
        "agno-workflow",
    )
    original_levels = {name: logging.getLogger(name).level for name in bounded_loggers}
    configure_file_logging(str(path), debug=True, max_bytes=1024, backup_count=1)
    handler = next(
        item
        for item in logging.getLogger().handlers
        if getattr(item, "_smart_reporting_file_handler", False)
    )
    try:
        logging.getLogger("smart_reporting.test").warning("ROOT_FILE_MARKER")
        logging.getLogger("smart_reporting.test").debug("APP_DEBUG_MARKER")
        logging.getLogger("agno").warning("AGNO_FILE_MARKER")
        loguru_logger.info("LOGURU_FILE_MARKER")
        starrocks_logger.debug("connect_args: %r", {"password": "synthetic-secret"})
        for name in bounded_loggers:
            logging.getLogger(name).debug(
                "FULL_PROMPT_MARKER Authorization=Bearer TOKEN_MARKER BUSINESS_FACT_MARKER"
            )
        handler.flush()
        content = path.read_text(encoding="utf-8")
        assert content.count("ROOT_FILE_MARKER") == 1
        assert content.count("APP_DEBUG_MARKER") == 1
        assert content.count("AGNO_FILE_MARKER") == 1
        assert content.count("LOGURU_FILE_MARKER") == 1
        assert "synthetic-secret" not in content
        assert "FULL_PROMPT_MARKER" not in content
        assert "TOKEN_MARKER" not in content
        assert "BUSINESS_FACT_MARKER" not in content
        assert path.stat().st_mode & 0o777 == 0o640
    finally:
        sink_id = getattr(handler, "_smart_reporting_loguru_sink_id", None)
        if sink_id is not None:
            loguru_logger.remove(sink_id)
        for logger_name in (
            "",
            "agno",
            "agno-team",
            "agno-workflow",
            "uvicorn",
            "uvicorn.error",
            "uvicorn.access",
        ):
            logger = logging.getLogger(logger_name)
            if handler in logger.handlers:
                logger.removeHandler(handler)
        handler.close()
        logging.getLogger().setLevel(original_root_level)
        starrocks_logger.setLevel(original_starrocks_level)
        for name, level in original_levels.items():
            logging.getLogger(name).setLevel(level)


def test_configure_file_logging_rebinds_uvicorn_loggers_once_after_reset(tmp_path):
    path = tmp_path / "logs" / "agentos.log"
    root = logging.getLogger()
    original_root_level = root.level
    logger_names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    original_states = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in logger_names
    }
    configure_file_logging(str(path))
    handler = next(
        item for item in root.handlers if getattr(item, "_smart_reporting_file_handler", False)
    )
    try:
        # Uvicorn 的 dictConfig 会在应用导入后重置这些 named logger。
        for name in logger_names:
            logging.getLogger(name).handlers.clear()
        logging.getLogger("uvicorn").propagate = False
        logging.getLogger("uvicorn.error").addHandler(handler)
        logging.getLogger("uvicorn.error").propagate = True
        logging.getLogger("uvicorn.access").propagate = False

        configure_file_logging(str(path))
        configure_file_logging(str(path))
        logging.getLogger("uvicorn.error").error("UVICORN_ERROR_MARKER")
        logging.getLogger("uvicorn.access").info("UVICORN_ACCESS_MARKER")
        handler.flush()

        content = path.read_text(encoding="utf-8")
        assert content.count("UVICORN_ERROR_MARKER") == 1
        assert content.count("UVICORN_ACCESS_MARKER") == 1
    finally:
        sink_id = getattr(handler, "_smart_reporting_loguru_sink_id", None)
        if sink_id is not None:
            loguru_logger.remove(sink_id)
        for name in ("", *logger_names, "agno", "agno-team", "agno-workflow"):
            current = logging.getLogger(name)
            if handler in current.handlers:
                current.removeHandler(handler)
        handler.close()
        root.setLevel(original_root_level)
        for name, (handlers, level, propagate) in original_states.items():
            current = logging.getLogger(name)
            current.handlers[:] = handlers
            current.setLevel(level)
            current.propagate = propagate
