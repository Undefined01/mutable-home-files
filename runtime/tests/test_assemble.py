import json

import pytest

from mutable_file_runtime.assemble import assemble_document
from mutable_file_runtime.task_schema import decode_task_file



def make_document(tmp_path, **overrides):
    payload = {
        "version": 4,
        "documents": [
            {
                "id": "doc-1",
                "target": ".config/app/config.json",
                "format": "json",
                "create": True,
                "mode": "0600",
                "state_dir": str(tmp_path / "state"),
                "ownership": {
                    "fallback": "declared",
                    "overrides": [],
                },
                "layers": [
                    {
                        "id": "layer-defaults",
                        "name": "defaults",
                        "source": {
                            "kind": "inline",
                            "value": {"app": {"name": "demo"}},
                        },
                        "from": [],
                        "to": [],
                        "required": True,
                    }
                ],
            }
        ],
    }
    payload["documents"][0].update(overrides)
    return decode_task_file(payload).documents[0]



def test_assemble_merges_inline_and_runtime_layers(tmp_path):
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"token": "secret-token"}))
    document = make_document(
        tmp_path,
        layers=[
            {
                "id": "layer-defaults",
                "name": "defaults",
                "source": {
                    "kind": "inline",
                    "value": {
                        "app": {"name": "demo"},
                        "credentials": {"database": {"user": "demo"}},
                    },
                },
                "from": [],
                "to": [],
                "required": True,
            },
            {
                "id": "layer-secret",
                "name": "api-secret",
                "source": {
                    "kind": "runtime_path",
                    "path": str(secret),
                },
                "from": ["token"],
                "to": ["credentials", "api", "token"],
                "required": True,
            },
        ],
    )

    assembled = assemble_document(document)

    assert assembled == {
        "app": {"name": "demo"},
        "credentials": {
            "database": {"user": "demo"},
            "api": {"token": "secret-token"},
        },
    }



def test_assemble_skips_optional_missing_layers(tmp_path):
    missing = tmp_path / "missing.json"
    document = make_document(
        tmp_path,
        layers=[
            {
                "id": "layer-defaults",
                "name": "defaults",
                "source": {
                    "kind": "inline",
                    "value": {"app": {"name": "demo"}},
                },
                "from": [],
                "to": [],
                "required": True,
            },
            {
                "id": "layer-optional",
                "name": "optional-secret",
                "source": {
                    "kind": "runtime_path",
                    "path": str(missing),
                },
                "from": ["token"],
                "to": ["credentials", "token"],
                "required": False,
            },
        ],
    )

    assert assemble_document(document) == {"app": {"name": "demo"}}



def test_assemble_rejects_scalar_overlap(tmp_path):
    document = make_document(
        tmp_path,
        layers=[
            {
                "id": "layer-one",
                "name": "one",
                "source": {
                    "kind": "inline",
                    "value": {"app": {"name": "demo"}},
                },
                "from": [],
                "to": [],
                "required": True,
            },
            {
                "id": "layer-two",
                "name": "two",
                "source": {
                    "kind": "inline",
                    "value": {"name": "other"},
                },
                "from": [],
                "to": ["app"],
                "required": True,
            },
        ],
    )

    with pytest.raises(RuntimeError):
        assemble_document(document)



def test_assemble_rejects_local_targets(tmp_path):
    document = make_document(
        tmp_path,
        ownership={
            "fallback": "declared",
            "overrides": [{"path": ["runtime"], "mode": "local"}],
        },
        layers=[
            {
                "id": "layer-one",
                "name": "one",
                "source": {
                    "kind": "inline",
                    "value": {"enabled": True},
                },
                "from": [],
                "to": ["runtime"],
                "required": True,
            }
        ],
    )

    with pytest.raises(RuntimeError):
        assemble_document(document)
