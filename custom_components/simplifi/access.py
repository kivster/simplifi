"""Default-deny SimpliFi grants bound to an existing authenticated HA user."""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta

from .const import STALE_SECONDS
from .group_controls import ACTIONS as GROUP_UNBLOCK_ACTIONS
from .group_controls import summary as unblock_summary
from .models import SimpliFiError, instant
from .planner import group_status

SCOPES = ("read_only", "agent_controls", "watch_rules")
GROUP_CONTROLS = frozenset(
    {"pause_internet", "resume_internet", "extend_pause", "allow_internet", "end_allowance"}
    | GROUP_UNBLOCK_ACTIONS
)
RULE_CONTROLS = frozenset(
    {
        "suspend_rule",
        "resume_rule",
        "extend_rule_suspension",
        "allow_rule",
        "end_rule_allowance",
        "set_rule_enabled",
    }
)
QUARANTINE_CONTROLS = frozenset(
    {"suspend_quarantine", "extend_quarantine_suspension", "resume_quarantine"}
)
EDITOR_ACTIONS = frozenset(
    {"upsert_group", "delete_group", "assign_device", "forget_device", "upsert_rule", "delete_rule"}
)


def validate_grants(state):
    if not isinstance(state.access_grants, dict) or len(state.access_grants) > 100:
        raise SimpliFiError("At most 100 access grants are supported")
    for user_id, grant in state.access_grants.items():
        if (
            not isinstance(user_id, str)
            or not user_id
            or len(user_id) > 100
            or not isinstance(grant, dict)
            or set(grant)
            != {"scope", "groups", "networks", "all_groups", "expires_at", "actor", "created_at"}
            or grant["scope"] not in SCOPES
            or type(grant["all_groups"]) is not bool
            or any(
                not isinstance(grant[k], list) or any(not isinstance(v, str) for v in grant[k])
                for k in ("groups", "networks")
            )
            or len(set(grant["groups"])) != len(grant["groups"])
            or len(set(grant["networks"])) != len(grant["networks"])
            or not set(grant["groups"]) <= set(state.groups)
            or not set(grant["networks"]) <= set(state.networks)
            or not isinstance(grant["actor"], str)
            or not grant["actor"]
        ):
            raise SimpliFiError("Invalid explicit access scope")
        try:
            if (
                not isinstance(grant["created_at"], str)
                or grant["expires_at"] is not None
                and not isinstance(grant["expires_at"], str)
            ):
                raise SimpliFiError("Invalid access timestamp")
            instant(grant["created_at"])
            if grant["expires_at"] is not None:
                instant(grant["expires_at"])
        except (ValueError, TypeError, AttributeError) as err:
            raise SimpliFiError("Invalid access timestamp") from err


def grant_for(state, actor, now):
    grant = state.access_grants.get(actor)
    if not grant or grant["expires_at"] and instant(grant["expires_at"]) <= now:
        raise SimpliFiError("No active SimpliFi grant for this Home Assistant user")
    return grant


def groups_for(state, grant):
    return set(state.groups) if grant["all_groups"] else set(grant["groups"])


def whole_rule_allowed(rule, groups, networks):
    return bool(
        rule.groups
        and set(rule.groups) <= groups
        or rule.networks
        and set(rule.networks) <= networks
    )


def authorize(state, action, payload, actor, now):
    grant = grant_for(state, actor, now)
    if action == "access_status":
        return grant
    if grant["scope"] == "read_only":
        raise SimpliFiError("This grant allows read-only SimpliFi status")
    groups, networks = groups_for(state, grant), set(grant["networks"])
    group = payload.get("group_id") or None
    rule = state.rules.get(payload.get("rule_id"))
    allowed = False
    if action in GROUP_CONTROLS:
        allowed = group in groups
    elif action in RULE_CONTROLS:
        allowed = bool(
            rule
            and (
                group in groups and group in rule.groups
                if group
                else whole_rule_allowed(rule, groups, networks)
            )
        )
    elif action in QUARANTINE_CONTROLS:
        allowed = set(state.networks) <= networks
    elif action == "edit_allowance":
        exc = state.exceptions.get(payload.get("exception_id"))
        allowed = bool(
            exc
            and (
                exc.group in groups
                if exc.group
                else exc.rule in state.rules
                and whole_rule_allowed(state.rules[exc.rule], groups, networks)
            )
        )
    elif grant["scope"] == "agent_controls" and action in EDITOR_ACTIONS:
        if action in ("upsert_group", "delete_group"):
            allowed = (
                group in groups
                or action == "upsert_group"
                and grant["all_groups"]
                and group not in state.groups
            )
        elif action in ("assign_device", "forget_device"):
            device = state.devices.get(payload.get("device_id"))
            allowed = bool(
                device
                and (device.group in groups if device.group else device.network in networks)
                and (
                    action == "forget_device"
                    or group in groups
                    or group is None
                    and device.network in networks
                )
            )
        elif action == "delete_rule":
            allowed = bool(rule and whole_rule_allowed(rule, groups, networks))
        elif action == "upsert_rule":
            allowed = (rule is None or whole_rule_allowed(rule, groups, networks)) and bool(
                payload["groups"]
                and set(payload["groups"]) <= groups
                and not payload["networks"]
                or payload["networks"]
                and set(payload["networks"]) <= networks
                and not payload["groups"]
            )
    if not allowed:
        raise SimpliFiError("This action or target is outside your SimpliFi grant")
    return grant


def status(state, actor, now, *, confirmed=False, gateway=None):
    from .rule_summary import labels, summary, target_labels

    grant = grant_for(state, actor, now)
    groups = groups_for(state, grant)
    networks = set(grant["networks"])
    rules = [
        r for r in state.rules.values() if set(r.groups) & groups or set(r.networks) & networks
    ]
    visible_rules = {r.id for r in rules}
    catalogue_labels = labels(gateway)
    fresh = bool(
        state.inventory_complete
        and state.last_observed
        and now - instant(state.last_observed) < timedelta(seconds=STALE_SECONDS)
    )
    group_rows = []
    for g in state.groups.values():
        if g.id not in groups:
            continue
        row = group_status(state, g.id, now)
        row.pop("actor", None)
        row.pop("reason", None)
        row["rules"] = [r for r in row["rules"] if r in visible_rules]
        row["network_rules"] = [r for r in row["network_rules"] if r in visible_rules]
        row["confirmed"] = fresh and confirmed
        row["control_state"] = row["state"]
        row["unblock"] = unblock_summary(state, g.id, now)
        row.update(
            summary(
                state, g.id, now, row["confirmed"], catalogue_labels, visible_rules=visible_rules
            )
        )
        if not row["confirmed"]:
            row["state"] = "unknown"
        group_rows.append({"id": g.id, "name": g.name, "kind": g.kind, **row})
    exceptions = []
    for e in state.exceptions.values():
        if e.active(now) and (
            e.group in groups
            if e.group
            else e.rule in state.rules and whole_rule_allowed(state.rules[e.rule], groups, networks)
        ):
            row = {k: v for k, v in asdict(e).items() if k not in ("actor", "reason")}
            row["captured"] = [r for r in row["captured"] if r in visible_rules]
            exceptions.append(row)
    changes = []
    for c in state.changes[-100:]:
        targets = c.get("targets", {})
        group, rule = targets.get("group_id"), targets.get("rule_id")
        if group in groups or not group and rule in visible_rules:
            changes.append(
                {
                    k: deepcopy(c[k])
                    for k in ("id", "action", "requested_at", "revision", "outcome")
                    if k in c
                }
            )
    result = {
        "scope": grant["scope"],
        "expires_at": grant["expires_at"],
        "timezone": state.timezone,
        "revision": state.revision,
        "confirmed_revision": state.confirmed_revision,
        "sync": state.sync_status,
        "last_observed": state.last_observed,
        "fresh": fresh,
        "management": state.management,
        "groups": group_rows,
        "rules": [
            {
                **asdict(r),
                "target_names": [t["name"] for t in target_labels(r, catalogue_labels)],
                "groups": [g for g in r.groups if g in groups],
                "networks": [n for n in r.networks if n in networks],
                "whole_rule_control": grant["scope"] != "read_only"
                and whole_rule_allowed(r, groups, networks),
            }
            for r in rules
        ],
        "exceptions": exceptions,
        "changes": changes,
    }
    # Watch payloads intentionally omit inventory, DNS, grants and administration.
    if set(state.networks) <= networks:
        result["quarantine_rule"] = {
            "enabled": state.quarantine,
            "paused": state.quarantine_paused(now),
            "expires_at": state.quarantine_until if state.quarantine_paused(now) else None,
            "can_control": grant["scope"] != "read_only",
            "can_toggle": False,
        }
    if grant["scope"] != "watch_rules":
        result["devices"] = [
            asdict(d) for d in state.devices.values() if d.group in groups or d.network in networks
        ]
        for device in result["devices"]:
            if device["group"] not in groups:
                device["group"] = None
    return result
