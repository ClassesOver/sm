import logging

from loguru import logger as loguru_logger

from smart_reporting.logging_config import configure_file_logging


def test_configure_file_logging_writes_root_and_agno_logs(tmp_path):
    path = tmp_path / "logs" / "agentos.log"
    original_root_level = logging.getLogger().level
    starrocks_logger = logging.getLogger("starrocks.dialect")
    original_starrocks_level = starrocks_logger.level
    configure_file_logging(str(path), debug=True, max_bytes=1024, backup_count=1)
    handler = next(
        item
        for item in logging.getLogger().handlers
        if getattr(item, "_smart_reporting_file_handler", False)
    )
    try:
        logging.getLogger("smart_reporting.test").warning("文件日志测试")
        logging.getLogger("smart_reporting.test").debug("应用调试日志测试")
        logging.getLogger("agno").warning("Agno 文件日志测试")
        loguru_logger.info("Loguru 文件日志测试")
        starrocks_logger.debug("connect_args: %r", {"password": "synthetic-secret"})
        handler.flush()
        content = path.read_text(encoding="utf-8")
        assert "文件日志测试" in content
        assert "应用调试日志测试" in content
        assert "Agno 文件日志测试" in content
        assert "Loguru 文件日志测试" in content
        assert "synthetic-secret" not in content
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
