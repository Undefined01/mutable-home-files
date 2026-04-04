from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .assemble import assemble_document
from .formats import get_format
from .merge import merge_documents
from .model import MISSING, StateSnapshot
from .state import load_state, write_state



def _atomic_write(path: Path, text: str, mode: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fchmod(handle.fileno(), int(mode, 8))
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    temp_path.replace(path)



def reconcile_document(document, *, home_directory):
    target_path = Path(home_directory) / document.target
    adapter = get_format(document.format)
    desired = assemble_document(document)
    state = load_state(document)

    if target_path.exists():
        current_text = target_path.read_text()
        current_local = adapter.load_text(current_text)
    else:
        if state is not None:
            raise RuntimeError(f"target disappeared since last apply: {target_path}")
        if not document.create:
            raise FileNotFoundError(f"target does not exist: {target_path}")
        current_text = None
        current_local = {}

    merge_result = merge_documents(
        previous_applied=state.previous_applied if state is not None else MISSING,
        previous_desired=state.previous_desired if state is not None else MISSING,
        current_local=current_local,
        current_desired=desired,
        ownership=document.ownership,
    )
    if merge_result.conflicts:
        conflict = merge_result.conflicts[0]
        raise RuntimeError(f"conflict at {conflict.path}: {conflict.reason}")

    if current_text is None:
        rendered = adapter.dump_new(merge_result.final_document)
    elif not merge_result.planned_ops:
        rendered = current_text
    else:
        rendered = adapter.apply_ops(current_text, merge_result.planned_ops)

    verified = adapter.load_text(rendered)
    if verified != merge_result.final_document:
        raise RuntimeError("rendered document did not match planned semantic output")

    _atomic_write(target_path, rendered, document.mode)
    write_state(
        document,
        StateSnapshot(
            version=1,
            document_id=document.id,
            format=document.format,
            ownership=document.ownership,
            previous_applied=merge_result.final_document,
            previous_desired=desired,
        ),
    )
