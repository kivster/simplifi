"""Read-only person rule summaries, keeping continuous restrictions out of clock rows."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .const import STALE_SECONDS
from .models import instant
from .planner import lifted, rule_devices
from .schedule import occurrences, rule_active


def labels(gateway):
    return {
        kind: {r["id"]: r["name"] for r in getattr(gateway, attribute, ())}
        for kind, attribute in (("category", "categories"), ("application", "applications"))
    }


def target_labels(rule, catalogues):
    if rule.kind == "internet":
        return [{"id": None, "name": "All internet", "known": True}]
    result = []
    for identity in rule.targets:
        name = catalogues.get(rule.kind, {}).get(identity)
        known = isinstance(name, str) and bool(name.strip()) or rule.kind == "domain"
        result.append(
            {
                "id": identity,
                "name": str(identity)
                if rule.kind == "domain"
                else name
                if known
                else f"Unknown {rule.kind} (ID {identity})",
                "known": known,
            }
        )
    return result


def day_bounds(now, timezone):
    zone = ZoneInfo(timezone)
    start = datetime.combine(now.astimezone(zone).date(), time(), zone)
    return start, start + timedelta(days=1)


def summary(state, group_id, now, confirmed, catalogues, *, visible_rules=None):
    start, end = day_bounds(now, state.timezone)
    members = [
        d for d in state.devices.values() if d.group == group_id and d.network in state.networks
    ]
    coverage_fresh = bool(
        state.inventory_complete
        and state.last_observed
        and 0 <= (now - instant(state.last_observed)).total_seconds() < STALE_SECONDS
    )
    rows = []
    always_internet = all_day_internet = False
    for rule in state.rules.values():
        if visible_rules is not None and rule.id not in visible_rules:
            continue
        covered = rule_devices(state, rule, group_id)
        if group_id not in rule.groups and not covered:
            continue
        always = not rule.windows
        all_day = any(
            w.all_day and any(occurrences(w, start, end, state.timezone)) for w in rule.windows
        )
        if not always and not all_day:
            continue
        active = rule_active(rule, now, state.timezone)
        allowed = lifted(state, rule.id, group_id, now)
        if (
            rule.kind == "internet"
            and active
            and not allowed
            and covered
            and not state.groups[group_id].archived
        ):
            always_internet |= always
            all_day_internet |= all_day
        if state.groups[group_id].archived:
            status, label = "unmanaged", "Archived person"
        elif not rule.enabled:
            status, label = "disabled", "Disabled"
        elif not covered:
            status, label = "no_devices", "No managed devices"
        elif not state.management:
            status, label = "saved", "Saved · management off"
        elif not active:
            status, label = "inactive", "Inactive now"
        elif not confirmed:
            status, label = "unknown", "Allowance unconfirmed" if allowed else "Rule unconfirmed"
        elif allowed:
            status, label = "allowed", "Temporarily lifted"
        else:
            status, label = (
                ("partial", "Some devices restricted")
                if len(covered) < len(members)
                else ("restricted", "Rule active")
            )
        rows.append(
            {
                "rule_id": rule.id,
                "name": rule.name,
                "kind": rule.kind,
                "mode": "always_on" if always else "all_day_today",
                "enabled": rule.enabled,
                "active": active,
                "lifted": allowed,
                "state": status,
                "label": label,
                "targets": target_labels(rule, catalogues),
                "covered_devices": len(covered),
                "devices": len(members),
                "coverage_fresh": coverage_fresh,
                "network_scope": bool(rule.networks),
                "person_control": group_id in rule.groups and not rule.networks,
            }
        )
    return {
        "rule_rows": rows,
        "always_on_internet": always_internet,
        "all_day_internet": all_day_internet,
    }
