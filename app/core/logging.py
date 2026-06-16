import logging
import sys


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the memory_rag logger with stdout handler.

    Args:
        level: Log level name (e.g. "DEBUG", "INFO", "WARNING").

    Returns:
        Configured logger instance for the memory_rag namespace.
    """
    logger = logging.getLogger("memory_rag")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger
