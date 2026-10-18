"""Read existing filtering through a matching, already-authenticated HA UniFi hub.

The local Network UI API is separate from the official policy API. This adapter
only issues fixed GET requests and never copies credentials or changes filters.
"""

import asyncio
import ipaddress
from copy import deepcopy
from datetime import timedelta

from .models import SimpliFiError
from .unifi_source import matching_unifi_api

MAX_PROFILES = 1000
MAX_ITEMS = 10000


def _strings(row, key):
    value = row.get(key)
    if (
        not isinstance(value, list)
        or len(value) > MAX_ITEMS
        or any(not isinstance(item, str) or len(item) > 500 for item in value)
    ):
        raise SimpliFiError("Incomplete filtering response")
    return list(value)


def normalize_profiles(response, network_response, official_networks=None):
    """Keep only the documented display fields; reject incomplete collection reads."""
    rows = response.get("data") if isinstance(response, dict) else response
    networks = network_response.get("data") if isinstance(network_response, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_PROFILES or not isinstance(networks, list):
        raise SimpliFiError("Incomplete filtering response")
    names = {
        row["_id"]: row["name"]
        for row in networks
        if isinstance(row, dict)
        and isinstance(row.get("_id"), str)
        and isinstance(row.get("name"), str)
    }
    mapping = {}
    normalized_subnets: list[str | None] = []
    for item in networks:
        try:
            normalized_subnets.append(
                str(ipaddress.ip_network(item.get("ip_subnet", ""), strict=False))
            )
        except ValueError, AttributeError:
            normalized_subnets.append(None)
    for network in networks:
        try:
            subnet = str(ipaddress.ip_network(network.get("ip_subnet", ""), strict=False))
        except ValueError, AttributeError:
            continue
        candidates = [
            key for key, value in (official_networks or {}).items() if value.get("subnet") == subnet
        ]
        if len(candidates) == 1 and normalized_subnets.count(subnet) == 1:
            mapping[network["_id"]] = candidates[0]
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SimpliFiError("Incomplete filtering response")
        key = row.get("_id")
        if (
            not isinstance(key, str)
            or not key
            or key in seen
            or not isinstance(row.get("name"), str)
        ):
            raise SimpliFiError("Invalid filtering identity")
        if type(row.get("enabled")) is not bool:
            raise SimpliFiError("Unknown filtering enabled state")
        seen.add(key)
        network_ids = _strings(row, "network_ids")
        clients = _strings(row, "client_macs")
        schedule = row.get("schedule")
        if not isinstance(schedule, dict) or not isinstance(schedule.get("mode"), str):
            raise SimpliFiError("Unknown filtering schedule")
        # Scheduling fields are displayed as configuration, never evaluated as
        # evidence of traffic blocking. No arbitrary controller fields escape.
        schedule_view = {"mode": schedule["mode"]}
        for field in ("days", "time_all_day", "time_start", "time_end", "date_start", "date_end"):
            if field in schedule:
                value = schedule[field]
                if isinstance(value, (str, bool)) or (
                    isinstance(value, list) and all(isinstance(v, str) for v in value)
                ):
                    schedule_view[field] = deepcopy(value)
        result.append(
            {
                "id": key,
                "name": row["name"][:200],
                "enabled": row["enabled"],
                "categories": _strings(row, "categories"),
                "safe_search": _strings(row, "safe_search"),
                "allow_list": _strings(row, "allow_list"),
                "block_list": _strings(row, "block_list"),
                "networks": [
                    {
                        "id": key,
                        "name": names.get(key, "Unknown network"),
                        "official_id": mapping.get(key),
                    }
                    for key in network_ids
                ],
                "client_macs": clients,
                "schedule": schedule_view,
            }
        )
    return sorted(result, key=lambda row: (row["name"].casefold(), row["id"]))


class ProtectionReader:
    """Optional readback failure never interrupts the policy reconciler."""

    def __init__(self, hass, gateway):
        self.hass = hass
        self.gateway = gateway
        self.last_attempt = None
        self.last_success = None
        self.profiles = []
        self.source = "Home Assistant UniFi Network integration · local read-only API"
        self.error: str | None = "Waiting for the first filtering read"

    def _source(self):
        return matching_unifi_api(self.hass, self.gateway)

    async def refresh(self, now):
        if self.last_attempt and now - self.last_attempt < timedelta(seconds=60):
            return
        self.last_attempt = now
        if self.gateway.simulation:
            self.source = "Offline simulator · fictional filtering configuration"
            self.profiles = [
                {
                    "id": "demo-protection",
                    "name": "Demo family filtering",
                    "enabled": True,
                    "categories": ["ADULT", "MALWARE"],
                    "safe_search": ["GOOGLE", "BING", "YOUTUBE"],
                    "allow_list": ["example.com"],
                    "block_list": [],
                    "networks": [
                        {
                            "id": "demo-family",
                            "name": "Demo SimpliFi",
                            "official_id": "demo-family",
                        }
                    ],
                    "client_macs": [],
                    "schedule": {"mode": "ALWAYS"},
                }
            ]
            self.last_success, self.error = now, None
            return
        try:
            api = self._source()
            from aiounifi.models.api import ApiRequest, ApiRequestV2

            async with asyncio.timeout(15):
                filters = await api.request(ApiRequestV2(method="get", path="/content-filtering"))
                networks = await api.request(ApiRequest(method="get", path="/rest/networkconf"))
            profiles = normalize_profiles(filters, networks, self.gateway.networks)
        except SimpliFiError as error:
            self.error = str(error)
        except Exception:
            # aiounifi errors may contain the controller's response. Never put
            # those bodies into entities, logs or the dashboard.
            self.error = "UniFi filtering read failed; check the existing UniFi integration connection and permissions"
        else:
            self.profiles = profiles
            self.last_success, self.error = now, None

    def snapshot(self, now):
        fresh = bool(
            self.last_success
            and not self.error
            and now - self.last_success < timedelta(seconds=120)
        )
        return {
            "status": "available" if fresh else "stale" if self.last_success else "unavailable",
            "fresh": fresh,
            "source": self.source,
            "issue": self.error,
            "observed_at": self.last_success.isoformat() if self.last_success else None,
            "profiles": deepcopy(self.profiles),
            "profile_count": len(self.profiles),
            "scope": "All filtering profiles on the matched UniFi site",
            "limit": MAX_PROFILES,
            "read_only": True,
        }
