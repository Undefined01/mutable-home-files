from mutable_file_runtime.model import MISSING, Ownership, OwnershipRule
from mutable_file_runtime.projection import materialize_resolved, project_local


def make_ownership(default="declared", rules=()):
    return Ownership(
        default=default,
        rules=tuple(OwnershipRule(path=tuple(path), mode=mode) for path, mode in rules),
    )


def test_project_local_declared_hides_unknown_siblings_outside_basis():
    projected = project_local(
        current_local={"app": {"name": "manual"}, "extra": {"cache": True}},
        previous_applied={"app": {"name": "demo"}},
        current_desired={"app": {"name": "demo"}},
        ownership=make_ownership(),
    )

    assert projected == {"app": {"name": "manual"}}


def test_project_local_sealed_keeps_unknown_siblings_inside_visible_subtree():
    projected = project_local(
        current_local={
            "credentials": {"api": {"token": "x"}, "extra": True},
            "ignored": {"cache": True},
        },
        previous_applied={"credentials": {"api": {"token": "x"}}},
        current_desired={"credentials": {"api": {"token": "x"}}},
        ownership=make_ownership(rules=[(["credentials"], "sealed")]),
    )

    assert projected == {"credentials": {"api": {"token": "x"}, "extra": True}}


def test_project_local_sealed_nested_subtree_keeps_new_fields_but_local_rule_still_hides_descendants():
    projected = project_local(
        current_local={
            "service": {
                "declared": {"enabled": True, "extra": "keep"},
                "runtime": {"token": "secret"},
            }
        },
        previous_applied={"service": {"declared": {"enabled": False}}},
        current_desired={"service": {"declared": {"enabled": True}}},
        ownership=make_ownership(
            rules=[(["service"], "sealed"), (["service", "runtime"], "local")]
        ),
    )

    assert projected == {"service": {"declared": {"enabled": True, "extra": "keep"}}}


def test_project_local_declared_child_overrides_sealed_ancestor():
    projected = project_local(
        current_local={
            "service": {
                "runtime": {"name": "manual", "token": "secret"},
                "extra": {"cache": True},
            }
        },
        previous_applied={"service": {"runtime": {"name": "demo"}}},
        current_desired={"service": {"runtime": {"name": "demo"}}},
        ownership=make_ownership(
            rules=[(["service"], "sealed"), (["service", "runtime"], "declared")]
        ),
    )

    assert projected == {
        "service": {
            "runtime": {"name": "manual"},
            "extra": {"cache": True},
        }
    }


def test_project_local_omits_deleted_managed_mapping():
    projected = project_local(
        current_local={},
        previous_applied={"service": {"enabled": True}},
        current_desired={},
        ownership=make_ownership(),
    )

    assert projected == {}


def test_materialize_resolved_drops_deleted_managed_mapping():
    materialized = materialize_resolved(
        current_local={"service": {"enabled": False}},
        resolved_managed={},
        previous_applied={"service": {"enabled": True}},
        current_desired={},
        ownership=make_ownership(),
    )

    assert materialized == {}


def test_project_local_returns_missing_when_no_basis_exists():
    projected = project_local(
        current_local={"extra": True},
        previous_applied=MISSING,
        current_desired=MISSING,
        ownership=make_ownership(),
    )

    assert projected is MISSING
