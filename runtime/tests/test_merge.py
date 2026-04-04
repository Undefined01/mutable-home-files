from mutable_file_runtime.merge import merge_documents
from mutable_file_runtime.model import Ownership, OwnershipRule


def make_ownership(default="declared", rules=()):
    return Ownership(
        default=default,
        rules=tuple(OwnershipRule(path=tuple(path), mode=mode) for path, mode in rules),
    )


def test_declared_keeps_unknown_local_fields():
    result = merge_documents(
        previous_desired={"app": {"name": "demo"}},
        current_local={"app": {"name": "demo"}, "localOnly": {"cache": True}},
        current_desired={"app": {"name": "demo"}},
        ownership=make_ownership(),
    )

    assert result.conflicts == []
    assert result.final_document == {
        "app": {"name": "demo"},
        "localOnly": {"cache": True},
    }


def test_sealed_rejects_unknown_local_fields():
    result = merge_documents(
        previous_desired={"credentials": {"api": {"token": "x"}}},
        current_local={"credentials": {"api": {"token": "x"}, "extra": True}},
        current_desired={"credentials": {"api": {"token": "x"}}},
        ownership=make_ownership(rules=[(["credentials"], "sealed")]),
    )

    assert result.conflicts
    assert result.conflicts[0].path == ("credentials", "extra")


def test_local_changes_to_unchanged_managed_fields_conflict():
    result = merge_documents(
        previous_desired={"app": {"name": "demo"}},
        current_local={"app": {"name": "manual"}},
        current_desired={"app": {"name": "demo"}},
        ownership=make_ownership(),
    )

    assert result.conflicts
    assert result.conflicts[0].path == ("app", "name")


def test_desired_changes_apply_when_local_is_unchanged():
    result = merge_documents(
        previous_desired={"app": {"name": "old"}},
        current_local={"app": {"name": "old"}},
        current_desired={"app": {"name": "new"}},
        ownership=make_ownership(),
    )

    assert result.conflicts == []
    assert result.final_document == {"app": {"name": "new"}}


def test_same_value_convergence_is_not_a_conflict():
    result = merge_documents(
        previous_desired={"app": {"name": "old"}},
        current_local={"app": {"name": "new"}},
        current_desired={"app": {"name": "new"}},
        ownership=make_ownership(),
    )

    assert result.conflicts == []
    assert result.final_document == {"app": {"name": "new"}}


def test_takeover_equal_value_is_allowed():
    result = merge_documents(
        previous_desired={},
        current_local={"app": {"name": "demo"}},
        current_desired={"app": {"name": "demo"}},
        ownership=make_ownership(),
    )

    assert result.conflicts == []
    assert result.final_document == {"app": {"name": "demo"}}


def test_takeover_different_value_conflicts():
    result = merge_documents(
        previous_desired={},
        current_local={"app": {"name": "manual"}},
        current_desired={"app": {"name": "demo"}},
        ownership=make_ownership(),
    )

    assert result.conflicts
    assert result.conflicts[0].path == ("app", "name")


def test_managed_deletion_keeps_unknown_declared_siblings():
    result = merge_documents(
        previous_desired={"credentials": {"user": "demo"}},
        current_local={"credentials": {"user": "demo", "runtime": "x"}},
        current_desired={},
        ownership=make_ownership(),
    )

    assert result.conflicts == []
    assert result.final_document == {"credentials": {"runtime": "x"}}


def test_local_ownership_stops_managing_previous_subtrees():
    result = merge_documents(
        previous_desired={"runtime": {"enabled": False}},
        current_local={"runtime": {"enabled": True}},
        current_desired={},
        ownership=make_ownership(rules=[(["runtime"], "local")]),
    )

    assert result.conflicts == []
    assert result.final_document == {"runtime": {"enabled": True}}
