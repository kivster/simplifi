"""Current connection network IDs from a matched local UniFi session.

The active-client endpoint is never merged with saved /rest/user reservations.
Only a literal networkconf.external_id -> official ID match provides scope.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from .const import STALE_SECONDS
from .models import FamilyError, mac_address, utcnow
from .unifi_source import matching_unifi_api


def collection(response, limit):
    if not isinstance(response, dict) or not isinstance(response.get("data"), list):
        raise FamilyError("Current-network read returned an incomplete collection")
    meta = response.get("meta", {})
    if not isinstance(meta, dict) or meta.get("rc", "ok") != "ok" or len(response["data"]) >= limit:
        raise FamilyError("Current-network read failed or reached its collection limit")
    return response["data"]


def current_networks(network_response, client_response, official, now):
    """Never infer a connection from a name, VLAN number, reservation or old row."""
    networks = collection(network_response, 1000)
    clients = collection(client_response, 2000)
    mapping = {}
    seen_networks, seen_external = set(), set()
    for row in networks:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("_id"), str)
            or not row["_id"]
            or row["_id"] in seen_networks
        ):
            raise FamilyError("Ambiguous local network identities")
        seen_networks.add(row["_id"])
        external = row.get("external_id")
        # WAN/VPN entries need not be part of the official LAN collection.
        if external is None:
            continue
        if not isinstance(external, str) or not external or external in seen_external:
            raise FamilyError("Ambiguous official network identities")
        seen_external.add(external)
        if external in official:
            mapping[row["_id"]] = external
    result, seen_macs = {}, set()
    counts = {
        "network_rows": len(networks),
        "matched_networks": len(mapping),
        "client_rows": len(clients),
        "fresh_mapped_clients": 0,
        "unmapped_clients": 0,
        "stale_clients": 0,
    }
    for row in clients:
        try:
            mac = mac_address(row["mac"])
        except TypeError, KeyError, ValueError:
            raise FamilyError("Invalid current-client identity") from None
        if mac in seen_macs:
            raise FamilyError("Ambiguous current-client MAC identity")
        seen_macs.add(mac)
        value = row.get("last_seen")
        if type(value) not in (int, float):
            counts["stale_clients"] += 1
            continue
        try:
            seen = datetime.fromtimestamp(value, UTC)
        except ValueError, OverflowError, OSError:
            counts["stale_clients"] += 1
            continue
        if not now - timedelta(seconds=STALE_SECONDS) <= seen <= now + timedelta(seconds=15):
            counts["stale_clients"] += 1
            continue
        network = row.get("network_id")
        if not isinstance(network, str) or network not in mapping:
            counts["unmapped_clients"] += 1
            continue
        result[mac] = {"network": mapping[network], "observed_at": seen.isoformat()}
        counts["fresh_mapped_clients"] += 1
    return result, counts


class CurrentNetworkReader:
    """No stale mappings are returned, even when last-known diagnostics exist."""

    def __init__(self, hass, gateway):
        self.hass, self.gateway = hass, gateway
        self.last_attempt = None
        self.last_success = None
        self.counts = {}
        self.error: str | None = "Waiting for the first current-network read"

    async def read(self):
        self.last_attempt = utcnow()
        if self.gateway.simulation:
            self.error = "The offline simulator does not use a local UniFi session"
            return {}
        try:
            api = matching_unifi_api(self.hass, self.gateway)
            from aiounifi.models.api import ApiRequest

            async with asyncio.timeout(15):
                networks = await api.request(ApiRequest(method="get", path="/rest/networkconf"))
                clients = await api.request(ApiRequest(method="get", path="/stat/sta"))
            now = utcnow()
            result, counts = current_networks(networks, clients, self.gateway.networks, now)
        except FamilyError as err:
            self.error = str(err)
        except Exception:
            self.error = (
                "Current connection networks could not be read from the matching UniFi integration"
            )
        else:
            self.last_success, self.error, self.counts = now, None, counts
            return result
        # Previous successful scope is never reused for policy decisions.
        return {}

    def snapshot(self, now):
        fresh = bool(
            self.last_success
            and not self.error
            and now - self.last_success < timedelta(seconds=STALE_SECONDS)
        )
        return {
            "status": "available" if fresh else "stale" if self.last_success else "unavailable",
            "fresh": fresh,
            "observed_at": self.last_success.isoformat() if self.last_success else None,
            "issue": self.error,
            "counts": dict(self.counts),
            "source": "Matched Home Assistant UniFi integration · active connections",
            "identity": "Exact local network external_id to official network ID",
            "read_only": True,
        }
