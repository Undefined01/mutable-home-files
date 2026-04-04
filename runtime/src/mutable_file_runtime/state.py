from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .model import Ownership, OwnershipRule, StateSnapshot


def _target_key(target: str) -> str:
    return hashlib.sha256(target.encode()).hexdigest()


def state_path_for(document) -> Path:
    return Path(document.state_dir) / _target_key(document.target) / "state.json"


def _decode_ownership(payload) -> Ownership:
    rules = tuple(
        OwnershipRule(path=tuple(item["path"]), mode=item["mode"])
        for item in payload.get("rules", [])
    )
    return Ownership(default=payload.get("default", "declared"), rules=rules)


def load_state(document):
    path = state_path_for(document)
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    if payload.get("version") != 1:
        return None
    return StateSnapshot(
        version=1,
        target=payload["target"],
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
                "target": snapshot.target,
                "format": snapshot.format,
                "ownership": {
                    "default": snapshot.ownership.default,
                    "rules": [
                        {"path": list(item.path), "mode": item.mode}
                        for item in snapshot.ownership.rules
                    ],
                },
                "previous_applied": snapshot.previous_applied,
                "previous_desired": snapshot.previous_desired,
            },
            indent=2,
            sort_keys=True,
        )
    )
