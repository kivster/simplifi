"""Capture deadline evidence with accepted intent, never from later live state."""

from typing import Any

from .models import ExceptionRecord, State

START_ACTIONS = {
    "pause_internet",
    "allow_internet",
    "suspend_rule",
    "allow_rule",
    "suspend_quarantine",
    "unblock_group",
}
EXTEND_ACTIONS = {
    "extend_pause",
    "extend_rule_suspension",
    "extend_quarantine_suspension",
    "extend_group_unblock",
}
END_ACTIONS = {
    "resume_internet",
    "end_allowance",
    "resume_rule",
    "end_rule_allowance",
    "resume_quarantine",
    "revoke_access_grant",
    "end_group_unblock",
}


def _exception(state: State, record: ExceptionRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "kind": record.kind,
        "group_id": record.group,
        "group_name": state.groups[record.group].name if record.group in state.groups else None,
        "rule_id": record.rule,
        "rule_name": state.rules[record.rule].name if record.rule in state.rules else None,
        "captured_rules": [
            {"id": key, "name": state.rules[key].name if key in state.rules else key}
            for key in record.captured
        ],
        "created_at": record.created_at,
        "expires_at": record.expires_at,
    }


def _quarantine(state: State) -> dict[str, Any] | None:
    if not state.quarantine_suspended and not state.quarantine_until:
        return None
    return {
        "kind": "quarantine_suspension",
        "enabled": state.quarantine,
        "expires_at": state.quarantine_until,
    }


def _grant(user: str, value: dict | None) -> dict[str, Any] | None:
    return (
        None
        if value is None
        else {
            "kind": "access_grant",
            "user_id": user,
            "created_at": value["created_at"],
            "expires_at": value["expires_at"],
        }
    )


def capture(before: State, after: State, action: str, payload: dict) -> dict[str, Any] | None:
    """Return only changed timing records and whitelisted request fields.

    An absent record is different from an existing record with no deadline.
    Expired records retain their original deadline; this is intent evidence,
    not proof that the gateway applied the requested change at that instant.
    """
    changes: list[dict[str, Any]] = []
    for key in sorted(before.exceptions.keys() | after.exceptions.keys()):
        old, new = before.exceptions.get(key), after.exceptions.get(key)
        if old != new:
            changes.append(
                {
                    "id": key,
                    "before": _exception(before, old),
                    "after": _exception(after, new),
                }
            )
    old_quarantine, new_quarantine = _quarantine(before), _quarantine(after)
    if old_quarantine != new_quarantine:
        changes.append({"id": "quarantine", "before": old_quarantine, "after": new_quarantine})
    for user in sorted(before.access_grants.keys() | after.access_grants.keys()):
        old_grant, new_grant = before.access_grants.get(user), after.access_grants.get(user)
        if old_grant != new_grant:
            previous, resulting = _grant(user, old_grant), _grant(user, new_grant)
            if previous != resulting:
                changes.append({"id": user, "before": previous, "after": resulting})
    timed = action in START_ACTIONS | EXTEND_ACTIONS | END_ACTIONS | {
        "edit_allowance",
        "set_access_grant",
    }
    if not timed and not changes:
        return None
    request: dict[str, Any]
    if action in EXTEND_ACTIONS:
        request = {
            "mode": "extend_group_minutes"
            if action == "extend_group_unblock"
            else "extend_minutes",
            "value": payload["duration_minutes"],
        }
    elif action in END_ACTIONS:
        request = {"mode": "remove"}
    else:
        mode = next(
            (
                key
                for key in (
                    "duration_minutes",
                    "expires_at",
                    "next_window_end",
                    "indefinite",
                )
                if payload.get(key)
            ),
            None,
        )
        request = (
            {"mode": mode, "value": payload[mode]}
            if mode
            else {
                "mode": "indefinite"
                if action == "set_access_grant"
                else "default"
                if timed
                else "implicit",
            }
        )
    return {"version": 1, "timezone": before.timezone, "request": request, "changes": changes}
