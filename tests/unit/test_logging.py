import logging

from app.core.logging import configure_logging


class TestConfigureLogging:
    def test_logger_name_is_memory_rag(self):
        logger = configure_logging("INFO")
        assert logger.name == "memory_rag"

    def test_returns_same_logger_on_duplicate_call(self):
        logger1 = configure_logging("INFO")
        logger2 = configure_logging("DEBUG")
        assert logger1 is logger2

    def test_no_duplicate_handlers(self):
        configure_logging("INFO")
        logger = logging.getLogger("memory_rag")
        initial_count = len(logger.handlers)
        configure_logging("INFO")
        assert len(logger.handlers) == initial_count

    def test_log_level_applied(self):
        logger = configure_logging("WARNING")
        assert logger.level == logging.WARNING

    def test_handler_added(self):
        logger = configure_logging("INFO")
        assert len(logger.handlers) >= 1
