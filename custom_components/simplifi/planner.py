"""Explicit network scope for every policy; group rules additionally require a MAC."""

from datetime import datetime, timedelta
from typing import Any

from .const import MAX_POLICIES
from .models import CapabilityError, SimpliFiError, State, fingerprint, instant
from .schedule import gateway_schedules, occurrences, rule_active


def rule_devices(state: State, rule, group: str) -> list:
    """Current in-scope coverage, including network rules affecting a group's devices."""
    return [
        d
        for d in state.devices.values()
        if d.group == group
        and d.network in state.networks
        and (group in rule.groups or d.network in rule.networks)
    ]


def lifted(state: State, rule: str, group: str | None, now: datetime) -> bool:
    for exc in state.exceptions.values():
        if not exc.active(now):
            continue
        if (
            exc.kind == "internet_allow"
            and exc.group == group
            and rule in exc.captured
            and not state.rules[rule].networks
        ):
            return True
        if (
            exc.kind in ("suspension", "rule_allow")
            and exc.rule == rule
            and (exc.group is None or not state.rules[rule].networks and exc.group == group)
        ):
            return True
    return False


def group_status(state: State, group: str, now: datetime) -> dict[str, Any]:
    members = [
        d for d in state.devices.values() if d.group == group and d.network in state.networks
    ]
    active = [e for e in state.exceptions.values() if e.group == group and e.active(now)]
    restrictions = [
        r
        for r in state.rules.values()
        if rule_devices(state, r, group)
        and r.kind == "internet"
        and rule_active(r, now, state.timezone)
        and not lifted(state, r.id, group, now)
    ]
    pause = next((e for e in active if e.kind == "pause"), None)
    allowances = [
        e
        for e in state.exceptions.values()
        if e.active(now)
        and (
            e.kind == "internet_allow"
            and e.group == group
            or e.kind == "rule_allow"
            and e.rule in state.rules
            and state.rules[e.rule].kind == "internet"
            and group in state.rules[e.rule].groups
            and e.group in (None, group)
        )
    ]
    allowance = min(
        allowances,
        key=lambda e: instant(e.expires_at).timestamp() if e.expires_at else float("inf"),
        default=None,
    )
    network_rules = [r for r in restrictions if r.networks]
    blocked_devices = {d.id for r in restrictions for d in rule_devices(state, r, group)}
    network_devices = {d.id for r in network_rules for d in rule_devices(state, r, group)}
    if not members or state.groups[group].archived:
        status = "unmanaged"
    elif not state.inventory_complete:
        status = "unknown"
    elif pause:
        status = "paused"
    elif network_rules:
        status = "network_blocked" if len(blocked_devices) == len(members) else "partially_blocked"
    elif restrictions:
        status = "scheduled_block"
    elif allowance:
        status = "allowed"
    else:
        status = "available"
    relevant = pause or allowance
    return {
        "state": status,
        "reason": (
            f"Network restrictions affect {len(network_devices)} of {len(members)} devices. "
            "A person's allowance cannot override them. "
            if network_rules and not pause
            else ""
        )
        + (
            pause.reason
            if pause
            else ", ".join(r.name for r in restrictions)
            or (allowance.reason if allowance else "Content restrictions may still apply")
        ),
        "actor": relevant.actor if relevant else None,
        "expires_at": relevant.expires_at if relevant else None,
        "rules": [r.id for r in restrictions],
        "network_rules": [r.id for r in network_rules],
        "blocked_devices": len(members) if pause else len(blocked_devices),
        "devices": len(members),
        "connected": sum(d.connected for d in members),
        "management_enabled": state.management,
    }


def next_change(state: State, group: str, now: datetime) -> datetime | None:
    """Skip boundaries that do not alter internet state/reasons (overlap aware)."""
    horizon = now + timedelta(days=8)
    points = {
        instant(e.expires_at)
        for e in state.exceptions.values()
        if e.expires_at
        and e.active(now)
        and (
            e.group == group
            or e.rule in state.rules
            and rule_devices(state, state.rules[e.rule], group)
        )
    }
    for rule in state.rules.values():
        if rule_devices(state, rule, group) and rule.enabled and rule.kind == "internet":
            for window in rule.windows:
                for a, b in occurrences(window, now, horizon, state.timezone):
                    points.update(p for p in (a, b) if p > now)
    before = group_status(state, group, now)
    for point in sorted(points):
        after = group_status(state, group, point)
        if any(before[k] != after[k] for k in ("state", "rules", "expires_at", "blocked_devices")):
            return point
        before = after
    return None


def plan(
    state: State,
    networks: dict[str, dict],
    external_zone: str,
    catalogues: dict[str, set[int]],
    now: datetime,
) -> dict[str, dict]:
    if not state.inventory_complete:
        raise SimpliFiError("Complete inventory is required; keeping the last policies")
    if not external_zone:
        raise CapabilityError("Select and verify the internet destination zone")
    if any(n not in networks or not networks[n].get("zone") for n in state.networks):
        raise CapabilityError("Selected network/zone mapping is unavailable")
    result: dict[str, dict] = {}

    def add(
        key: str,
        network_id: str,
        mac: str | None,
        kind: str,
        targets: list,
        schedule: dict | None,
        enabled: bool = True,
    ):
        network = networks[network_id]
        destination: dict[str, Any] = {"zoneId": external_zone}
        if kind == "category":
            destination["trafficFilter"] = {
                "type": "APPLICATION_CATEGORY",
                "applicationCategoryFilter": {"applicationCategoryIds": targets},
            }
        elif kind == "application":
            destination["trafficFilter"] = {
                "type": "APPLICATION",
                "applicationFilter": {"applicationIds": targets},
            }
        elif kind == "domain":
            destination["trafficFilter"] = {
                "type": "DOMAIN",
                "domainFilter": {"type": "DOMAINS", "domains": targets},
            }
        body = {
            "name": f"SimpliFi {key[:90]}",
            "enabled": enabled,
            "action": {"type": "BLOCK"},
            "source": {
                "zoneId": network["zone"],
                "trafficFilter": {
                    "type": "NETWORK",
                    "networkFilter": {"networkIds": [network_id], "matchOpposite": False},
                    **({"macAddressFilter": mac} if mac is not None else {}),
                },
            },
            "destination": destination,
            "ipProtocolScope": {"ipVersion": "IPV4_AND_IPV6"},
            "loggingEnabled": False,
        }
        if schedule:
            body["schedule"] = schedule
        result[key] = body

    for rule in state.rules.values():
        if rule.kind in ("category", "application") and any(
            t not in catalogues.get(rule.kind, set()) for t in rule.targets
        ):
            raise CapabilityError("Target ID is absent from the complete gateway catalogue")
        schedules = (
            [("always", None)]
            if not rule.windows
            else [
                (f"{w.id}:{i}", schedule)
                for w in rule.windows
                for i, schedule in enumerate(gateway_schedules(w))
            ]
        )
        if rule.windows and not state.gateway_timezone_confirmed:
            raise CapabilityError(
                "Gateway timezone/schedule parity must be confirmed before recurring writes"
            )
        for network_id in rule.networks:
            if network_id not in state.networks:
                raise CapabilityError("Rule network is outside the selected managed scope")
            for suffix, schedule in schedules:
                add(
                    f"rule:{rule.id}:network:{network_id}:{suffix}",
                    network_id,
                    None,
                    rule.kind,
                    rule.targets,
                    schedule,
                    rule.enabled and not lifted(state, rule.id, None, now),
                )
        for group in rule.groups:
            enabled = (
                rule.enabled
                and not state.groups[group].archived
                and not lifted(state, rule.id, group, now)
            )
            for device in state.devices.values():
                if device.group == group and device.network in state.networks:
                    for suffix, schedule in schedules:
                        add(
                            f"rule:{rule.id}:{group}:{device.mac}:{suffix}",
                            device.network,
                            device.mac,
                            rule.kind,
                            rule.targets,
                            schedule,
                            enabled,
                        )
    for household_group in state.groups.values():
        if household_group.archived:
            continue
        if any(
            e.kind == "pause" and e.group == household_group.id and e.active(now)
            for e in state.exceptions.values()
        ):
            for device in state.devices.values():
                if device.group == household_group.id and device.network in state.networks:
                    add(
                        f"pause:{household_group.id}:{device.mac}",
                        device.network,
                        device.mac,
                        "internet",
                        [],
                        None,
                    )
    quarantine_active = state.quarantine and not state.quarantine_paused(now)
    for device in state.devices.values():
        key = f"quarantine:{device.mac}"
        if (
            device.group is None
            and device.network in state.networks
            and device.id not in state.quarantine_excluded
            and (quarantine_active or key in state.owned)
        ):
            add(key, device.network, device.mac, "internet", [], None, quarantine_active)
    if len(result) > MAX_POLICIES:
        raise CapabilityError(f"Plan exceeds the local {MAX_POLICIES}-policy safety cap")
    return result


def policy_fingerprint(policy: dict) -> str:
    return fingerprint(
        {k: v for k, v in policy.items() if k not in ("id", "index", "metadata") and v is not None}
    )


def _comparison_fields(policy: dict) -> dict:
    fields = {
        k: v for k, v in policy.items() if k not in ("id", "index", "metadata") and v is not None
    }
    schedule = fields.get("schedule")
    if isinstance(schedule, dict) and schedule.get("mode") == "EVERY_WEEK":
        days = schedule.get("repeatOnDays")
        weekdays = {"MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"}
        if (
            isinstance(days, list)
            and days
            and all(isinstance(day, str) and day in weekdays for day in days)
            and len(days) == len(set(days))
        ):
            # UniFi returns Sunday first. Only this documented set is unordered;
            # selectors, unknown fields, times and malformed schedules stay strict.
            fields["schedule"] = {**schedule, "repeatOnDays": sorted(days)}
    return fields


def policy_matches(actual: dict | None, recorded: dict | None, receipt: str) -> bool:
    """Compare readback semantics while preserving existing raw receipt hashes."""
    if not isinstance(actual, dict) or not isinstance(recorded, dict):
        return False
    if not isinstance(receipt, str) or policy_fingerprint(recorded) != receipt:
        return False
    return fingerprint(_comparison_fields(actual)) == fingerprint(_comparison_fields(recorded))
