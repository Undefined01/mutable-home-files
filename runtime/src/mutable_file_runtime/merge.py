from __future__ import annotations

from .diff import diff_documents
from .model import Conflict, MISSING, MergeResult, PathType, clone, is_mapping, ordered_keys, values_equal



def _record(conflicts, path: PathType, reason: str) -> None:
    conflicts.append(Conflict(path=path, reason=reason))



def _merge_leaf(path, previous_applied, previous_desired, current_local, current_desired, ownership, conflicts):
    mode = ownership.mode_for(path)
    if mode == "local":
        return clone(current_local)

    if current_desired is MISSING and previous_desired is MISSING:
        if current_local is MISSING:
            return MISSING
        if mode == "sealed":
            _record(conflicts, path, "undeclared field under sealed ownership")
        return clone(current_local)

    if current_desired is MISSING:
        if previous_applied is not MISSING and not values_equal(current_local, previous_applied) and current_local is not MISSING:
            _record(conflicts, path, "local value differs from removed managed field")
            return clone(current_local)
        return MISSING

    if previous_desired is MISSING:
        if current_local is MISSING or values_equal(current_local, current_desired):
            return clone(current_desired)
        _record(conflicts, path, "local value differs from managed takeover")
        return clone(current_local)

    if previous_applied is not MISSING and not values_equal(current_local, previous_applied) and not values_equal(current_local, current_desired):
        _record(conflicts, path, "local value differs from managed field")
        return clone(current_local)

    return clone(current_desired)



def _merge_node(path, previous_applied, previous_desired, current_local, current_desired, ownership, conflicts):
    mode = ownership.mode_for(path)
    if mode == "local":
        return clone(current_local)

    should_recurse_mapping = isinstance(current_desired, dict) or (
        current_desired is MISSING
        and any(isinstance(value, dict) for value in (previous_applied, previous_desired, current_local) if value is not MISSING)
    )
    if not should_recurse_mapping:
        return _merge_leaf(path, previous_applied, previous_desired, current_local, current_desired, ownership, conflicts)

    if current_local is not MISSING and not isinstance(current_local, dict):
        if current_desired is MISSING and previous_desired is MISSING:
            return _merge_leaf(path, previous_applied, previous_desired, current_local, current_desired, ownership, conflicts)
        reason = "type mismatch during object reconciliation"
        if previous_desired is MISSING:
            reason = "type mismatch during managed takeover"
        _record(conflicts, path, reason)
        return clone(current_local)

    result = {}
    for key in ordered_keys(current_local, current_desired, previous_desired, previous_applied):
        merged = _merge_node(
            path + (key,),
            previous_applied.get(key, MISSING) if isinstance(previous_applied, dict) else MISSING,
            previous_desired.get(key, MISSING) if isinstance(previous_desired, dict) else MISSING,
            current_local.get(key, MISSING) if isinstance(current_local, dict) else MISSING,
            current_desired.get(key, MISSING) if isinstance(current_desired, dict) else MISSING,
            ownership,
            conflicts,
        )
        if merged is not MISSING:
            result[key] = merged

    if current_desired is MISSING and previous_desired is not MISSING and result == {}:
        return MISSING
    if current_desired is MISSING and previous_desired is MISSING and current_local is MISSING:
        return MISSING
    return result



def merge_documents(*, previous_desired, current_local, current_desired, ownership, previous_applied=MISSING):
    previous_desired_value = previous_desired if previous_desired is not MISSING else MISSING
    previous_applied_value = previous_applied
    if previous_applied_value is MISSING and previous_desired_value is not MISSING:
        previous_applied_value = previous_desired_value
    current_local_value = current_local if current_local is not MISSING else {}

    conflicts = []
    final_document = _merge_node(
        (),
        previous_applied_value,
        previous_desired_value,
        current_local_value,
        current_desired,
        ownership,
        conflicts,
    )
    if final_document is MISSING:
        final_document = {}
    planned_ops = diff_documents(current_local_value, final_document)
    return MergeResult(
        conflicts=conflicts,
        final_document=final_document,
        planned_ops=planned_ops,
    )
