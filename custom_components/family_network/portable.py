"""Versioned household exports and explicit, credential-free restore planning."""

import json
from copy import deepcopy

from .models import Conflict, Device, FamilyError, State, fingerprint, mac_address

FIELDS = (
    "schema",
    "controller",
    "site",
    "networks",
    "timezone",
    "groups",
    "rules",
    "probes",
    "probe_schedule",
    "dns_settings",
    "audit_days",
)
MAX_BYTES = 2_000_000


def export(state):
    raw = state.to_dict()
    configuration = {k: raw[k] for k in FIELDS}
    configuration["probe_schedule"]["last_claim"] = None
    return {
        "format": "family_network",
        "version": 2,
        "configuration": configuration,
        "quarantine": state.quarantine,
        "assignments": [
            {
                "mac": d.mac,
                "name": d.name,
                "group": d.group,
                "quarantine_excluded": d.id in state.quarantine_excluded,
            }
            for d in sorted(state.devices.values(), key=lambda d: d.mac)
            if d.group or d.id in state.quarantine_excluded
        ],
    }


def unpack(data):
    """Accept old exports without silently accepting future formats or extra state."""
    try:
        if len(json.dumps(data).encode()) > MAX_BYTES:
            raise FamilyError("Configuration exceeds the 2 MB restore limit")
        if "format" in data:
            if (
                set(data) != {"format", "version", "configuration", "quarantine", "assignments"}
                or data["format"] != "family_network"
                or type(data["version"]) is not int
                or data["version"] != 2
            ):
                raise FamilyError("Unsupported portable export format or version")
            configuration, assignments, quarantine = (
                data["configuration"],
                data["assignments"],
                data["quarantine"],
            )
        else:
            configuration, assignments, quarantine = data, [], False
        if (
            not isinstance(configuration, dict)
            or set(configuration) not in (set(FIELDS), set(FIELDS) - {"dns_settings"})
            or not isinstance(assignments, list)
            or len(assignments) > 2000
            or type(quarantine) is not bool
        ):
            raise FamilyError("Portable export contains missing, unknown or invalid fields")
        return deepcopy(configuration), deepcopy(assignments), quarantine
    except TypeError, ValueError, RecursionError:
        raise FamilyError("Invalid configuration export") from None


def network_mapping(source, destination, mapping):
    if (
        not isinstance(source, list)
        or not source
        or any(type(n) is not str for n in source)
        or len(set(source)) != len(source)
    ):
        raise FamilyError("Invalid source network scope")
    if (
        not isinstance(mapping, dict)
        or set(mapping) != set(source)
        or any(type(n) is not str or n not in destination for n in mapping.values())
    ):
        raise FamilyError("Explicitly map every source network to a currently managed network")
    return mapping


def clean_binding(state):
    """Never discard policies or uncertain writes when moving the household."""
    if (
        state.management
        or state.owned
        or any(row.get("status") != "verified" for row in state.journal)
    ):
        raise FamilyError(
            "Disable management, resolve uncertain writes and clean up owned policies first"
        )


def prepare(state, data, mapping, actor):
    try:
        return _prepare(state, data, mapping, actor)
    except TypeError, KeyError, ValueError, AttributeError:
        raise FamilyError("Invalid configuration export") from None


def _prepare(state, data, mapping, actor):
    source, assignments, quarantine = unpack(data)
    same_binding = (source["controller"], source["site"], sorted(source["networks"])) == (
        state.controller,
        state.site,
        sorted(state.networks),
    )
    if not mapping and same_binding:
        mapping = {n: n for n in source["networks"]}
    mapping = network_mapping(source["networks"], state.networks, mapping)
    raw = state.to_dict()
    raw.update(source)
    # Controller credentials and operational ownership never travel in an export.
    raw.update(
        controller=state.controller,
        site=state.site,
        networks=list(state.networks),
        management=False,
        confirmed_revision=None,
        gateway_timezone_confirmed=False,
        expiry_acknowledged=False,
        quarantine=quarantine,
        quarantine_until=None,
        quarantine_suspended=False,
        quarantine_excluded=[],
        exceptions={},
        probe_results={},
        access_grants={},
        access_revision=state.access_revision + 1,
        inventory_complete=False,
        last_observed=None,
        sync_status="management_disabled",
        issue=None,
    )
    from .dns_context import DEFAULT_SETTINGS

    raw["dns_settings"] = source.get("dns_settings", deepcopy(DEFAULT_SETTINGS))
    if not same_binding:
        # A LAN address on another controller is not evidence of the same resolver.
        raw["dns_settings"] = deepcopy(DEFAULT_SETTINGS)
        for probe in raw["probes"].values():
            probe["resolver"] = ""
            probe["baseline_resolver"] = ""
    raw["probe_schedule"]["last_claim"] = None
    for group in raw["groups"].values():
        group["person"] = None
    for rule in raw["rules"].values():
        rule["networks"] = sorted({mapping[n] for n in rule.get("networks", [])})
    for device in raw["devices"].values():
        device["group"] = None
    draft = State.from_dict(raw)
    by_mac = {d.mac: d for d in draft.devices.values()}
    seen = set()
    matched = []
    pending = []
    for row in assignments:
        if (
            set(row) != {"mac", "name", "group", "quarantine_excluded"}
            or type(row["name"]) is not str
            or not 1 <= len(row["name"]) <= 200
            or type(row["quarantine_excluded"]) is not bool
            or row["group"] is not None
            and row["group"] not in draft.groups
        ):
            raise FamilyError("Invalid portable device assignment")
        mac = mac_address(row["mac"])
        if mac != row["mac"] or mac in seen:
            raise FamilyError("Duplicate or noncanonical assignment MAC address")
        seen.add(mac)
        device = by_mac.get(mac)
        if device:
            matched.append({"mac": mac, "name": device.name, "group": row["group"]})
        else:
            device = Device(f"restore:{mac}", mac, row["name"], None)
            draft.devices[device.id] = device
            pending.append({"mac": mac, "name": row["name"], "group": row["group"]})
        device.group = row["group"]
        if row["quarantine_excluded"]:
            draft.quarantine_excluded.append(device.id)
    from .dns_catalog import ensure_seeds

    ensure_seeds(draft)
    draft.dns_revision += 1
    draft.validate()
    review = {
        "revision": state.revision,
        "source_controller": source["controller"],
        "source_site": source["site"],
        "scope": state.networks,
        "mapping": mapping,
        "groups": len(draft.groups),
        "rules": len(draft.rules),
        "timezone": draft.timezone,
        "quarantine": quarantine,
        "matched": matched,
        "pending": pending,
        "dns_resolvers_reset": not same_binding,
        "note": "Management stays disabled. Existing household settings and assignments are replaced; access grants are revoked; temporary exceptions and HA person links are cleared. Unseen MAC addresses wait for discovery. Review before enabling management.",
    }
    review["preview_hash"] = fingerprint(
        {
            "configuration": data,
            "mapping": mapping,
            "revision": state.revision,
            "dns_revision": state.dns_revision,
            "access_revision": state.access_revision,
            "binding": [state.controller, state.site, state.networks],
            "actor": actor,
            "devices": sorted((d.id, d.mac, d.network, d.group) for d in state.devices.values()),
        }
    )
    return draft, review


def confirm(state, data, mapping, actor, expected):
    clean_binding(state)
    draft, review = prepare(state, data, mapping, actor)
    if expected != review["preview_hash"]:
        raise Conflict(
            "Import preview changed; review current assignments, settings and network mapping again"
        )
    return draft
