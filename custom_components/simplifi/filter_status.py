"""Per-person evidence: configured controls and DNS observations stay separate."""

from .dns_catalog import CATEGORIES
from .dns_checks import aggregate
from .dns_context import observation
from .planner import lifted, rule_devices
from .schedule import rule_active


def inherited(state, group_id, protection):
    devices = [
        d for d in state.devices.values() if d.group == group_id and d.network in state.networks
    ]
    rows = []
    unresolved = False
    for profile in protection["profiles"]:
        if not profile["enabled"]:
            continue
        network_ids = {n.get("official_id") for n in profile["networks"]} - {None}
        # Never infer legacy-to-official identity from a friendly network name.
        unresolved |= any(not n.get("official_id") for n in profile["networks"])
        macs = {m.lower().replace("-", ":") for m in profile["client_macs"]}
        matched = [d for d in devices if d.network in network_ids or d.mac in macs]
        if matched:
            rows.append(
                {
                    "id": profile["id"],
                    "name": profile["name"],
                    "devices": [d.id for d in matched],
                    "device_count": len(matched),
                    "categories": profile["categories"],
                    "safe_search": profile["safe_search"],
                    "schedule": profile["schedule"],
                    "exceptions": len(profile["allow_list"]),
                    "blocked_domains": len(profile["block_list"]),
                }
            )
    reasons = []
    if not protection["fresh"]:
        reasons.append("Inherited UniFi settings are not current")
    if not state.inventory_complete:
        reasons.append("Device network discovery is not current")
    if unresolved:
        reasons.append(
            "Some UniFi network targets could not be matched; coverage may be incomplete"
        )
    if not devices:
        reasons.append("No assigned device is on a managed network")
    return {
        "fresh": bool(protection["fresh"] and state.inventory_complete),
        "complete": not reasons,
        "profiles": rows,
        "issues": reasons,
        "device_count": len(devices),
    }


def category_marks(state, networks, group_id, protection, confirmed, category_ids, now):
    parent = inherited(state, group_id, protection)
    result = []
    for slug, category in CATEGORIES.items():
        category_id = category["dpi"]
        matched = [
            r.id
            for r in state.rules.values()
            if r.kind == "category"
            and category_id in r.targets
            and (group_id in r.groups or rule_devices(state, r, group_id))
        ]
        active = [
            key
            for key in matched
            if rule_active(state.rules[key], now, state.timezone)
            and not lifted(state, key, group_id, now)
        ]
        covered_by_rules = {
            d.id for key in active for d in rule_devices(state, state.rules[key], group_id)
        }
        blocked = bool(active)
        enabled = [key for key in matched if state.rules[key].enabled]
        profiles = [
            p for p in parent["profiles"] if set(p["categories"]) & set(category["filters"])
        ]
        lists = [
            (key, observation(state, networks, key, group_id, now))
            for key, probe in state.probes.items()
            if probe.get("category") == slug
            and probe.get("group_id") in (None, group_id)
            and probe.get("enabled", True)
        ]
        dns = aggregate(obs["verdict"] for _, obs in lists)
        reasons = []
        if matched:
            reasons.append(
                "Managed category restriction is active and read back from UniFi"
                if blocked and confirmed and parent["device_count"]
                else "Managed restriction is saved but gateway confirmation is unavailable"
                if blocked
                else "Managed category rules are outside their schedule, disabled or temporarily lifted"
            )
        else:
            reasons.append("No managed category rule targets this person")
        if profiles:
            covered = set().union(*(set(p["devices"]) for p in profiles))
            reasons.append(
                f"Inherited UniFi filter configured for {len(covered)} of {parent['device_count']} assigned devices: "
                + ", ".join(p["name"] for p in profiles)
            )
            if any(p["schedule"].get("mode") != "ALWAYS" for p in profiles):
                reasons.append(
                    "Inherited profiles have schedules; their current active state is not evaluated here"
                )
            if any(p["exceptions"] for p in profiles):
                reasons.append("Inherited domain exceptions may allow individual sites")
        if active:
            reasons.append(
                f"Managed rules cover {len(covered_by_rules)} of {parent['device_count']} assigned devices"
            )
        reasons.extend(parent["issues"])
        dns_labels = {
            "open": "DNS resolves",
            "blocked": "DNS blocked",
            "partial": "DNS mixed",
            "unknown": "Needs checking",
        }
        dns_reasons = {
            "open": "All current sample names resolve from Home Assistant",
            "blocked": "Current samples return filtering evidence from Home Assistant",
            "partial": "Some samples or resolvers are filtered and others resolve",
            "unknown": "DNS observations are missing, stale, incomplete or inconclusive",
        }
        reasons.append(dns_reasons[dns])
        for _, obs in lists:
            reasons.extend(obs["issues"])
            reasons.extend(c["issue"] for c in obs["contexts"] if c.get("issue"))
        if not parent["device_count"]:
            status, label = "unknown", "No managed devices"
        elif blocked:
            status, label = (
                (
                    "restricted",
                    "Some devices restricted"
                    if len(covered_by_rules) < parent["device_count"]
                    else "Rule active",
                )
                if confirmed
                else ("unknown", "Rule unconfirmed")
            )
        elif profiles and parent["fresh"]:
            status, label = "inherited", "Filter configured"
        elif dns != "unknown":
            status, label = "dns_" + dns, dns_labels[dns]
        elif enabled:
            status, label = "scheduled", "Rule inactive now"
        else:
            status, label = "unknown", "Needs checking" if lists else "Not checked"
        result.append(
            {
                "id": category_id,
                "slug": slug,
                "name": category["name"],
                "icon": category["icon"],
                "supported": category_id in category_ids,
                "rules": matched,
                "state": status,
                "label": label,
                "reasons": list(dict.fromkeys(reasons)),
                "inherited": profiles,
                "dns": {
                    "verdict": dns,
                    "label": dns_labels[dns],
                    "lists": [key for key, _ in lists],
                },
                "scope": "Configuration and sample DNS observations; device traffic is not tested",
            }
        )
    return result, parent
