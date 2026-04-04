from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from ..diff import apply_ops
from ..model import EditOp


class JsonFormat:
    name = "json"

    def load_file(self, path: Path):
        return self.load_text(path.read_text())

    def load_text(self, text: str):
        if text.strip() == "":
            return {}
        return json.loads(text)

    def dump_new(self, data):
        return json.dumps(data, indent=2) + "\n"

    def apply_ops(self, original_text: str, operations: Sequence[EditOp]):
        document = self.load_text(original_text)
        updated = apply_ops(document, operations)
        return self.dump_new(updated)
