"""Read-only recovery evidence and explicit administrator resolution of uncertain writes."""

from copy import deepcopy
from datetime import timedelta

from .models import Conflict, SimpliFiError, fingerprint, instant
from .planner import policy_fingerprint
from .reconciler import Reconciler


def operation_for(state, operation_id):
    operation = next((j for j in state.journal if j["id"] == operation_id), None)
    if not operation or operation["status"] == "verified":
        raise Conflict("This operation is already resolved or no longer exists; refresh recovery")
    return operation


def evidence(state, operation, actual, actor, now):
    """A name alone is never ownership. Require our durable operation marker and full body."""
    marker = f"simplifi operation {operation['id']}"
    known_ids = {r["id"] for k, r in state.owned.items() if k != operation["key"]}
    candidates = [
        p
        for key, p in actual.items()
        if key not in known_ids
        and p.get("description") == marker
        and policy_fingerprint(p) == operation["fingerprint"]
    ]
    marked = [p for p in actual.values() if p.get("description") == marker]
    lost_create = operation["action"] == "create" and not operation.get("returned_id")
    candidate = candidates[0] if lost_create and len(candidates) == len(marked) == 1 else None
    old_enough = now - instant(operation["created_at"]) >= timedelta(minutes=2)
    # Absence is an observation, not proof a timed-out server request finished.
    # Closing absent therefore requires a separate administrator acknowledgement.
    can_close_absent = lost_create and not marked and old_enough
    policy_id = operation.get("policy_id")
    current = actual.get(policy_id)
    owner = state.owned.get(operation["key"], {})
    can_close_not_applied = bool(
        operation["action"] in ("update", "delete")
        and old_enough
        and current
        and owner.get("id") == policy_id
        and owner.get("fingerprint") == operation["pre_fingerprint"]
        and policy_fingerprint(current) == operation["pre_fingerprint"]
    )
    return {
        "operation_id": operation["id"],
        "action": operation["action"],
        "created_at": operation["created_at"],
        "revision": operation["revision"],
        "key": operation["key"],
        "status": operation["status"],
        "candidate_id": candidate["id"] if candidate else None,
        "marked_candidates": len(marked),
        "exact_candidates": len(candidates),
        "can_close_absent": can_close_absent,
        "can_close_not_applied": can_close_not_applied,
        "policy_id": policy_id,
        "requested_policy": deepcopy(operation.get("body")),
        "previous_policy": deepcopy(operation.get("pre_image")),
        "preview_hash": fingerprint(
            {"operation": operation, "actual": actual, "actor": actor, "revision": state.revision}
        ),
        "message": "One policy exactly matches the recorded request and operation marker. Confirm to attach its returned identity and replan current intent."
        if candidate
        else "No marked policy was found. Only close this request after independently checking in UniFi that the original request has finished without creating a policy. Otherwise wait and refresh."
        if can_close_absent
        else "The known policy still matches its recorded previous state. This does not prove the request finished. Only close it after independently verifying the original update or delete ended without changing the policy."
        if can_close_not_applied
        else "Automatic retry remains frozen. Wait and refresh, or inspect the recorded request and controller policies. Changed, duplicate or still-pending policies cannot be adopted.",
    }


async def preview(state, gateway, actor, now, operation_id=None):
    if (state.controller, state.site) != (gateway.controller, gateway.site):
        raise Conflict("Controller/site binding changed; recovery is unavailable")
    actual = await gateway.list_policies()
    operations = (
        [operation_for(state, operation_id)]
        if operation_id
        else [j for j in state.journal if j["status"] != "verified"]
    )
    drift = [
        {
            "key": key,
            "policy_id": r["id"],
            "message": "Owned policy was edited externally. Review it in UniFi; recovery will not overwrite it.",
        }
        for key, r in state.owned.items()
        if r["id"] in actual and policy_fingerprint(actual[r["id"]]) != r["fingerprint"]
    ]
    return {
        "revision": state.revision,
        "operations": [evidence(state, j, actual, actor, now) for j in operations],
        "drift": drift,
        "observed_at": now.isoformat(),
        "policy_count": len(actual),
    }


async def resolve(state, gateway, payload, actor, now):
    if not payload["confirm"]:
        raise SimpliFiError("Review and confirm the selected recovery decision")
    view = await preview(state, gateway, actor, now, payload["operation_id"])
    row = view["operations"][0]
    if row["preview_hash"] != payload["preview_hash"]:
        raise Conflict("Recovery evidence changed; refresh and review it again")
    draft = deepcopy(state)
    operation = operation_for(draft, payload["operation_id"])
    if payload["decision"] == "attach":
        if not row["candidate_id"]:
            raise SimpliFiError("No unique exact policy can be attached")
        operation["returned_id"] = row["candidate_id"]
        policy = {**operation["body"], "id": row["candidate_id"]}
        draft.owned[operation["key"]] = Reconciler._owned(draft, operation, policy, now)
    elif payload["decision"] == "confirm_absent":
        if (
            not row["can_close_absent"]
            or not payload.get("request_finished")
            or not payload["reason"].strip()
        ):
            raise SimpliFiError(
                "Confirm the original UniFi request finished without a policy, and record how it was checked"
            )
        # Keep any previous returned identity: latest reconciliation checks it separately.
    elif payload["decision"] == "confirm_not_applied":
        if (
            not row["can_close_not_applied"]
            or not payload.get("request_finished")
            or not payload["reason"].strip()
        ):
            raise SimpliFiError(
                "Confirm the original UniFi update or delete finished without changing "
                "the policy, and record how it was checked"
            )
        # Retain the proven original ownership. Resolution itself makes no write;
        # the next sync plans from current intent only after request completion.
    else:
        raise SimpliFiError("Unknown recovery decision")
    operation.update(
        status="verified",
        outcome="administrator_" + payload["decision"],
        resolved_at=now.isoformat(),
        resolved_by=actor,
        resolution_reason=payload["reason"],
    )
    return draft
