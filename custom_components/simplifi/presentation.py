"""Administrator dashboard read model. No credentials or policy write bodies."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .compatibility import snapshot as compatibility_snapshot
from .const import STALE_SECONDS, VERSION
from .group_controls import summary as unblock_summary
from .models import instant
from .planner import group_status, lifted, next_change, rule_devices
from .rule_summary import summary as rule_summary
from .rule_summary import target_labels
from .schedule import occurrences, rule_active


async def dashboard_data(hass, entry):
    coordinator = entry.runtime_data
    engine = coordinator.engine
    async with engine.lock:
        state = deepcopy(engine.state)
        gateway = engine.gateway
        categories = deepcopy(gateway.categories)
        applications = deepcopy(gateway.applications)
        networks = deepcopy(gateway.networks)
        capabilities = deepcopy(gateway.capabilities)
        compatibility = compatibility_snapshot(gateway)
        now = engine.clock()
        configuration_confirmed = engine.configuration_confirmed(now)
    fresh = bool(
        coordinator.last_update_success
        and state.inventory_complete
        and state.last_observed
        and now - instant(state.last_observed) < timedelta(seconds=STALE_SECONDS)
    )
    confirmed = fresh and configuration_confirmed
    actors = {c["actor"] for c in state.changes}
    actors.update(e.actor for e in state.exceptions.values())
    names = {}
    for actor in actors:
        user = await hass.auth.async_get_user(actor)
        names[actor] = user.name if user else "Former administrator"
    labels = {
        kind: {row["id"]: row["name"] for row in rows}
        for kind, rows in (("category", categories), ("application", applications))
    }
    zone = ZoneInfo(state.timezone)
    start = datetime.combine(now.astimezone(zone).date(), time(), zone)
    end = start + timedelta(days=1)
    rules = []
    for rule in state.rules.values():
        rules.append(
            {
                **asdict(rule),
                "active": rule_active(rule, now, state.timezone),
                "target_names": [t["name"] for t in target_labels(rule, labels)],
                "affected_groups": [g for g in state.groups if rule_devices(state, rule, g)],
            }
        )
    protection = coordinator.protection.snapshot(now)
    protection["last_edit"] = await coordinator.protection_editor.status()
    coexistence = coordinator.coexistence.snapshot(now, state)
    groups = []
    for group in state.groups.values():
        status = group_status(state, group.id, now)
        status["actor"] = names.get(status["actor"])
        status["control_state"] = status["state"]
        if not confirmed and status["state"] != "unmanaged":
            status["state"] = "unknown"
        upcoming = next_change(state, group.id, now)
        timeline = []
        for rule in state.rules.values():
            if (
                not (group.id in rule.groups or rule_devices(state, rule, group.id))
                or not rule.enabled
            ):
                continue
            spans = [
                span
                for window in rule.windows
                if not window.all_day
                for span in occurrences(window, start, end, state.timezone)
            ]
            for a, b in spans:
                timeline.append(
                    {
                        "rule_id": rule.id,
                        "name": rule.name,
                        "kind": rule.kind,
                        "start": max(a, start).isoformat(),
                        "end": min(b, end).isoformat(),
                        "lifted_now": lifted(state, rule.id, group.id, now),
                    }
                )
        from .filter_status import category_marks

        marks, inherited_protection = category_marks(
            state,
            networks,
            group.id,
            {**protection, "fresh": protection["fresh"] and fresh},
            confirmed,
            labels["category"],
            now,
        )
        groups.append(
            {
                **asdict(group),
                **status,
                **rule_summary(state, group.id, now, confirmed, labels),
                "unblock": unblock_summary(state, group.id, now),
                "next_change": upcoming.isoformat() if upcoming else None,
                "next_state": group_status(state, group.id, upcoming)["state"]
                if upcoming
                else None,
                "timeline": sorted(timeline, key=lambda row: row["start"]),
                "categories": marks,
                "protection": inherited_protection,
                "other_policies": [
                    p["id"]
                    for p in coexistence["policies"]
                    if p["ownership"] in ("external", "drift")
                    and p["enabled"]
                    and p["action"] in ("BLOCK", "REJECT")
                    and group.id in p["matched_groups"]
                ],
                "possible_other_policies": [
                    p["id"]
                    for p in coexistence["policies"]
                    if p["ownership"] in ("external", "drift")
                    and p["enabled"]
                    and p["action"] in ("BLOCK", "REJECT")
                    and group.id in p["possible_groups"]
                ],
            }
        )
    exceptions = [
        {**asdict(e), "actor": names.get(e.actor)}
        for e in state.exceptions.values()
        if e.active(now)
    ]
    changes = [
        {k: deepcopy(v) for k, v in c.items() if k not in ("digest", "request_id")}
        for c in reversed(state.changes[-100:])
    ]
    sync_evidence = await coordinator.storage.history.summaries(changes)
    for change in changes:
        if change["id"] in sync_evidence:
            change["sync_evidence"] = sync_evidence[change["id"]]
        change["actor"] = names.get(change["actor"])
        targets = change.get("targets", {})
        group_ids = targets.get("groups", []) + (
            [targets["group_id"]] if targets.get("group_id") else []
        )
        change["target_names"] = [state.groups[g].name for g in group_ids if g in state.groups]
        change["target_names"].extend(
            networks.get(n, {}).get("name", n) for n in targets.get("networks", [])
        )
        if targets.get("rule_id") in state.rules:
            change["target_names"].append(state.rules[targets["rule_id"]].name)
    from .dns_context import observation

    dns_views: dict[str, dict[str, Any]] = {}
    for key, probe in state.probes.items():
        targets = [probe.get("group_id")] if probe.get("group_id") else [None, *state.groups]
        dns_views[key] = {}
        for target in targets:
            view = observation(state, networks, key, target, now)
            for context in view["contexts"]:
                context.pop("result", None)
            dns_views[key][target or "household"] = view
    return {
        "version": VERSION,
        "inventory_readback": gateway.current_network_reader.snapshot(now)
        if getattr(gateway, "current_network_reader", None)
        else None,
        "updates": entry.runtime_data.updates.status()
        if hasattr(entry.runtime_data, "updates")
        else None,
        "entry_id": entry.entry_id,
        "simulation": entry.data["simulation"],
        "revision": state.revision,
        "confirmed_revision": state.confirmed_revision,
        "fresh": fresh,
        "confirmed": confirmed,
        "management": state.management,
        "sync": "pending"
        if fresh and state.management and state.sync_status == "applied" and not confirmed
        else state.sync_status,
        "issue": state.issue,
        "unresolved_operations": sum(j["status"] != "verified" for j in state.journal),
        "last_observed": state.last_observed,
        "now": now.isoformat(),
        "timezone": state.timezone,
        "day_start": start.isoformat(),
        "day_end": end.isoformat(),
        "groups": groups,
        "rules": rules,
        "devices": [asdict(d) for d in state.devices.values()],
        "networks": networks,
        "managed_networks": list(state.networks),
        "exceptions": exceptions,
        "changes": changes,
        "quarantine": state.quarantine,
        "quarantine_until": state.quarantine_until,
        "quarantine_paused": state.quarantine_paused(now),
        "quarantine_rule": {
            "enabled": state.quarantine,
            "paused": state.quarantine_paused(now),
            "expires_at": state.quarantine_until if state.quarantine_paused(now) else None,
            "can_control": True,
            "can_toggle": True,
        },
        "quarantine_excluded": state.quarantine_excluded,
        "probes": deepcopy(state.probes),
        "probe_results": deepcopy(state.probe_results),
        "probe_schedule": deepcopy(state.probe_schedule),
        "dns_settings": deepcopy(state.dns_settings),
        "dns_revision": state.dns_revision,
        "dns_views": dns_views,
        "dns_progress": deepcopy(coordinator.dns_progress),
        "capabilities": capabilities,
        "compatibility": compatibility,
        "protection": protection,
        "coexistence": coexistence,
        "expiry_acknowledged": state.expiry_acknowledged,
        "gateway_timezone_confirmed": state.gateway_timezone_confirmed,
        "categories": categories,
    }


def dashboard_catalogue(entry, kind, query):
    rows = getattr(
        entry.runtime_data.engine.gateway, "categories" if kind == "category" else "applications"
    )
    matches = [r for r in rows if query.casefold() in r["name"].casefold()]
    return {
        "items": [{"id": r["id"], "name": r["name"]} for r in matches[:100]],
        "total": len(matches),
        "capped": len(matches) > 100,
    }
