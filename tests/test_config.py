import json
from pathlib import Path
from unittest.mock import patch

from ker.config import load_settings


def test_load_settings_defaults():
    settings = load_settings()
    assert settings.workspace == Path.cwd().resolve()
    assert settings.ker_root == Path.cwd().resolve() / ".ker"
    assert settings.llm_provider == "anthropic"


def test_config_json_precedence(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    (ker_root / "config.json").write_text(
        json.dumps({"model_id": "test-model"}), encoding="utf-8"
    )
    settings = load_settings()
    assert settings.model_id == "test-model"
