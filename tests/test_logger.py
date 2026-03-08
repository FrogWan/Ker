from pathlib import Path
from ker.logger import init_logger, get_logger


def test_init_logger(tmp_path: Path):
    logger = init_logger(tmp_path)
    assert logger.name == "ker"
    log_dir = tmp_path / "logs"
    assert log_dir.exists()


def test_get_logger():
    logger = get_logger("test")
    assert logger.name == "ker.test"
