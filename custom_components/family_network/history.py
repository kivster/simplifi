"""Protected, bounded per-run history; compact logbook events carry caller attribution."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from typing import Any

from homeassistant.components.logbook import async_log_entry
from homeassistant.core import Context

from .checked_store import CheckedStore as Store
from .const import DOMAIN
from .models import Conflict, instant, uid, utcnow

MAX_RUNS = 10000


def page(rows, *, before_id=None, limit=50, outcome=None):
    ordered = list(reversed(rows))
    if outcome:
        ordered = [r for r in ordered if r.get("outcome") == outcome]
    if before_id:
        offset = next((i for i, r in enumerate(ordered) if r["id"] == before_id), None)
        if offset is None:
            raise Conflict("This history cursor expired; return to newest records")
        ordered = ordered[offset + 1 :]
    selected = ordered[:limit]
    return {
        "items": deepcopy(selected),
        "next_cursor": selected[-1]["id"] if len(ordered) > limit else None,
    }


class RunHistory:
    def __init__(self, hass, entry_id):
        self.hass = hass
        self.store: Store[dict] = Store(hass, 1, f"{DOMAIN}.{entry_id}.history")
        self.lock = asyncio.Lock()
        self.data: dict[str, Any] = {"runs": [], "outcomes": {}}

    async def load(self, state):
        raw = await self.store.async_load()
        if raw is None:
            self.data["outcomes"] = {c["id"]: [c["outcome"]] for c in state.changes}
        else:
            self.data = raw
            for run in self.data["runs"]:
                if run["outcome"] == "running":
                    run["outcome"] = "interrupted"
                    run["issue"] = (
                        "Home Assistant stopped before this run completed; no success is assumed"
                    )
        await self.store.async_save(self.data)

    async def start(self, state, now):
        async with self.lock:
            cutoff = now - timedelta(days=state.audit_days)
            self.data["runs"] = [
                r for r in self.data["runs"] if instant(r["started_at"]) >= cutoff
            ][-(MAX_RUNS - 1) :]
            run_id = uid()
            self.data["runs"].append(
                {
                    "id": run_id,
                    "started_at": now.isoformat(),
                    "started_revision": state.revision,
                    "revision": state.revision,
                    "outcome": "running",
                }
            )
            await self.store.async_save(self.data)
            return run_id

    async def finish(self, run_id, state, operations, success, duration_ms, *, interrupted=False):
        async with self.lock:
            run = next(r for r in self.data["runs"] if r["id"] == run_id)
            run.update(
                finished_at=utcnow().isoformat(),
                revision=state.revision,
                duration_ms=duration_ms,
                outcome="interrupted"
                if interrupted
                else state.sync_status
                if success
                else "failed",
                confirmed_revision=state.confirmed_revision,
                devices=len(state.devices),
                owned_policies=len(state.owned),
                writes={
                    a: sum(j["action"] == a for j in operations)
                    for a in ("create", "update", "delete")
                },
                unresolved=sum(j["status"] != "verified" for j in state.journal),
                issue="Integration stopped before this run completed"
                if interrupted
                else None
                if success
                else state.issue or "Sync did not complete; inspect recovery",
            )
            await self.store.async_save(self.data)
        await self.observe_changes(state.changes)

    async def observe_changes(self, changes):
        changes = deepcopy(changes)
        async with self.lock:
            pending = [
                c for c in changes if c["outcome"] not in self.data["outcomes"].get(c["id"], [])
            ]
            if not pending:
                return
            for change in pending:
                self.data["outcomes"].setdefault(change["id"], []).append(change["outcome"])
            self.data["outcomes"] = dict(list(self.data["outcomes"].items())[-2000:])
            # Durable receipts suppress replay on restart. A crash after this save
            # can omit a logbook projection, but the protected change is retained.
            await self.store.async_save(self.data)
            for change in pending:
                async_log_entry(
                    self.hass,
                    "SimpliFi",
                    f"{change['action'].replace('_', ' ')}: {change['outcome'].replace('_', ' ')} (revision {change['revision']})",
                    domain=DOMAIN,
                    context=Context(user_id=change["actor"]),
                )

    async def read(self, **kwargs):
        async with self.lock:
            return {
                **page(self.data["runs"], **kwargs),
                "capacity": MAX_RUNS,
                "retained": len(self.data["runs"]),
            }

    async def for_change(self, change, **query):
        """Link attempts to the exact saved revision, without rewriting its outcome."""
        async with self.lock:
            rows = [
                r
                for r in self.data["runs"]
                if r.get("revision") == change["revision"]
                and instant(r.get("finished_at") or r["started_at"])
                >= instant(change["requested_at"])
            ]
            return {
                **page(rows, **query),
                "capacity": MAX_RUNS,
                "retained": len(rows),
                "latest": deepcopy(rows[-1]) if rows else None,
                "change": deepcopy(change),
            }
