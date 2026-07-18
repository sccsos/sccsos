"""Structured JSON logging for sccsos."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class JSONFormatter(logging.Formatter):
    """Format log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "agent_id"):
            log_entry["agent_id"] = record.agent_id
        if hasattr(record, "event"):
            log_entry["event"] = record.event
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logger(name: str = "sccsos",
                 level: str = "INFO",
                 log_dir: Optional[str] = None,
                 json_format: bool = True,
                 retention_days: int = 0) -> logging.Logger:
    """Configure and return a logger.

    Args:
        name: Logger name.
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        log_dir: Directory for log file. If None, stdout only.
        json_format: Use JSON format (default: True).
        retention_days: Number of days to keep log files.
            0 or negative means no rotation (default).
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = JSONFormatter() if json_format else logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler (if log_dir specified)
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        if retention_days > 0:
            # Timed rotation — keeps N days of logs, no need to clean manually
            file_handler = logging.handlers.TimedRotatingFileHandler(
                log_path / "sccsos.log",
                when="midnight",
                interval=1,
                backupCount=retention_days,
                encoding="utf-8",
            )
        else:
            file_handler = logging.FileHandler(
                log_path / "sccsos.log", encoding="utf-8"
            )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# Global logger (lazy init)
_logger: Optional[logging.Logger] = None


def get_logger() -> logging.Logger:
    """Get the global logger, creating with defaults if needed.

    Reads configuration from ``sccsos.yaml`` (``logging.level``,
    ``logging.directory``, and ``logging.retention_days``)
    on first call.
    """
    global _logger
    if _logger is None:
        from sccsos.core.config import get_config
        cfg = get_config()
        log_dir = cfg.logging.directory or None
        _logger = setup_logger(
            level=cfg.logging.level,
            log_dir=log_dir,
            retention_days=cfg.logging.retention_days,
        )
    return _logger
