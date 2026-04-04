from mutable_file_runtime.diff import apply_ops, diff_documents
from mutable_file_runtime.model import InsertOp, RemoveOp, SetOp



def simplify(ops):
    result = []
    for op in ops:
        if isinstance(op, SetOp):
            result.append(("set", op.path, op.value))
        elif isinstance(op, RemoveOp):
            result.append(("remove", op.path))
        elif isinstance(op, InsertOp):
            result.append(("insert", op.path, op.value))
        else:
            raise AssertionError(f"unexpected op: {op!r}")
    return result



def test_diff_recurses_into_objects():
    old = {"app": {"name": "old", "keep": 1}}
    new = {"app": {"name": "new", "keep": 1}, "extra": 2}

    ops = diff_documents(old, new)

    assert simplify(ops) == [
        ("set", ("app", "name"), "new"),
        ("set", ("extra",), 2),
    ]



def test_diff_emits_array_insertions_in_order():
    old = {"items": [1, 3]}
    new = {"items": [1, 2, 3, 4]}

    ops = diff_documents(old, new)

    assert simplify(ops) == [
        ("insert", ("items", 1), 2),
        ("insert", ("items", 3), 4),
    ]
    assert apply_ops(old, ops) == new



def test_diff_reuses_nested_paths_for_array_element_updates():
    old = {"items": [{"a": 1}, {"b": 2}]}
    new = {"items": [{"a": 1}, {"b": 3}, {"c": 4}]}

    ops = diff_documents(old, new)

    assert simplify(ops) == [
        ("set", ("items", 1, "b"), 3),
        ("insert", ("items", 2), {"c": 4}),
    ]
    assert apply_ops(old, ops) == new



def test_diff_emits_repeated_removals_for_array_deletes():
    old = {"items": [1, 2, 3]}
    new = {"items": [1]}

    ops = diff_documents(old, new)

    assert simplify(ops) == [
        ("remove", ("items", 1)),
        ("remove", ("items", 1)),
    ]
    assert apply_ops(old, ops) == new
