from mutable_file_runtime.formats import get_format
from mutable_file_runtime.model import SetOp


def test_json_apply_ops_preserves_existing_key_order():
    adapter = get_format("json")
    original = '{"a": 1, "b": 2}\n'

    rendered = adapter.apply_ops(
        original,
        [
            SetOp(path=("b",), value=3),
            SetOp(path=("c",), value=4),
        ],
    )

    assert adapter.load_text(rendered) == {"a": 1, "b": 3, "c": 4}
    assert rendered.index('"a"') < rendered.index('"b"') < rendered.index('"c"')


def test_yaml_apply_ops_preserves_comments():
    adapter = get_format("yaml")
    original = '# top\napp:\n  name: old\nruntime:\n  enabled: true # keep\n'

    rendered = adapter.apply_ops(original, [SetOp(path=("app", "name"), value="new")])

    assert adapter.load_text(rendered) == {
        "app": {"name": "new"},
        "runtime": {"enabled": True},
    }
    assert '# top' in rendered
    assert '# keep' in rendered


def test_toml_apply_ops_preserves_comments():
    adapter = get_format("toml")
    original = '# top\n[app]\nname = "old"\n\n[runtime]\nenabled = true # keep\n'

    rendered = adapter.apply_ops(original, [SetOp(path=("app", "name"), value="new")])

    assert adapter.load_text(rendered) == {
        "app": {"name": "new"},
        "runtime": {"enabled": True},
    }
    assert '# top' in rendered
    assert '# keep' in rendered
