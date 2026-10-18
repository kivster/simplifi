"""Review-bound, atomic person/device/schedule setup using native household records."""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

import probatio as vol

from .const import STALE_SECONDS
from .models import FamilyError, Group, Rule, Window, fingerprint, instant
from .planner import plan

CONFIGURATION = vol.Schema(
    {
        vol.Optional("group_id"): str,
        vol.Optional("name", default=""): vol.All(str, vol.Length(max=100)),
        vol.Optional("kind", default="family"): vol.In(["family", "thing"]),
        vol.Optional("age", default=""): vol.In(["", "child", "teen", "adult"]),
        vol.Optional("person", default=""): str,
        vol.Required("devices"): [str],
        vol.Optional("gateway_timezone_confirmed", default=False): bool,
        vol.Optional("schedules", default=[]): [
            vol.Schema(
                {
                    vol.Required("name"): vol.All(str, vol.Length(min=1, max=100)),
                    vol.Required("days"): [int],
                    vol.Required("start"): str,
                    vol.Required("end"): str,
                    vol.Required("overnight"): bool,
                },
                extra=vol.PREVENT_EXTRA,
            )
        ],
    },
    extra=vol.PREVENT_EXTRA,
)


def prepare(state, gateway, configuration, actor, now):
    try:
        config = CONFIGURATION(configuration)
    except Exception as err:
        raise FamilyError("Setup fields do not match the documented schema") from err
    if (
        not state.inventory_complete
        or not state.last_observed
        or now - instant(state.last_observed) >= timedelta(seconds=STALE_SECONDS)
    ):
        raise FamilyError("Refresh the inventory before reviewing household setup")
    if len(config["devices"]) != len(set(config["devices"])) or len(config["schedules"]) > 8:
        raise FamilyError("Select unique devices and at most eight schedules")
    group_id = config.get("group_id")
    existing = state.groups.get(group_id)
    if group_id and (existing is None or existing.archived):
        raise FamilyError("Select an active existing person or shared group")
    if not existing and (
        not config["name"].strip()
        or any(
            g.name.casefold() == config["name"].strip().casefold() for g in state.groups.values()
        )
    ):
        raise FamilyError("Enter a new, distinct person or shared group name")
    selected = []
    for key in config["devices"]:
        device = state.devices.get(key)
        if device is None or device.network not in state.networks:
            raise FamilyError("A selected device is no longer in the managed network scope")
        if device.group and device.group != group_id:
            raise FamilyError(
                "A selected device already belongs to someone else; review it in Devices"
            )
        selected.append(device)
    evidence = {
        "configuration": config,
        "actor": actor,
        "revision": state.revision,
        "devices": [
            {k: asdict(d)[k] for k in ("id", "mac", "name", "network", "group")} for d in selected
        ],
        "networks": {n: gateway.networks.get(n) for n in state.networks},
        "timezone": state.timezone,
        "management": state.management,
        "external_zone": gateway.external_zone,
    }
    review_hash = fingerprint(evidence)

    def identity(label):
        return str(uuid5(NAMESPACE_URL, "family-network/setup/" + review_hash + "/" + label))

    draft = deepcopy(state)
    draft.gateway_timezone_confirmed = (
        state.gateway_timezone_confirmed or config["gateway_timezone_confirmed"]
    )
    if not existing:
        group_id = identity("group")
        if group_id in draft.groups:
            raise FamilyError("Setup identity already exists; refresh and review again")
        draft.groups[group_id] = Group(
            group_id,
            config["name"].strip(),
            config["kind"],
            config["age"] or None,
            config["person"] or None,
        )
    for device in selected:
        draft.devices[device.id].group = group_id
    rules = []
    for index, item in enumerate(config["schedules"]):
        window = Window(
            identity(f"window-{index}"),
            item["name"],
            item["days"],
            item["start"],
            item["end"],
            overnight=item["overnight"],
        )
        window.validate()
        rule = Rule(
            identity(f"rule-{index}"), item["name"], "internet", [group_id], windows=[window]
        )
        if rule.id in draft.rules:
            raise FamilyError("Setup rule already exists; refresh and review again")
        draft.rules[rule.id] = rule
        rules.append(rule)
    draft.validate()
    policies = plan(draft, gateway.networks, gateway.external_zone, gateway.catalogues, now)
    return draft, {
        "preview_hash": review_hash,
        "revision": state.revision,
        "group": asdict(draft.groups[group_id]),
        "existing_group": bool(existing),
        "devices": [
            {"id": d.id, "name": d.name, "network": d.network, "connected": d.connected}
            for d in selected
        ],
        "rules": [asdict(r) for r in rules],
        "timezone": state.timezone,
        "management": state.management,
        "confirms_gateway_timezone": bool(
            config["gateway_timezone_confirmed"] and not state.gateway_timezone_confirmed
        ),
        "planned_policy_count": len(policies),
        "assignment_releases_quarantine": bool(state.quarantine and selected),
        "note": "Existing group settings, rules and exceptions are retained. These schedules restrict all internet for this group. Future devices assigned to the group inherit its rules.",
    }
