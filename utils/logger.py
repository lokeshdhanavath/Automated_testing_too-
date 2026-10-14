"""Small logger factory: one file per run, plus console output."""
import logging
from datetime import datetime
from pathlib import Path

from utils import config

LOG_DIR = config.ROOT / "reports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_run_logger(run_id: str = None) -> tuple[logging.Logger, Path]:
    """
    Return a logger that writes to reports/logs/run_<id>.log
    and also prints to the console.
    """
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"run_{run_id}.log"

    logger = logging.getLogger(f"apex.{run_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Avoid duplicate handlers on repeated calls in the same process
    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(message)s",
            datefmt="%H:%M:%S",
        )

        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    return logger, log_path