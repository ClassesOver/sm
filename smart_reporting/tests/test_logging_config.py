import logging

from smart_reporting.logging_config import configure_file_logging


def test_configure_file_logging_writes_root_and_agno_logs(tmp_path):
    path = tmp_path / "logs" / "agentos.log"
    original_root_level = logging.getLogger().level
    configure_file_logging(str(path), max_bytes=1024, backup_count=1)
    handler = next(
        item
        for item in logging.getLogger().handlers
        if getattr(item, "_smart_reporting_file_handler", False)
    )
    try:
        logging.getLogger("smart_reporting.test").warning("文件日志测试")
        logging.getLogger("agno").warning("Agno 文件日志测试")
        handler.flush()
        content = path.read_text(encoding="utf-8")
        assert "文件日志测试" in content
        assert "Agno 文件日志测试" in content
        assert path.stat().st_mode & 0o777 == 0o640
    finally:
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
