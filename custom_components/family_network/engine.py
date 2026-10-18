"""Authorised, atomic desired-state transitions and reconciliation orchestration."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
from typing import Any

from .actions import DNS_ACTIONS, SCHEMAS
from .const import STALE_SECONDS
from .models import (
    Conflict,
    ExceptionRecord,
    FamilyError,
    Group,
    Rule,
    State,
    Window,
    domain_name,
    fingerprint,
    instant,
    uid,
    utcnow,
)
from .planner import group_status, lifted, plan, policy_fingerprint
from .reconciler import Reconciler
from .schedule import active_end, rule_active
from .timing_audit import capture as capture_timing


class Engine:
    def __init__(self, state: State, gateway, save, clock=utcnow):
        self.state = state
        self.gateway = gateway
        self.save = save
        self.clock = clock
        self.lock = asyncio.Lock()
        self.reconfiguring = False
        self.closing = False
        self.import_backup: Any = None
        self.reconciler = Reconciler(gateway, save, self.ensure_available)

    async def command(
        self, action: str, data: dict, actor: str | None, *, administrator: bool = False
    ) -> dict[str, Any]:
        if not actor:
            raise FamilyError("An authenticated Home Assistant user is required")
        if action not in SCHEMAS:
            raise FamilyError("Unknown action")
        try:
            payload = SCHEMAS[action](data)
        except Exception as err:
            raise FamilyError("Action fields do not match the documented schema") from err
        async with self.lock:
            self.ensure_available()
            now = self.clock()
            state = self.state
            if not administrator:
                from .access import authorize

                authorize(state, action, payload, actor, now)
            token = payload.get("request_id")
            digest = fingerprint(
                {
                    "action": action,
                    "payload": {
                        k: v
                        for k, v in payload.items()
                        if k
                        not in (
                            "expected_revision",
                            "expected_dns_revision",
                            "expected_access_revision",
                        )
                    },
                }
            )
            if token:
                previous = next(
                    (
                        c
                        for c in state.changes
                        if c.get("request_id") == token and c["actor"] == actor
                    ),
                    None,
                )
                if previous:
                    if previous["digest"] != digest:
                        raise Conflict("Request ID was already used for a different change")
                    return deepcopy(previous)
            if payload.get("expected_revision", state.revision) != state.revision:
                raise Conflict("Configuration changed; refresh the form and preview again")
            if action == "preview_setup":
                from .setup import prepare

                _, review = prepare(state, self.gateway, payload["configuration"], actor, now)
                return review
            if action == "access_status":
                from .access import status

                return status(state, actor, now, confirmed=self.configuration_confirmed(now))
            if action == "list_access_grants":
                return {
                    "access_revision": state.access_revision,
                    "grants": deepcopy(state.access_grants),
                }
            if action in ("set_access_grant", "revoke_access_grant"):
                if not payload["confirm"]:
                    raise FamilyError("Review and confirm the explicit user and access scope")
                if (
                    payload.get("expected_access_revision", state.access_revision)
                    != state.access_revision
                ):
                    raise Conflict("Access grants changed; refresh the form")
                draft = deepcopy(state)
                user_id = payload["user_id"]
                if action == "revoke_access_grant":
                    draft.access_grants.pop(user_id, None)
                else:
                    expires = payload.get("expires_at")
                    if expires and not now < instant(expires) <= now + timedelta(days=365):
                        raise FamilyError("Grant expiry must be within the next year")
                    if (
                        not payload["all_groups"]
                        and not payload["groups"]
                        and not payload["networks"]
                    ):
                        raise FamilyError("Select explicit groups or networks")
                    draft.access_grants[user_id] = {
                        k: payload[k] for k in ("scope", "groups", "networks", "all_groups")
                    }
                    draft.access_grants[user_id].update(
                        expires_at=expires, actor=actor, created_at=now.isoformat()
                    )
                draft.access_revision += 1
                draft.validate()
                change = {
                    "id": uid(),
                    "revision": state.revision,
                    "actor": actor,
                    "action": action,
                    "targets": {"user_id": user_id},
                    "reason": payload["reason"],
                    "requested_at": now.isoformat(),
                    "outcome": "access_saved",
                    "access_revision": draft.access_revision,
                    "request_id": token,
                    "digest": digest,
                }
                change["details"] = {"timing": capture_timing(state, draft, action, payload)}
                draft.changes = [*draft.changes, change][-1000:]
                await self.save(draft)
                self.state = draft
                return deepcopy(change)
            if action in DNS_ACTIONS:
                if payload.get("expected_dns_revision", state.dns_revision) != state.dns_revision:
                    raise Conflict("DNS settings changed; reopen the form and try again")
                if action == "check_dns":
                    from .dns_context import jobs

                    jobs(
                        state,
                        self.gateway.networks,
                        payload.get("probe_id"),
                        payload.get("group_id"),
                    )
                draft = deepcopy(state)
                if action != "check_dns":
                    self._mutate(draft, action, payload, actor, now)
                    draft.dns_revision += 1
                    # A global observation generation makes in-flight edits and
                    # inherited resolver changes impossible to accept as current.
                    draft.probe_results.clear()
                draft.validate()
                change = {
                    "id": uid(),
                    "revision": draft.revision,
                    "dns_revision": draft.dns_revision,
                    "actor": actor,
                    "action": action,
                    "targets": {},
                    "reason": payload["reason"],
                    "requested_at": now.isoformat(),
                    "outcome": "requested" if action == "check_dns" else "saved",
                    "request_id": token,
                    "digest": digest,
                }
                draft.changes = [*draft.changes, change][-1000:]
                await self.save(draft)
                self.state = draft
                return deepcopy(change)
            if action == "view_activity":
                return {
                    "changes": deepcopy(state.changes[-100:]),
                    "owned_policies": deepcopy(state.owned),
                    "journal": deepcopy(state.journal[-100:]),
                }
            if action == "preview_recovery":
                from .recovery import preview

                return await preview(state, self.gateway, actor, now, payload.get("operation_id"))
            if action == "resolve_operation":
                from .recovery import resolve

                draft = await resolve(state, self.gateway, payload, actor, now)
                change = {
                    "id": uid(),
                    "revision": state.revision,
                    "actor": actor,
                    "action": action,
                    "targets": {"operation_id": payload["operation_id"]},
                    "reason": payload["reason"],
                    "requested_at": now.isoformat(),
                    "outcome": "recovery_recorded",
                    "decision": payload["decision"],
                    "request_id": token,
                    "digest": digest,
                }
                draft.changes = [*draft.changes, change][-1000:]
                await self.save(draft)
                self.state = draft
                return deepcopy(change)
            if action == "export_configuration":
                return {"configuration": self.export()}
            if action == "preview_import":
                from .portable import prepare as prepare_import

                return prepare_import(
                    state, payload["configuration"], payload["network_mapping"], actor
                )[1]
            if action == "dashboard_configuration":
                raise FamilyError(
                    "Dashboard generation is provided by the HA service binding layer"
                )
            if action == "cleanup_owned":
                if not payload["confirm"] or state.management:
                    raise FamilyError(
                        "Disable management and review owned policy IDs before confirming cleanup"
                    )
                await self.reconciler.apply(state, {}, now)
                return {"outcome": "owned_cleanup_verified", "remaining": len(state.owned)}
            draft = deepcopy(state)
            setup_review = None
            if action == "apply_setup":
                from .setup import prepare

                if not payload["confirm"]:
                    raise FamilyError("Review and confirm the person, devices and schedules")
                draft, setup_review = prepare(
                    state, self.gateway, payload["configuration"], actor, now
                )
                if setup_review["preview_hash"] != payload["preview_hash"]:
                    raise Conflict("Setup evidence changed; review the current household again")
            elif action == "apply_import":
                from .portable import confirm

                draft = confirm(
                    state,
                    payload["configuration"],
                    payload["network_mapping"],
                    actor,
                    payload["preview_hash"],
                )
            elif action not in ("sync_now", "check_dns"):
                self._mutate(draft, action, payload, actor, now)
            draft.validate()
            if action == "apply_import" and self.import_backup is not None:
                await self.import_backup(state.to_dict())
            draft.revision += 1
            draft.sync_status = "pending"
            draft.issue = None
            change = {
                "id": uid(),
                "revision": draft.revision,
                "actor": actor,
                "action": action,
                "targets": {
                    k: v
                    for k, v in payload.items()
                    if k.endswith("_id") or k in ("groups", "networks")
                },
                "reason": payload["reason"],
                "requested_at": now.isoformat(),
                "outcome": "pending",
                "request_id": token,
                "digest": digest,
            }
            draft.changes.append(change)
            if setup_review:
                change["targets"] = {"group_id": setup_review["group"]["id"]}
                change["details"] = {
                    "assigned_devices": [d["id"] for d in setup_review["devices"]],
                    "created_rules": [r["id"] for r in setup_review["rules"]],
                }
            if action == "edit_allowance":
                exc = draft.exceptions[payload["exception_id"]]
                change["details"] = {
                    "previous_deadline": state.exceptions[exc.id].expires_at,
                    "expires_at": exc.expires_at,
                    "captured_rules": list(exc.captured),
                }
                change["targets"].update(group_id=exc.group, rule_id=exc.rule)
            if timing := capture_timing(state, draft, action, payload):
                change.setdefault("details", {})["timing"] = timing
            cutoff = now - timedelta(days=draft.audit_days)
            draft.changes = [c for c in draft.changes if instant(c["requested_at"]) >= cutoff][
                -1000:
            ]
            # Verified journal rows can be bounded; uncertain operations are never evicted.
            draft.journal = (
                [
                    j
                    for j in draft.journal
                    if j["status"] != "verified" or instant(j["created_at"]) >= cutoff
                ][-2000:]
                if not any(j["status"] != "verified" for j in draft.journal[:-2000])
                else draft.journal
            )
            await self.save(draft)
            self.state = draft  # Save failure never changes live intent.
            return deepcopy(change)

    def _deadline(self, state, data, now, rule_ids=(), *, indefinite=False):
        selected = [
            k
            for k in ("duration_minutes", "expires_at", "next_window_end", "indefinite")
            if data.get(k)
        ]
        if len(selected) != 1:
            raise FamilyError("Select exactly one deadline mode")
        mode = selected[0]
        if mode == "indefinite":
            if not indefinite:
                raise FamilyError("This action requires a finite deadline")
            return None
        if mode == "duration_minutes":
            end = now + timedelta(minutes=data[mode])
        elif mode == "expires_at":
            try:
                end = instant(data[mode])
            except ValueError, TypeError:
                raise FamilyError("Choose a valid deadline with a timezone") from None
        else:
            ends = [
                active_end(state.rules[r], now, state.timezone)
                for r in rule_ids
                if state.rules[r].windows and rule_active(state.rules[r], now, state.timezone)
            ]
            if not ends:
                raise FamilyError("No applicable schedule end; select a time")
            end = min(ends)
        if not now < end <= now + timedelta(days=7):
            raise FamilyError("Deadline must be within the next seven days")
        return end.isoformat()

    def _mutate(self, state, action, p, actor, now):
        group = p.get("group_id") or None
        rule = p.get("rule_id") or None
        if group and action != "upsert_group" and group not in state.groups:
            raise FamilyError("Unknown group")
        if rule and action != "upsert_rule" and rule not in state.rules:
            raise FamilyError("Unknown rule")
        if rule and group and group not in state.rules[rule].groups:
            raise FamilyError("Group is not targeted by this rule")
        if (
            rule
            and action in ("suspend_rule", "allow_rule", "extend_rule_suspension")
            and not state.rules[rule].enabled
        ):
            raise FamilyError("Enable the rule before pausing, allowing or extending it")
        if action == "upsert_group":
            group = group or uid()
            state.groups[group] = Group(
                group,
                p["name"],
                p["kind"],
                p.get("age") or None,
                p.get("person") or None,
                p["archived"],
            )
        elif action == "delete_group":
            if not p["confirm"]:
                raise FamilyError("Confirm device unassignment and quarantine implications")
            state.groups.pop(group)
            for grant in state.access_grants.values():
                if group in grant["groups"]:
                    grant["groups"].remove(group)
                    state.access_revision += 1
            state.dns_settings["group_resolvers"].pop(group, None)
            state.probes = {k: p for k, p in state.probes.items() if p.get("group_id") != group}
            state.probe_results.clear()
            state.dns_revision += 1
            for device in state.devices.values():
                if device.group == group:
                    device.group = None
            for r in list(state.rules.values()):
                r.groups = [g for g in r.groups if g != group]
                if not r.groups and not r.networks:
                    state.rules.pop(r.id)
            state.exceptions = {
                k: e
                for k, e in state.exceptions.items()
                if e.group != group and (e.rule is None or e.rule in state.rules)
            }
        elif action == "assign_device":
            if p["device_id"] not in state.devices:
                raise FamilyError("Unknown device; refresh inventory")
            if group and state.groups[group].archived:
                raise FamilyError("Cannot assign to an archived group")
            state.devices[p["device_id"]].group = group
        elif action == "forget_device":
            if not p["confirm"]:
                raise FamilyError(
                    "Confirm removal of the device assignment and quarantine exclusion"
                )
            if p["device_id"] not in state.devices:
                raise FamilyError("Unknown device; refresh inventory")
            state.devices.pop(p["device_id"])
            state.quarantine_excluded = [
                key for key in state.quarantine_excluded if key != p["device_id"]
            ]
            # No tombstone or controller deletion: a present client is rediscovered
            # unassigned, so normal in-scope quarantine remains effective.
        elif action in ("unblock_group", "end_group_unblock", "extend_group_unblock"):
            from .group_controls import mutate

            mutate(
                state,
                action,
                p,
                actor,
                now,
                deadline=self._deadline,
                simulation=self.gateway.simulation,
            )
        elif action == "edit_allowance":
            exc = state.exceptions.get(p["exception_id"])
            if not exc or exc.kind not in ("internet_allow", "rule_allow") or not exc.active(now):
                raise FamilyError("This allowance has ended; refresh the household")
            if state.management and not self.gateway.simulation and not state.expiry_acknowledged:
                raise FamilyError("Acknowledge allowance expiry dependence on Home Assistant")
            # Keep identity, original actor, creation time, scope and captured rules.
            exc.expires_at = self._deadline(state, p, now)
        elif action == "upsert_rule":
            rule = rule or uid()
            targets = (
                [domain_name(t) for t in p["targets"]] if p["kind"] == "domain" else p["targets"]
            )
            windows = []
            for w in p["windows"]:
                try:
                    windows.append(Window(**{**w, "id": w.get("id") or uid()}))
                except TypeError:
                    raise FamilyError("Invalid window fields") from None
            if p["kind"] in ("category", "application") and any(
                t not in self.gateway.catalogues.get(p["kind"], set()) for t in targets
            ):
                raise FamilyError("Select target IDs from the current gateway catalogue")
            previous = state.rules.get(rule)
            if previous and (
                previous.kind != p["kind"] or bool(previous.networks) != bool(p["networks"])
            ):
                raise FamilyError(
                    "An existing rule keeps its kind and scope type; create a new rule for that change"
                )
            state.rules[rule] = Rule(
                rule,
                p["name"],
                p["kind"],
                p["groups"],
                targets,
                windows,
                p["enabled"],
                p["networks"],
            )
            # Renaming or editing a rule retains its pauses. Removed targets and
            # switching it off cannot leave exceptions that revive on re-enable.
            self._prune_rule_exceptions(state, rule)
        elif action == "delete_rule":
            state.rules.pop(rule)
            state.exceptions = {k: e for k, e in state.exceptions.items() if e.rule != rule}
            for exc in state.exceptions.values():
                exc.captured = [r for r in exc.captured if r != rule]
            state.exceptions = {
                key: exc
                for key, exc in state.exceptions.items()
                if exc.kind != "internet_allow" or exc.captured
            }
        elif action == "set_rule_enabled":
            state.rules[rule].enabled = p["enabled"]
            self._prune_rule_exceptions(state, rule)
        elif action in ("pause_internet", "allow_internet", "suspend_rule", "allow_rule"):
            kind = {
                "pause_internet": "pause",
                "allow_internet": "internet_allow",
                "suspend_rule": "suspension",
                "allow_rule": "rule_allow",
            }[action]
            captured = (
                [
                    r.id
                    for r in state.rules.values()
                    if group in r.groups
                    and r.kind == "internet"
                    and rule_active(r, now, state.timezone)
                    and (
                        action != "allow_internet"
                        or not lifted(state, r.id, group, now)
                        or any(
                            e.kind in ("internet_allow", "rule_allow")
                            and e.group == group
                            and e.active(now)
                            and (r.id in e.captured or e.rule == r.id)
                            for e in state.exceptions.values()
                        )
                    )
                ]
                if action in ("pause_internet", "allow_internet")
                else [rule]
                if rule
                else []
            )
            if action == "allow_internet" and not captured:
                raise FamilyError("No active managed internet rule to lift")
            modes = sum(
                bool(p.get(k))
                for k in ("duration_minutes", "expires_at", "next_window_end", "indefinite")
            )
            if modes > 1:
                raise FamilyError("Select exactly one deadline mode")
            default = modes == 0
            if kind == "internet_allow" and (default or p.get("next_window_end")):
                # Each captured internet rule returns at its own active window end.
                deadlines = [
                    (
                        [r],
                        self._deadline(state, {"next_window_end": True}, now, [r])
                        if state.rules[r].windows
                        else None,
                    )
                    for r in captured
                ]
            elif kind == "rule_allow" and default:
                if not rule_active(state.rules[rule], now, state.timezone):
                    raise FamilyError("No active window to allow; choose an explicit deadline")
                deadlines = [
                    (
                        captured,
                        self._deadline(state, {"next_window_end": True}, now, captured)
                        if state.rules[rule].windows
                        else None,
                    )
                ]
            else:
                deadlines = [
                    (
                        captured,
                        self._deadline(
                            state,
                            {**p, **({"indefinite": True} if default else {})},
                            now,
                            captured,
                            indefinite=True,
                        ),
                    )
                ]
            if (
                kind in ("internet_allow", "suspension", "rule_allow")
                and state.management
                and not self.gateway.simulation
                and not state.expiry_acknowledged
                and any(deadline for _, deadline in deadlines)
            ):
                raise FamilyError(
                    "Acknowledge permissive exception expiry dependence on HA before enabling it live"
                )
            if kind in ("suspension", "rule_allow") and group:
                self._clear_group_rule_allowance(state, rule, group)
            if kind in ("pause", "internet_allow"):
                state.exceptions = {
                    key: e
                    for key, e in state.exceptions.items()
                    if not (
                        e.kind == "rule_allow"
                        and e.group == group
                        and e.rule in state.rules
                        and state.rules[e.rule].kind == "internet"
                        and (kind == "pause" or e.rule in captured)
                    )
                }
            state.exceptions = {
                k: e
                for k, e in state.exceptions.items()
                if not (
                    e.group == group
                    and e.rule == rule
                    and (
                        e.kind in ("pause", "internet_allow")
                        if kind in ("pause", "internet_allow")
                        else e.kind in ("suspension", "rule_allow")
                    )
                )
            }
            for captured_rules, deadline in deadlines:
                record = ExceptionRecord(
                    uid(),
                    kind,
                    group,
                    rule,
                    captured_rules,
                    now.isoformat(),
                    deadline,
                    actor,
                    p["reason"],
                )
                state.exceptions[record.id] = record
        elif action in ("resume_internet", "end_allowance", "resume_rule", "end_rule_allowance"):
            if action == "end_rule_allowance" and group:
                self._clear_group_rule_allowance(state, rule, group)
            if action == "end_allowance":
                state.exceptions = {
                    key: e
                    for key, e in state.exceptions.items()
                    if not (
                        e.kind == "rule_allow"
                        and e.group == group
                        and e.rule in state.rules
                        and state.rules[e.rule].kind == "internet"
                    )
                }
            kind = {
                "resume_internet": "pause",
                "end_allowance": "internet_allow",
                "resume_rule": "suspension",
                "end_rule_allowance": "rule_allow",
            }[action]
            state.exceptions = {
                k: e
                for k, e in state.exceptions.items()
                if not (e.group == group and e.rule == rule and e.kind == kind)
            }
        elif action in ("extend_pause", "extend_rule_suspension"):
            kind = "pause" if action == "extend_pause" else "suspension"
            exc = next(
                (
                    e
                    for e in state.exceptions.values()
                    if e.group == group and e.rule == rule and e.kind == kind and e.active(now)
                ),
                None,
            )
            if not exc or not exc.expires_at:
                raise FamilyError("No active timed exception to extend")
            end = instant(exc.expires_at) + timedelta(minutes=p["duration_minutes"])
            if end > now + timedelta(days=7):
                raise FamilyError("Extended deadline exceeds seven days")
            exc.expires_at = end.isoformat()
        elif action == "set_quarantine":
            if p["enabled"] and not p["confirm"]:
                raise FamilyError("Review unassigned devices and recovery exclusions first")
            if not set(p["excluded_devices"]) <= set(state.devices):
                raise FamilyError("Unknown quarantine exclusion")
            if not p["enabled"] or not state.quarantine:
                state.quarantine_suspended = False
                state.quarantine_until = None
            state.quarantine = p["enabled"]
            state.quarantine_excluded = p["excluded_devices"]
        elif action == "suspend_quarantine":
            if not state.quarantine:
                raise FamilyError("Enable quarantine before pausing it")
            default = not any(
                p.get(k)
                for k in ("duration_minutes", "expires_at", "next_window_end", "indefinite")
            )
            deadline = self._deadline(
                state, {**p, **({"indefinite": True} if default else {})}, now, indefinite=True
            )
            if (
                deadline
                and state.management
                and not self.gateway.simulation
                and not state.expiry_acknowledged
            ):
                raise FamilyError("Acknowledge quarantine suspension expiry dependence on HA")
            state.quarantine_until = deadline
            state.quarantine_suspended = True
        elif action == "extend_quarantine_suspension":
            if (
                not state.quarantine
                or not state.quarantine_until
                or instant(state.quarantine_until) <= now
            ):
                raise FamilyError("No active quarantine suspension")
            end = instant(state.quarantine_until) + timedelta(minutes=p["duration_minutes"])
            if end > now + timedelta(days=7):
                raise FamilyError("Deadline exceeds seven days")
            state.quarantine_until = end.isoformat()
        elif action == "resume_quarantine":
            state.quarantine_until = None
            state.quarantine_suspended = False
        elif action == "set_management":
            if (
                p["enabled"]
                and not self.gateway.simulation
                and not p["expiry_acknowledged"]
                and (
                    any(
                        e.kind in ("internet_allow", "suspension", "rule_allow")
                        and e.active(now)
                        and e.expires_at
                        for e in state.exceptions.values()
                    )
                    or state.quarantine_until
                    and instant(state.quarantine_until) > now
                )
            ):
                raise FamilyError(
                    "Active permissive deadlines require an explicit outage acknowledgement"
                )
            state.management = p["enabled"]
            state.expiry_acknowledged = p["expiry_acknowledged"]
            state.gateway_timezone_confirmed = p["gateway_timezone_confirmed"]
        elif action == "upsert_probe":
            from .dns_checks import validate_probe

            probe = validate_probe(p)
            key = p.get("probe_id") or uid()
            from .dns_catalog import seed_edit

            old = state.probes.get(key, {})
            probe = seed_edit(old, probe)
            state.probes[key] = {**probe, "revision": old.get("revision", 0) + 1}
            state.probe_results.pop(key, None)
        elif action == "delete_probe":
            key = p["probe_id"]
            if key not in state.probes:
                raise FamilyError("Unknown DNS list")
            if state.probes[key].get("seed"):
                state.probes[key]["enabled"] = False
                state.probes[key]["revision"] += 1
            else:
                state.probes.pop(key)
            state.probe_results.pop(p["probe_id"], None)
        elif action == "restore_probe":
            from .dns_catalog import CATEGORIES

            probe = state.probes.get(p["probe_id"], {})
            if probe.get("seed") not in CATEGORIES:
                raise FamilyError("Only built-in sample lists have defaults to restore")
            probe["domains"] = sorted(
                set(probe["domains"]) | set(CATEGORIES[probe["seed"]]["domains"])
            )
            probe["removed_seed_domains"] = []
            probe["enabled"] = True
            probe["revision"] += 1
        elif action == "set_dns_settings":
            from .dns_context import DEFAULT_SETTINGS, settings

            state.dns_settings = settings({k: p[k] for k in DEFAULT_SETTINGS}, state.groups)
        elif action == "set_probe_schedule":
            window = Window("probe", "DNS checks", p["days"], p["time"], "00:00", all_day=True)
            window.validate()
            state.probe_schedule = {k: p[k] for k in ("enabled", "days", "time")} | {
                "last_claim": None
            }
        else:
            raise FamilyError("Unsupported action")

    def _clear_group_rule_allowance(self, state, rule_id, group):
        for exc in state.exceptions.values():
            if exc.kind == "internet_allow" and exc.group == group:
                exc.captured = [r for r in exc.captured if r != rule_id]
        state.exceptions = {
            key: e
            for key, e in state.exceptions.items()
            if e.kind != "internet_allow" or e.captured
        }

    def _prune_rule_exceptions(self, state, rule_id):
        rule = state.rules[rule_id]
        state.exceptions = {
            key: exc
            for key, exc in state.exceptions.items()
            if exc.rule != rule_id
            or rule.enabled
            and (exc.group is None or exc.group in rule.groups)
        }
        for exc in state.exceptions.values():
            if rule_id in exc.captured and (
                not rule.enabled or exc.group is not None and exc.group not in rule.groups
            ):
                exc.captured = [r for r in exc.captured if r != rule_id]
        state.exceptions = {
            key: exc
            for key, exc in state.exceptions.items()
            if exc.kind != "internet_allow" or exc.captured
        }

    async def refresh(self) -> None:
        async with self.lock:
            self.ensure_available()
            state = self.state
            now = self.clock()
            cutoff = now - timedelta(days=state.audit_days)
            state.changes = [c for c in state.changes if instant(c["requested_at"]) >= cutoff][
                -1000:
            ]
            stage = "device discovery"
            try:
                clients = await self.gateway.discover()
                candidate = deepcopy(state)
                for device in candidate.devices.values():
                    device.connected = False
                seen = set()
                for device in clients:
                    if device.mac in seen:
                        raise FamilyError("Duplicate MAC in controller inventory")
                    seen.add(device.mac)
                    existing = candidate.devices.get(device.id)
                    if existing and existing.mac != device.mac:
                        raise Conflict(
                            "Controller reused a device ID for a different MAC; review inventory"
                        )
                    existing = existing or next(
                        (d for d in candidate.devices.values() if d.mac == device.mac), None
                    )
                    if existing:
                        device.group = existing.group
                        if device.registrant_status == "unavailable":
                            device.registrant = existing.registrant
                        if existing.id != device.id:
                            del candidate.devices[existing.id]
                            candidate.quarantine_excluded = [
                                device.id if key == existing.id else key
                                for key in candidate.quarantine_excluded
                            ]
                    if existing or device.network in candidate.networks:
                        candidate.devices[device.id] = device
                candidate.inventory_complete = True
                candidate.last_observed = now.isoformat()
                candidate.validate()
                stage = "saving device observations"
                await self.save(candidate)
                self.state = state = candidate
                if state.management:
                    stage = "planning restrictions"
                    desired = plan(
                        state,
                        self.gateway.networks,
                        self.gateway.external_zone,
                        self.gateway.catalogues,
                        now,
                    )
                    # Preserve creation evidence marker in each complete PUT body.
                    for key, body in desired.items():
                        if key in state.owned:
                            body["description"] = state.owned[key]["body"].get("description", "")
                    stage = "policy reconciliation"
                    await self.reconciler.apply(state, desired, now)
                else:
                    state.sync_status = "management_disabled"
                    state.issue = None
                    for c in state.changes:
                        if c["revision"] == state.revision and c["outcome"] == "pending":
                            c["outcome"] = "saved_management_disabled"
                stage = "saving sync results"
                await self.save(state)
            except (FamilyError, TimeoutError) as err:
                state.inventory_complete = False
                state.sync_status = "partial" if state.owned else "failed"
                # FamilyError is the same redacted, user-facing contract used by
                # HA actions. Never expose raw transport exception text here.
                reason = str(err) if isinstance(err, FamilyError) else "The operation timed out"
                state.issue = f"Sync unconfirmed during {stage}: {reason}"
                for c in state.changes:
                    if c["revision"] == state.revision and c["outcome"] == "pending":
                        c["outcome"] = "failed"
                await self.save(state)
                raise

    def ensure_available(self):
        if self.closing:
            raise Conflict("SimpliFi is stopping; wait for the integration to reload")
        if self.reconfiguring:
            raise Conflict("Connection changes are being saved; wait for the integration to reload")

    def export(self):
        from .portable import export

        return export(self.state)

    def status(self, group):
        return group_status(self.state, group, self.clock())

    def configuration_confirmed(self, now=None):
        """Confirm current-time intent, not just the last saved revision.

        Expiring exceptions can change the required policy without a new revision.
        The recorded readback must match that plan before availability is confirmed.
        """
        state = self.state
        now = now or self.clock()
        if not (
            state.management
            and state.inventory_complete
            and state.last_observed
            and timedelta(0)
            <= now - instant(state.last_observed)
            < timedelta(seconds=STALE_SECONDS)
            and state.sync_status == "applied"
            and state.confirmed_revision == state.revision
            and all(j["status"] == "verified" for j in state.journal)
        ):
            return False
        try:
            desired = plan(
                state,
                self.gateway.networks,
                self.gateway.external_zone,
                self.gateway.catalogues,
                now,
            )
        except FamilyError:
            return False
        if desired.keys() != state.owned.keys():
            return False
        return all(
            policy_fingerprint(
                {**body, "description": state.owned[key]["body"].get("description", "")}
            )
            == state.owned[key]["fingerprint"]
            for key, body in desired.items()
        )
