from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from ..model import EditOp


class FormatImplementation(Protocol):
    name: str

    def load_file(self, path: Path): ...
    def load_text(self, text: str): ...
    def dump_new(self, data): ...
    def apply_ops(self, original_text: str, operations: Sequence[EditOp]): ...
