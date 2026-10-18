"""Group-only allowances across every kind of explicitly assigned rule."""

from datetime import timedelta

from .models import ExceptionRecord, FamilyError, instant, uid
from .schedule import rule_active

ACTIONS = {"unblock_group", "end_group_unblock", "extend_group_unblock"}


def candidates(state, group, now):
    """Leave whole-rule lifts and this group's suspensions untouched."""
    protected = {
        e.rule
        for e in state.exceptions.values()
        if e.active(now)
        and e.rule
        and (
            e.group is None
            and e.kind in ("suspension", "rule_allow")
            or e.group == group
            and e.kind == "suspension"
        )
    }
    return [
        r
        for r in state.rules.values()
        if r.enabled and group in r.groups and not r.networks and r.id not in protected
    ]


def allowances(state, group, now):
    rules = {
        r.id for r in state.rules.values() if r.enabled and group in r.groups and not r.networks
    }
    return [
        e
        for e in state.exceptions.values()
        if e.group == group
        and e.active(now)
        and (
            e.kind == "rule_allow"
            and e.rule in rules
            or e.kind == "internet_allow"
            and rules.intersection(e.captured)
        )
    ]


def summary(state, group, now):
    records = allowances(state, group, now)
    timed = [e.expires_at for e in records if e.expires_at]
    return {
        "eligible_rules": len(candidates(state, group, now)),
        "can_unblock": any(
            rule_active(r, now, state.timezone) for r in candidates(state, group, now)
        )
        or any(
            e.group == group and e.kind == "pause" and e.active(now)
            for e in state.exceptions.values()
        ),
        "allowances": len(records),
        "timed_allowances": len(timed),
        "indefinite_allowances": len(records) - len(timed),
        "latest_deadline": max(timed, key=instant) if timed else None,
    }


def mutate(state, action, payload, actor, now, *, deadline, simulation):
    group = payload["group_id"]
    if action == "end_group_unblock":
        state.exceptions = {
            key: e
            for key, e in state.exceptions.items()
            if not (e.group == group and e.kind in ("internet_allow", "rule_allow"))
        }
        return
    if action == "extend_group_unblock":
        timed = [e for e in allowances(state, group, now) if e.expires_at]
        if not timed:
            raise FamilyError("No active timed group allowance to extend")
        extended_end = max(instant(e.expires_at) for e in timed) + timedelta(
            minutes=payload["duration_minutes"]
        )
        if extended_end > now + timedelta(days=7):
            raise FamilyError("Extended deadline exceeds seven days")
        if state.management and not simulation and not state.expiry_acknowledged:
            raise FamilyError("Acknowledge allowance expiry dependence on Home Assistant")
        for record in timed:
            record.expires_at = extended_end.isoformat()
        return

    modes = [
        key
        for key in ("duration_minutes", "expires_at", "next_window_end", "indefinite")
        if payload.get(key)
    ]
    if len(modes) > 1:
        raise FamilyError("Select exactly one deadline mode")
    explicit = bool(modes and modes[0] != "next_window_end")
    end = deadline(state, payload, now, indefinite=True) if explicit else None
    rules = [
        r for r in candidates(state, group, now) if explicit or rule_active(r, now, state.timezone)
    ]
    paused = any(
        e.group == group and e.kind == "pause" and e.active(now) for e in state.exceptions.values()
    )
    if not rules and not paused:
        raise FamilyError(
            "No applicable group restriction to unblock; network-wide rules remain separate"
        )
    ends = {
        r.id: end
        if explicit or not r.windows
        else deadline(state, {"next_window_end": True}, now, [r.id])
        for r in rules
    }
    if state.management and not simulation and not state.expiry_acknowledged and any(ends.values()):
        raise FamilyError("Acknowledge allowance expiry dependence on Home Assistant")

    # Replace only allowances for the captured rules; new/future rules are never
    # captured retroactively. Whole-network and whole-rule exceptions stay intact.
    retained = {}
    for key, record in state.exceptions.items():
        if record.group == group:
            if record.kind == "pause" or record.kind == "rule_allow" and record.rule in ends:
                continue
            if record.kind == "internet_allow":
                record.captured = [r for r in record.captured if r not in ends]
                if not record.captured:
                    continue
        retained[key] = record
    state.exceptions = retained
    for rule, expires in ends.items():
        record = ExceptionRecord(
            uid(),
            "rule_allow",
            group,
            rule,
            [rule],
            now.isoformat(),
            expires,
            actor,
            payload["reason"],
        )
        state.exceptions[record.id] = record
