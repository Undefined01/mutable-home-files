import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def runtime_env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return {
        "root": tmp_path,
        "home": home,
        "state_dir": tmp_path / "state",
    }


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
