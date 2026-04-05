from __future__ import annotations

from .model import MISSING, clone, is_mapping, ordered_keys


def project_desired(value, ownership, path=()):
    if value is MISSING:
        return MISSING
    if ownership.mode_for(path) == "local":
        return MISSING
    if is_mapping(value):
        result = {}
        for key, item in value.items():
            projected = project_desired(item, ownership, path + (key,))
            if projected is not MISSING:
                result[key] = projected
        return result
    return clone(value)


def project_local(current_local, previous_applied, current_desired, ownership, path=()):
    mode = ownership.mode_for(path)
    if mode == "local":
        return MISSING

    visible_here = mode == "sealed"
    has_basis = visible_here or previous_applied is not MISSING or current_desired is not MISSING
    if not has_basis:
        return MISSING

    should_recurse = any(
        is_mapping(value)
        for value in (current_local, previous_applied, current_desired)
        if value is not MISSING
    )
    if not should_recurse:
        if current_local is MISSING:
            return MISSING
        return clone(current_local)

    if current_local is not MISSING and not is_mapping(current_local):
        return clone(current_local)

    result = {}
    current_present = is_mapping(current_local)
    keys = list(ordered_keys(previous_applied, current_desired))
    if visible_here and current_present:
        for key in current_local.keys():
            if key not in keys:
                keys.append(key)

    for key in keys:
        projected = project_local(
            current_local.get(key, MISSING) if current_present else MISSING,
            previous_applied.get(key, MISSING) if is_mapping(previous_applied) else MISSING,
            current_desired.get(key, MISSING) if is_mapping(current_desired) else MISSING,
            ownership,
            path + (key,),
        )
        if projected is not MISSING:
            result[key] = projected

    if result:
        return result
    if current_present and any(
        is_mapping(value)
        for value in (previous_applied, current_desired)
        if value is not MISSING
    ):
        return {}
    return MISSING


def materialize_resolved(current_local, resolved_managed, previous_applied, current_desired, ownership, path=()):
    mode = ownership.mode_for(path)
    if mode == "local":
        if current_local is MISSING:
            return MISSING
        return clone(current_local)

    has_managed_basis = (
        previous_applied is not MISSING
        or current_desired is not MISSING
        or resolved_managed is not MISSING
    )
    if not has_managed_basis:
        if current_local is MISSING:
            return MISSING
        if mode == "declared":
            return clone(current_local)
        return MISSING

    should_recurse = any(
        is_mapping(value)
        for value in (current_local, resolved_managed, previous_applied, current_desired)
        if value is not MISSING
    )
    if not should_recurse:
        if resolved_managed is MISSING:
            return MISSING
        return clone(resolved_managed)

    if current_local is not MISSING and not is_mapping(current_local):
        if resolved_managed is MISSING:
            return MISSING
        return clone(resolved_managed)

    result = {}
    current_present = is_mapping(current_local)
    for key in ordered_keys(current_local, resolved_managed, previous_applied, current_desired):
        materialized = materialize_resolved(
            current_local.get(key, MISSING) if current_present else MISSING,
            resolved_managed.get(key, MISSING) if is_mapping(resolved_managed) else MISSING,
            previous_applied.get(key, MISSING) if is_mapping(previous_applied) else MISSING,
            current_desired.get(key, MISSING) if is_mapping(current_desired) else MISSING,
            ownership,
            path + (key,),
        )
        if materialized is not MISSING:
            result[key] = materialized

    if result:
        return result
    if is_mapping(resolved_managed):
        return {}
    return MISSING
