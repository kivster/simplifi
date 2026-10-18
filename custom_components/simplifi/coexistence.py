"""Read-only policy context. Address matches never assert packet enforcement."""

import asyncio
import ipaddress
from copy import deepcopy
from datetime import timedelta
from typing import Any

from .const import STALE_SECONDS
from .models import SimpliFiError, instant, mac_address
from .planner import policy_matches
from .unifi_source import matching_unifi_entry

MAX_POLICIES = 10000
MAX_ORDER_PAIRS = 64
CONTROL_KINDS = {
    "block": "Client access",
    "firewall_policy": "Firewall policy",
    "traffic_rule": "Traffic rule",
    "traffic_route": "Traffic route",
    "dpi": "Application restriction",
    "wlan": "Wi-Fi network",
    "port": "Switch port",
    "poe": "Power over Ethernet",
    "object_oriented_network_config": "Policy engine",
}


def strings(values):
    if (
        not isinstance(values, list)
        or len(values) > 1000
        or any(
            not isinstance(v, (str, int)) or isinstance(v, bool) or len(str(v)) > 500
            for v in values
        )
    ):
        raise SimpliFiError("Policy selector is incomplete or exceeds its display limit")
    return values


def and_match(*values):
    return False if False in values else None if None in values else True


def ip_match(selector, address):
    if selector.get("type") != "IP_ADDRESSES" or type(selector.get("matchOpposite")) is not bool:
        return None
    try:
        ip = ipaddress.ip_address(address)
        matches = []
        for item in selector["items"]:
            kind = item.get("type")
            if kind == "IP_ADDRESS":
                matches.append(ip == ipaddress.ip_address(item["value"]))
            elif kind == "SUBNET":
                matches.append(ip in ipaddress.ip_network(item["value"], strict=False))
            elif kind == "IP_ADDRESS_RANGE":
                start, stop = (
                    ipaddress.ip_address(item["start"]),
                    ipaddress.ip_address(item["stop"]),
                )
                matches.append(
                    start.version == ip.version == stop.version
                    and int(start) <= int(ip) <= int(stop)
                )
            else:
                return None
        if not matches:
            return None
        return any(matches) != selector["matchOpposite"]
    except ValueError, TypeError, KeyError:
        return None


def source_match(policy, device, networks):
    """Tri-state match of known source addresses; ports/protocols are separate conditions."""
    try:
        return _source_match(policy, device, networks)
    except SimpliFiError, ValueError, TypeError, AttributeError, KeyError:
        return None


def _source_match(policy, device, networks):
    network = networks.get(device.network)
    if not network or not network.get("zone"):
        return None
    source = policy["source"]
    if source["zoneId"] != network["zone"]:
        return False
    selector = source.get("trafficFilter")
    if selector is None:
        return True
    kind = selector.get("type")
    result = None
    if kind == "NETWORK":
        selected = selector.get("networkFilter", {})
        if type(selected.get("matchOpposite")) is bool:
            result = (device.network in strings(selected.get("networkIds"))) != selected[
                "matchOpposite"
            ]
    elif kind == "MAC_ADDRESS":
        try:
            result = device.mac in [
                mac_address(v)
                for v in strings(selector.get("macAddressFilter", {}).get("macAddresses"))
            ]
        except ValueError, TypeError:
            result = None
    elif kind == "IP_ADDRESS":
        result = ip_match(selector.get("ipAddressFilter", {}), device.ip)
        # The inventory contains one observed address, not every IPv4/IPv6 address.
        # A negative result therefore cannot exclude the device's other addresses.
        if result is False:
            result = None
    if kind in ("NETWORK", "IP_ADDRESS") and selector.get("macAddressFilter") is not None:
        try:
            result = and_match(result, device.mac == mac_address(selector["macAddressFilter"]))
        except ValueError, TypeError:
            result = and_match(result, None)
    return result


def port_text(spec):
    if spec.get("type") != "PORTS":
        return "Port list · membership not evaluated"
    values = [
        str(v.get("value", v.get("start", "?"))) + ("–" + str(v["stop"]) if "stop" in v else "")
        for v in spec.get("items", [])
    ]
    return ("Except ports: " if spec.get("matchOpposite") else "Ports: ") + ", ".join(
        strings(values)
    )


def selector_text(selector, gateway):
    if selector is None:
        return "All traffic in this zone"
    kind = selector.get("type", "Unknown")
    text = kind.replace("_", " ").capitalize()
    if kind == "NETWORK":
        spec = selector.get("networkFilter", {})
        ids = strings(spec.get("networkIds"))
        text = ("Except networks: " if spec.get("matchOpposite") else "Networks: ") + ", ".join(
            gateway.networks.get(key, {}).get("name", key) for key in ids
        )
    elif kind == "MAC_ADDRESS":
        text = "Devices: " + ", ".join(
            strings(selector.get("macAddressFilter", {}).get("macAddresses"))
        )
    elif kind in ("APPLICATION", "APPLICATION_CATEGORY"):
        category = kind == "APPLICATION_CATEGORY"
        field, ids_key = (
            ("applicationCategoryFilter", "applicationCategoryIds")
            if category
            else ("applicationFilter", "applicationIds")
        )
        names = {
            r["id"]: r["name"] for r in (gateway.categories if category else gateway.applications)
        }
        text = ("Categories: " if category else "Applications: ") + ", ".join(
            names.get(key, str(key)) for key in strings(selector.get(field, {}).get(ids_key))
        )
    elif kind == "DOMAIN":
        spec = selector.get("domainFilter", {})
        if spec.get("type") == "DOMAINS":
            text = "Domains: " + ", ".join(strings(spec.get("domains")))
        else:
            text = "Domain list · membership not evaluated"
    elif kind == "IP_ADDRESS":
        spec = selector.get("ipAddressFilter", {})
        if spec.get("type") == "IP_ADDRESSES":
            values = []
            for item in spec.get("items", []):
                values.append(
                    str(item.get("value", item.get("start", "?")))
                    + ("–" + str(item["stop"]) if "stop" in item else "")
                )
            text = (
                "Except addresses: " if spec.get("matchOpposite") else "Addresses: "
            ) + ", ".join(strings(values))
        else:
            text = "Address list · membership not evaluated"
    if kind in ("NETWORK", "IP_ADDRESS") and selector.get("macAddressFilter"):
        text += " · device " + str(selector["macAddressFilter"])
    if selector.get("portFilter"):
        text += " · " + port_text(selector["portFilter"])
    return text[:3000]


def normalize_policy(row, gateway):
    if (
        not isinstance(row, dict)
        or not isinstance(row.get("id"), str)
        or not row["id"]
        or not isinstance(row.get("name"), str)
        or type(row.get("enabled")) is not bool
    ):
        raise SimpliFiError("Policy identity or enabled state is incomplete")
    for side in ("source", "destination"):
        value = row.get(side)
        if not isinstance(value, dict) or not isinstance(value.get("zoneId"), str):
            raise SimpliFiError("Policy zone scope is incomplete")
        if value.get("trafficFilter") is not None and not isinstance(value["trafficFilter"], dict):
            raise SimpliFiError("Policy traffic selector is incomplete")
    action = row.get("action", {}).get("type")
    if action not in ("ALLOW", "BLOCK", "REJECT"):
        raise SimpliFiError("Policy action is unsupported")
    zones = {z["id"]: z["name"] for z in getattr(gateway, "zones", [])}
    conditions = []
    scope = row.get("ipProtocolScope", {})
    conditions.append(str(scope.get("ipVersion", "Unknown IP version")))
    if scope.get("protocolFilter"):
        spec = scope["protocolFilter"]
        protocol = spec.get("protocol", {}).get(
            "name", spec.get("preset", {}).get("name", spec.get("protocolNumber", "Unknown"))
        )
        conditions.append(
            ("Except protocol: " if spec.get("matchOpposite") else "Protocol: ")
            + str(protocol)[:100]
        )
    if row.get("connectionStateFilter"):
        conditions.append("Connection states: " + ", ".join(strings(row["connectionStateFilter"])))
    if row.get("ipsecFilter"):
        conditions.append("IPsec condition")
    schedule = row.get("schedule")
    if schedule is None:
        schedule_text = "Always configured"
    elif isinstance(schedule, dict) and isinstance(schedule.get("mode"), str):
        schedule_text = schedule["mode"].replace("_", " ").capitalize()
        for key in ("date", "startDate", "stopDate"):
            if key in schedule:
                schedule_text += " · " + str(schedule[key])[:100]
        if schedule.get("repeatOnDays"):
            schedule_text += " · " + ", ".join(strings(schedule["repeatOnDays"]))
        if schedule.get("timeFilter"):
            schedule_text += (
                " · "
                + str(schedule["timeFilter"].get("startTime", "?"))[:20]
                + "–"
                + str(schedule["timeFilter"].get("stopTime", "?"))[:20]
            )
        schedule_text += " · gateway timing not evaluated"
    else:
        schedule_text = "Unknown schedule"
    return {
        "id": row["id"],
        "name": row["name"][:200] or "Unnamed policy",
        "origin": row.get("metadata", {}).get("origin", "UNKNOWN"),
        "enabled": row["enabled"],
        "action": action,
        "index": row.get("index") if type(row.get("index")) is int else None,
        "source_zone": zones.get(row["source"]["zoneId"], row["source"]["zoneId"]),
        "destination_zone": zones.get(row["destination"]["zoneId"], row["destination"]["zoneId"]),
        "internet_destination": row["destination"]["zoneId"] == gateway.external_zone,
        "source": selector_text(row["source"].get("trafficFilter"), gateway),
        "destination": selector_text(row["destination"].get("trafficFilter"), gateway),
        "conditions": conditions,
        "schedule": schedule_text,
    }


def ordering_positions(response, pair, policies):
    result, seen = {}, set()
    value = response.get("orderedFirewallPolicyIds", {})
    for section in ("beforeSystemDefined", "afterSystemDefined"):
        ids = strings(value.get(section))
        for index, key in enumerate(ids, 1):
            row = policies.get(key)
            if (
                key in seen
                or not row
                or (row["source"]["zoneId"], row["destination"]["zoneId"]) != pair
            ):
                raise SimpliFiError("Ordering disagrees with the policy collection")
            seen.add(key)
            result[key] = {"section": section, "position": index}
    expected = {
        key
        for key, row in policies.items()
        if row.get("metadata", {}).get("origin") == "USER_DEFINED"
        and (row["source"]["zoneId"], row["destination"]["zoneId"]) == pair
    }
    if not expected <= seen:
        raise SimpliFiError("Ordering omitted user-defined policies")
    return result


class CoexistenceReader:
    """Independent observations never mutate state or participate in policy planning."""

    def __init__(self, hass, gateway):
        self.hass, self.gateway = hass, gateway
        self.last_attempt = self.last_success = None
        self.policies, self.views, self.positions = {}, {}, {}
        self.ordering = {"status": "unavailable", "pairs": 0, "read": 0, "failed": 0}
        self.error: str | None = "Waiting for policy readback"
        self.controls: dict[str, Any] = {
            "status": "unavailable",
            "items": [],
            "issue": "Waiting for the existing UniFi integration",
        }

    async def refresh(self, now):
        if self.last_attempt and now - self.last_attempt < timedelta(seconds=60):
            return
        self.last_attempt = now
        try:
            async with asyncio.timeout(20):
                policies = await self.gateway.list_policies()
            if not isinstance(policies, dict) or len(policies) > MAX_POLICIES:
                raise SimpliFiError("Policy collection is incomplete or capped")
            views = {key: normalize_policy(row, self.gateway) for key, row in policies.items()}
            if any(row["id"] != key for key, row in policies.items()):
                raise SimpliFiError("Policy identities disagree")
        except Exception:
            self.error = "Policy readback failed; last-known rules are not current evidence"
        else:
            self.policies, self.views = deepcopy(policies), views
            self.last_success, self.error = now, None
            pairs = sorted(
                {(r["source"]["zoneId"], r["destination"]["zoneId"]) for r in policies.values()}
            )
            semaphore = asyncio.Semaphore(4)

            async def read_pair(pair):
                async with semaphore:
                    try:
                        async with asyncio.timeout(10):
                            response = await self.gateway.policy_ordering(*pair)
                        return ordering_positions(response, pair, policies)
                    except Exception:
                        return None

            try:
                async with asyncio.timeout(20):
                    results = await asyncio.gather(
                        *(read_pair(pair) for pair in pairs[:MAX_ORDER_PAIRS])
                    )
            except TimeoutError:
                results = [None] * min(len(pairs), MAX_ORDER_PAIRS)
            self.positions = {
                key: value
                for result in results
                if result is not None
                for key, value in result.items()
            }
            failed = sum(r is None for r in results)
            self.ordering = {
                "status": "capped"
                if len(pairs) > MAX_ORDER_PAIRS
                else "partial"
                if failed
                else "available",
                "pairs": len(pairs),
                "read": len(results) - failed,
                "failed": failed,
                "limit": MAX_ORDER_PAIRS,
            }
        self.read_controls(now)

    def read_controls(self, now):
        if self.gateway.simulation:
            self.controls = {
                "status": "available",
                "items": [],
                "issue": None,
                "observed_at": now.isoformat(),
                "simulation": True,
            }
            return
        try:
            from homeassistant.helpers import entity_registry as er

            entry = matching_unifi_entry(self.hass, self.gateway)
            items = []
            for entity in er.async_entries_for_config_entry(
                er.async_get(self.hass), entry.entry_id
            ):
                kind = entity.unique_id.split("-", 1)[0]
                if entity.domain != "switch":
                    continue
                current = self.hass.states.get(entity.entity_id)
                items.append(
                    {
                        "entity_id": entity.entity_id,
                        "name": entity.name
                        or (current.attributes.get("friendly_name") if current else None)
                        or entity.original_name
                        or entity.entity_id,
                        "kind": CONTROL_KINDS.get(kind, "Other UniFi switch"),
                        "registry_enabled": entity.disabled_by is None,
                        "hidden": entity.hidden_by is not None,
                        "state": current.state if current else "not_loaded",
                    }
                )
            if len(items) > MAX_POLICIES:
                raise SimpliFiError("Alternate control inventory is capped")
            self.controls = {
                "status": "available",
                "items": sorted(items, key=lambda r: r["name"].casefold()),
                "issue": None,
                "observed_at": now.isoformat(),
                "simulation": False,
            }
        except Exception:
            self.controls = {
                **self.controls,
                "status": "stale" if self.controls["items"] else "unavailable",
                "issue": "Alternate controls could not be read from the matching UniFi integration",
            }

    def snapshot(self, now, state):
        fresh = bool(
            self.last_success
            and not self.error
            and timedelta(0) <= now - self.last_success < timedelta(seconds=120)
        )
        owned = {
            r["id"]: r
            for r in state.owned.values()
            if (r["controller"], r["site"]) == (state.controller, state.site)
        }
        current_devices = bool(
            state.inventory_complete
            and state.last_observed
            and 0 <= (now - instant(state.last_observed)).total_seconds() < STALE_SECONDS
        )
        rows = []
        for key, view in self.views.items():
            row = {
                **deepcopy(view),
                "order": self.positions.get(key),
                "matched_groups": [],
                "possible_groups": [],
            }
            record = owned.get(key)
            row["ownership"] = (
                (
                    "managed"
                    if policy_matches(self.policies[key], record["body"], record["fingerprint"])
                    else "drift"
                )
                if record
                else "external"
            )
            if (
                record
                and record.get("readback_at")
                and self.last_success
                and instant(record["readback_at"]) > self.last_success
            ):
                row["ownership"] = "pending"
            for group in state.groups.values():
                devices = [d for d in state.devices.values() if d.group == group.id]
                matches = [
                    source_match(self.policies[key], d, self.gateway.networks)
                    if fresh and current_devices and d.connected
                    else None
                    for d in devices
                ]
                if True in matches:
                    row["matched_groups"].append(group.id)
                if None in matches:
                    row["possible_groups"].append(group.id)
            rows.append(row)
        rows.sort(
            key=lambda r: (
                r["source_zone"],
                r["destination_zone"],
                r["index"] if r["index"] is not None else float("inf"),
                r["name"],
            )
        )
        controls = deepcopy(self.controls)
        if self.last_attempt and now - self.last_attempt >= timedelta(seconds=120):
            controls["status"] = "stale" if controls["items"] else "unavailable"
        return {
            "status": "available" if fresh else "stale" if self.last_success else "unavailable",
            "fresh": fresh,
            "issue": self.error,
            "observed_at": self.last_success.isoformat() if self.last_success else None,
            "policies": rows,
            "policy_count": len(rows),
            "limit": MAX_POLICIES,
            "ordering": deepcopy(self.ordering),
            "controls": controls,
            "read_only": True,
            "source": "Offline simulator"
            if self.gateway.simulation
            else "UniFi official local API · complete site policy collection",
        }
