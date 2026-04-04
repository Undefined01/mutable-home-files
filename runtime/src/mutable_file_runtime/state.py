from __future__ import annotations

import json
from pathlib import Path

from .model import Ownership, OwnershipOverride, StateSnapshot



def state_path_for(document) -> Path:
    return Path(document.state_dir) / document.id / "state.json"



def _decode_ownership(payload) -> Ownership:
    overrides = tuple(
        OwnershipOverride(path=tuple(item["path"]), mode=item["mode"])
        for item in payload.get("overrides", [])
    )
    return Ownership(fallback=payload.get("fallback", "declared"), overrides=overrides)



def load_state(document):
    path = state_path_for(document)
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    if payload.get("version") != 1:
        return None
    return StateSnapshot(
        version=1,
        document_id=payload["document_id"],
        format=payload["format"],
        ownership=_decode_ownership(payload.get("ownership", {})),
        previous_applied=payload.get("previous_applied", {}),
        previous_desired=payload.get("previous_desired", {}),
    )



def write_state(document, snapshot: StateSnapshot) -> None:
    path = state_path_for(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": snapshot.version,
                "document_id": snapshot.document_id,
                "format": snapshot.format,
                "ownership": {
                    "fallback": snapshot.ownership.fallback,
                    "overrides": [
                        {"path": list(item.path), "mode": item.mode}
                        for item in snapshot.ownership.overrides
                    ],
                },
                "previous_applied": snapshot.previous_applied,
                "previous_desired": snapshot.previous_desired,
            },
            indent=2,
            sort_keys=True,
        )
    )
