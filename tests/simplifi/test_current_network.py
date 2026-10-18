"""Current connection IDs resolve IPv6 scope without trusting saved reservations."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiounifi.models.api import ApiRequest

from custom_components.simplifi.api.unifi import UniFiGateway
from custom_components.simplifi.current_network import CurrentNetworkReader, current_networks
from custom_components.simplifi.inventory import client_network
from custom_components.simplifi.models import CapabilityError, SimpliFiError

NOW = datetime(2026, 10, 14, 19, 55, tzinfo=UTC)
MAC = "00:11:22:33:44:55"
OFFICIAL = {"home": {"subnets": ["192.0.2.0/24"]}, "iot": {"subnets": ["198.51.100.0/24"]}}
NETWORKS = {
    "meta": {"rc": "ok"},
    "data": [
        {"_id": "legacy-home", "external_id": "home", "name": "Renamed network"},
        {"_id": "legacy-iot", "external_id": "iot", "name": "Home"},
        {"_id": "wan", "name": "WAN"},
    ],
}
CLIENTS = {
    "meta": {"rc": "ok"},
    "data": [
        {
            "mac": MAC,
            "network_id": "legacy-home",
            "last_seen": NOW.timestamp(),
            "fixed_ip": "198.51.100.15",
            "last_connection_network_id": "legacy-iot",
            "unexpected_secret": "hidden",
        }
    ],
}


def reader(host="192.0.2.1", site="default", port=443, state="LOADED", count=1):
    api = SimpleNamespace(request=AsyncMock(side_effect=[deepcopy(NETWORKS), deepcopy(CLIENTS)]))
    hub = SimpleNamespace(config=SimpleNamespace(host=host, port=port, site=site), api=api)
    entry = SimpleNamespace(state=SimpleNamespace(name=state), runtime_data=hub)
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda _: [entry] * count))
    gateway = SimpleNamespace(
        controller="https://192.0.2.1", legacy_site="default", simulation=False, networks=OFFICIAL
    )
    return CurrentNetworkReader(hass, gateway), api


def test_exact_identity_mapping_ignores_names_saved_ips_and_old_networks():
    result, counts = current_networks(NETWORKS, CLIENTS, OFFICIAL, NOW)
    assert result[MAC]["network"] == "home"
    assert counts == {
        "network_rows": 3,
        "matched_networks": 2,
        "client_rows": 1,
        "fresh_mapped_clients": 1,
        "unmapped_clients": 0,
        "stale_clients": 0,
    }
    assert "hidden" not in str(result) and "fixed_ip" not in str(result)
    assert client_network(
        "official-client",
        ip_address("2001:db8:123::1"),
        OFFICIAL,
        {"iot": {"official-client"}},
        result[MAC]["network"],
    ) == ("home", "current_network_id_reference_differs")
    # Both source APIs confirm Home while the fixed-IP reservation points to IoT.
    assert client_network(
        "official-client", ip_address("192.0.2.5"), OFFICIAL, {"iot": {"official-client"}}, "home"
    ) == ("home", "subnet_and_current_network_id_reference_differs")


def test_missing_prefix_link_local_and_overlapping_subnets_require_current_identity():
    for address in (None, ip_address("2001:db8:123::1"), ip_address("fe80::123")):
        assert client_network("c", address, OFFICIAL, {}, "home") == ("home", "current_network_id")
        with pytest.raises(CapabilityError):
            client_network("c", address, OFFICIAL, {"home": {"c"}})
    overlapping = {**OFFICIAL, "other": {"subnets": ["192.0.2.0/24"]}}
    assert client_network("c", ip_address("192.0.2.3"), overlapping, {}, "home") == (
        "home",
        "current_network_id",
    )
    with pytest.raises(CapabilityError):
        client_network("c", ip_address("198.51.100.3"), OFFICIAL, {}, "home")
    with pytest.raises(CapabilityError):
        client_network("c", None, OFFICIAL, {}, "not-an-official-network")


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        "1792007700",
        NOW.timestamp() - 91,
        NOW.timestamp() + 16,
        float("inf"),
        float("nan"),
    ],
)
def test_stale_malformed_and_future_rows_never_prove_scope(value):
    clients = deepcopy(CLIENTS)
    clients["data"][0]["last_seen"] = value
    result, counts = current_networks(NETWORKS, clients, OFFICIAL, NOW)
    assert result == {} and counts["stale_clients"] == 1


def test_absent_current_id_never_falls_back_to_historical_id_or_vlan_name():
    clients = deepcopy(CLIENTS)
    clients["data"][0].pop("network_id")
    result, counts = current_networks(NETWORKS, clients, OFFICIAL, NOW)
    assert result == {} and counts["unmapped_clients"] == 1
    networks = deepcopy(NETWORKS)
    networks["data"][0].pop("external_id")
    result, counts = current_networks(networks, CLIENTS, OFFICIAL, NOW)
    assert result == {} and counts["matched_networks"] == 1


@pytest.mark.parametrize(
    "source",
    [
        "duplicate_mac",
        "duplicate_network",
        "duplicate_external",
        "truncated",
        "wrong_meta",
        "invalid_row",
    ],
)
def test_ambiguous_or_malformed_collections_are_not_policy_evidence(source):
    networks, clients = deepcopy(NETWORKS), deepcopy(CLIENTS)
    if source == "duplicate_mac":
        clients["data"] *= 2
    if source == "duplicate_network":
        networks["data"].append(networks["data"][0])
    if source == "duplicate_external":
        networks["data"].append({"_id": "new-id", "external_id": "home"})
    if source == "truncated":
        clients["data"] *= 2000
    if source == "wrong_meta":
        clients["meta"] = None
    if source == "invalid_row":
        clients["data"] = [{"name": "Unknown"}]
    with pytest.raises(SimpliFiError):
        current_networks(networks, clients, OFFICIAL, NOW)


async def test_reader_uses_only_fixed_active_endpoints_and_never_reuses_stale_data():
    source, api = reader()
    with patch("custom_components.simplifi.current_network.utcnow", return_value=NOW):
        assert (await source.read())[MAC]["network"] == "home"
    assert [c.args[0] for c in api.request.call_args_list] == [
        ApiRequest(method="get", path="/rest/networkconf"),
        ApiRequest(method="get", path="/stat/sta"),
    ]
    assert source.snapshot(NOW)["fresh"]
    api.request.side_effect = RuntimeError("private credential body")
    with patch(
        "custom_components.simplifi.current_network.utcnow",
        return_value=NOW + timedelta(seconds=30),
    ):
        assert await source.read() == {}
    result = source.snapshot(NOW + timedelta(seconds=30))
    assert result["status"] == "stale" and not result["fresh"]
    assert "private credential" not in str(result) and MAC not in str(result)
    assert result["counts"]["fresh_mapped_clients"] == 1  # Explicitly last-known diagnostic only.


@pytest.mark.parametrize(
    "kwargs",
    [
        {"host": "other.local"},
        {"site": "other"},
        {"port": 8443},
        {"state": "NOT_LOADED"},
        {"count": 0},
        {"count": 2},
    ],
)
async def test_wrong_missing_or_ambiguous_session_never_reads(kwargs):
    source, api = reader(**kwargs)
    assert await source.read() == {}
    api.request.assert_not_called()
    assert source.snapshot(NOW)["status"] == "unavailable"


async def test_simulator_never_reads_real_session():
    source, api = reader()
    source.gateway.simulation = True
    assert await source.read() == {}
    api.request.assert_not_called()


async def test_discovery_maps_ipv6_only_and_addressless_clients_and_preserves_official_ids():
    gateway = UniFiGateway(None, "https://example.local", "test", site="s", networks=["home"])
    gateway.refresh_resources = AsyncMock()
    gateway.networks = deepcopy(OFFICIAL)
    gateway.current_network_reader = SimpleNamespace(
        read=AsyncMock(return_value={MAC: {"network": "home"}})
    )
    row = {
        "id": "official-client",
        "type": "WIRELESS",
        "name": "Tablet",
        "macAddress": MAC,
        "ipAddress": "2001:db8:123::4",
    }
    gateway.pages = AsyncMock(side_effect=[[row], []])
    gateway.request = AsyncMock(return_value={"referenceResources": []})
    with patch("custom_components.simplifi.api.unifi.registrant_database", return_value={}):
        devices = await gateway.discover()
    assert gateway.current_network_reader.read.await_count == 1
    assert devices[0].network == "home" and devices[0].network_source == "current_network_id"
    assert devices[0].id == "s:" + MAC and devices[0].ip == "2001:db8:123::4"
    # Optional-source failure retains normal subnet-only operation.
    row["ipAddress"] = "192.0.2.10"
    gateway.pages.side_effect = [[row], []]
    gateway.current_network_reader.read.return_value = {}
    with patch("custom_components.simplifi.api.unifi.registrant_database", return_value={}):
        assert (await gateway.discover())[0].network_source == "subnet_observation"
    row.pop("ipAddress")
    gateway.pages.side_effect = [[row], [], [row], []]
    with patch("custom_components.simplifi.api.unifi.registrant_database", return_value={}):
        with pytest.raises(CapabilityError):
            await gateway.discover()


async def test_current_connection_can_prove_a_roam_outside_managed_scope(household):
    engine, gateway, _, _ = household
    # This tests the existing engine scope contract with the new proof label.
    device = gateway.clients[0]
    device.network = "outside"
    device.network_source = "current_network_id"
    owner = engine.state.devices[device.id].group
    await engine.refresh()
    assert engine.state.devices[device.id].network == "outside"
    assert engine.state.devices[device.id].group == owner
