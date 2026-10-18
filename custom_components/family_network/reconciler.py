"""Single-owner durable write journal. Call only under the engine's shared lock."""

from copy import deepcopy
from datetime import datetime
from typing import Protocol

from .models import Conflict, FamilyError, State, uid
from .planner import policy_fingerprint


class Gateway(Protocol):
    controller: str
    site: str

    async def list_policies(self) -> dict[str, dict]: ...
    async def create(self, body: dict) -> str: ...
    async def update(self, policy_id: str, body: dict) -> None: ...
    async def delete(self, policy_id: str) -> None: ...


class Reconciler:
    def __init__(self, gateway: Gateway, save, check_active):
        self.gateway = gateway
        self.save = save
        self.check_active = check_active

    async def apply(self, state: State, desired: dict[str, dict], now: datetime) -> None:
        if (state.controller, state.site) != (self.gateway.controller, self.gateway.site):
            raise Conflict("Controller/site identity changed; writer frozen")
        actual = await self.gateway.list_policies()  # Must be a complete validated read.
        for operation in state.journal:
            if operation["status"] == "verified":
                continue
            policy_id = operation.get("returned_id") or operation.get("policy_id")
            if operation["action"] == "create" and not policy_id:
                raise Conflict(
                    "Uncertain create: review operation evidence; automatic retry is frozen"
                )
            current = actual.get(policy_id) if policy_id else None
            if operation["action"] == "delete" and current is None:
                state.owned.pop(operation["key"], None)
                operation["status"] = "verified"
            elif (
                operation["action"] != "delete"
                and current
                and policy_fingerprint(current) == operation["fingerprint"]
            ):
                state.owned[operation["key"]] = self._owned(state, operation, current, now)
                operation["status"] = "verified"
            elif (
                operation["action"] in ("update", "delete")
                and current
                and policy_fingerprint(current) == operation["pre_fingerprint"]
            ):
                # A timed-out server request can still finish after this read.
                # Seeing the pre-image is not evidence that the request ended.
                raise Conflict(
                    "Original policy is still present; request completion is uncertain. "
                    "Wait for readback or review recovery before retrying"
                )
            else:
                raise Conflict("Unresolved write or readback mismatch; writer frozen")
            await self.save(state)
        for record in state.owned.values():
            if (record["controller"], record["site"]) != (state.controller, state.site):
                raise Conflict("Owned-policy record belongs to another controller")
            current = actual.get(record["id"])
            if current and policy_fingerprint(current) != record["fingerprint"]:
                raise Conflict("Owned policy was edited externally; refusing to overwrite")
        state.sync_status = "applying"
        await self.save(state)
        for key in sorted(set(state.owned) | set(desired)):
            # Unload drains the current request and its journal receipt, then
            # stops before another policy write can start from this instance.
            self.check_active()
            owned = state.owned.get(key)
            current = actual.get(owned["id"]) if owned else None
            body = desired.get(key)
            if body is None and current is None:
                state.owned.pop(key, None)
                continue
            if (
                body is not None
                and current is not None
                and policy_fingerprint(current) == policy_fingerprint(body)
            ):
                continue
            action = "delete" if body is None else "update" if current is not None else "create"
            operation = {
                "id": uid(),
                "revision": state.revision,
                "key": key,
                "action": action,
                "status": "intent",
                "created_at": now.isoformat(),
                "policy_id": owned["id"] if owned and current else None,
                "pre_image": deepcopy(current),
                "pre_fingerprint": policy_fingerprint(current) if current else None,
                "fingerprint": policy_fingerprint(body) if body else None,
            }
            if body:
                # This opaque marker records the creating operation. It is never ownership on its own.
                body = (
                    {**body, "description": f"family_network operation {operation['id']}"}
                    if action == "create"
                    else {**body, "description": current.get("description", "") if current else ""}
                )
                operation["fingerprint"] = policy_fingerprint(body)
                operation["body"] = body
            state.journal.append(operation)
            await self.save(state)  # Intent is durable BEFORE the external effect.
            try:
                if action == "create":
                    assert body is not None
                    operation["returned_id"] = await self.gateway.create(body)
                    await self.save(state)  # Preserve returned-ID evidence before readback.
                elif action == "update":
                    assert owned is not None and body is not None
                    await self.gateway.update(owned["id"], body)
                else:
                    assert owned is not None
                    await self.gateway.delete(owned["id"])
            except TimeoutError, FamilyError:
                operation["status"] = "uncertain"
                await self.save(state)
                raise Conflict(
                    "Gateway response uncertain; retained journal for readback"
                ) from None
            actual = await self.gateway.list_policies()
            policy_id = operation.get("returned_id") or operation["policy_id"]
            confirmed = actual.get(policy_id)
            if action == "delete":
                if confirmed is not None:
                    raise Conflict("Deletion not confirmed")
                state.owned.pop(key, None)
            else:
                if not confirmed or policy_fingerprint(confirmed) != operation["fingerprint"]:
                    raise Conflict("Policy readback did not match requested fields")
                state.owned[key] = self._owned(state, operation, confirmed, now)
            operation["status"] = "verified"
            await self.save(state)
        state.confirmed_revision = state.revision
        state.sync_status = "applied"
        state.issue = None
        for change in state.changes:
            if change["revision"] == state.revision and change["outcome"] in (
                "pending",
                "applying",
            ):
                change["outcome"] = "applied"
                change["applied_at"] = now.isoformat()
            elif change["revision"] < state.revision and change["outcome"] in (
                "pending",
                "applying",
            ):
                change["outcome"] = "superseded"
        await self.save(state)

    @staticmethod
    def _owned(state, operation, policy, now):
        return {
            "controller": state.controller,
            "site": state.site,
            "id": policy["id"],
            "operation": operation["id"],
            "fingerprint": policy_fingerprint(policy),
            "readback_at": now.isoformat(),
            "body": deepcopy(policy),
        }
