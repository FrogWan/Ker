from __future__ import annotations

import logging
import logging.handlers
from datetime import datetime
from pathlib import Path


def init_logger(ker_root: Path) -> logging.Logger:
    log_dir = ker_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("ker")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "{asctime} [{levelname}] {name}: {message}",
        style="{",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    today = datetime.now().strftime("%Y-%m-%d")
    fh = logging.FileHandler(log_dir / f"{today}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"ker.{name}")
