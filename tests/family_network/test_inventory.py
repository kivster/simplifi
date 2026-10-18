from copy import deepcopy
from datetime import timedelta
from ipaddress import ip_address
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.family_network.api.unifi import UniFiGateway
from custom_components.family_network.inventory import (
    client_network,
    client_references,
    mac_registrant,
    network_subnets,
)
from custom_components.family_network.models import CapabilityError, FamilyError, Rule, State
from custom_components.family_network.planner import plan

from .conftest import command


def test_current_subnet_mapping_and_saved_reference_conflicts():
    subnets = network_subnets(
        {
            "ipv4Configuration": {
                "hostIpAddress": "192.0.2.1",
                "prefixLength": 24,
                "additionalHostIpSubnets": ["198.51.100.1/24"],
            },
            "ipv6Configuration": {
                "interfaceType": "STATIC",
                "hostIpAddress": "2001:db8::1",
                "prefixLength": 64,
                "additionalHostIpSubnets": ["2001:db8:2::1/64"],
            },
        }
    )
    networks = {"a": {"subnets": subnets}, "b": {"subnets": ["203.0.113.0/24"]}}
    for address in ["192.0.2.10", "198.51.100.5", "2001:db8::10", "2001:db8:2::5"]:
        assert client_network("client", ip_address(address), networks, {}) == (
            "a",
            "subnet_observation",
        )
    assert client_network("client", ip_address("192.0.2.10"), networks, {"a": {"client"}}) == (
        "a",
        "subnet_and_reference",
    )
    assert client_network("client", ip_address("192.0.2.10"), networks, {"b": {"client"}}) == (
        "a",
        "subnet_observation_reference_differs",
    )
    # A saved fixed-IP reference cannot prove an IPv6-only client's current VLAN
    # when the delegated prefix is not provided by the official API.
    assert network_subnets({"ipv6Configuration": {"interfaceType": "PREFIX_DELEGATION"}}) == []
    for address in (None, ip_address("2001:db8:99::4")):
        with pytest.raises(CapabilityError):
            client_network("v6", address, networks, {"a": {"v6"}})
    with pytest.raises(CapabilityError):
        client_network(
            "c", ip_address("192.0.2.2"), {**networks, "overlap": {"subnets": ["192.0.2.0/25"]}}, {}
        )
    with pytest.raises(CapabilityError):
        client_network("c", None, networks, {"a": {"c"}, "b": {"c"}})
    with pytest.raises(FamilyError):
        network_subnets({"ipv4Configuration": {"additionalHostIpSubnets": ["invalid"]}})


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "referenceResources": [
                {
                    "resourceType": "CLIENT",
                    "referenceCount": 3,
                    "references": [{"referenceId": "c"}],
                }
            ]
        },
        {"referenceResources": [{"resourceType": "CLIENT", "referenceCount": 1}]},
        {
            "referenceResources": [
                {
                    "resourceType": "CLIENT",
                    "referenceCount": 2,
                    "references": [{"referenceId": "c"}, {"referenceId": "c"}],
                }
            ]
        },
    ],
)
def test_invalid_reference_read_is_not_complete(payload):
    with pytest.raises(FamilyError):
        client_references(payload)


def test_reference_resources_with_no_client_members_are_valid():
    assert (
        client_references({"referenceResources": [{"resourceType": "WIFI", "referenceCount": 1}]})
        == set()
    )
    assert client_references(
        {
            "referenceResources": [
                {
                    "resourceType": "CLIENT",
                    "referenceCount": 1,
                    "references": [{"referenceId": "c"}],
                }
            ]
        }
    ) == {"c"}


def test_registrants_use_longest_allocation_and_never_identify_private_mac():
    db = {"001122": "L", "0011223": "M", "001122334": "S", "021122": "Private"}
    assert mac_registrant("00:11:22:33:44:55", db) == ("S", "registered")
    assert mac_registrant("00:11:22:3f:44:55", db) == ("M", "registered")
    assert mac_registrant("00:11:22:ff:44:55", db) == ("L", "registered")
    assert mac_registrant("02:11:22:ff:44:55", db) == (None, "private")
    assert mac_registrant("00:22:22:ff:44:55", db) == (None, "unlisted")


async def test_discovery_reference_ipv6_and_uplink_observations():
    gateway = UniFiGateway(None, "https://example.local", "test", site="s", networks=["family"])
    gateway.refresh_resources = AsyncMock()
    gateway.networks = {
        "family": {"subnets": ["2001:db8::/64"]},
        "outside": {"subnets": ["203.0.113.0/24"]},
    }
    row = {
        "id": "c",
        "type": "WIRELESS",
        "name": "Tablet",
        "macAddress": "00:11:22:33:44:55",
        "ipAddress": "2001:db8::10",
        "connectedAt": "2026-10-14T12:00:00Z",
        "uplinkDeviceId": "ap",
    }
    gateway.pages = AsyncMock(side_effect=[[row], [{"id": "ap", "name": "Landing"}]])
    gateway.request = AsyncMock(
        side_effect=[
            {
                "referenceResources": [
                    {
                        "resourceType": "CLIENT",
                        "referenceCount": 1,
                        "references": [{"referenceId": "c"}],
                    }
                ]
            },
            {"referenceResources": []},
        ]
    )
    with patch(
        "custom_components.family_network.api.unifi.registrant_database",
        return_value={"001122": "Fictional"},
    ):
        devices = await gateway.discover()
    assert len(devices) == 1
    d = devices[0]
    assert (d.network, d.network_source, d.uplink_name, d.registrant) == (
        "family",
        "subnet_and_reference",
        "Landing",
        "Fictional",
    )
    assert d.connected_at == "2026-10-14T12:00:00+00:00" and d.last_seen and d.connected
    assert gateway.pages.await_count == 2


async def test_roaming_outside_scope_removes_policies_but_retains_owner(household):
    engine, gateway, now, _ = household
    engine.state.rules["r"] = Rule("r", "Video", "category", ["child"], [4])
    gateway.clients[0].network = "outside"
    outside = deepcopy(gateway.clients[0])
    outside.id = "new"
    outside.mac = "02:00:00:00:00:99"
    gateway.clients.append(outside)
    await engine.refresh()
    d = engine.state.devices[gateway.clients[0].id]
    assert d.network == "outside" and d.group == "child"
    assert "new" not in engine.state.devices
    policies = plan(
        engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0]
    )
    assert all(
        body["source"]["trafficFilter"]["macAddressFilter"] != d.mac for body in policies.values()
    )
    gateway.clients[0].network = "demo-family"
    await engine.refresh()
    assert engine.state.devices[d.id].group == "child"
    assert (
        len(plan(engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0]))
        == 2
    )


async def test_absence_and_failure_have_distinct_presence_semantics(household):
    engine, gateway, now, _ = household
    await engine.refresh()
    key = gateway.clients[0].id
    gateway.clients = []
    now[0] += timedelta(minutes=1)
    await engine.refresh()
    assert not engine.state.devices[key].connected
    last = engine.state.to_dict()
    gateway.failure = "inventory"
    with pytest.raises(FamilyError):
        await engine.refresh()
    assert engine.state.to_dict()["devices"] == last["devices"]
    assert not engine.state.inventory_complete


async def test_forget_present_client_rediscovers_unassigned_and_removes_exclusion(household):
    engine, gateway, _, _ = household
    key = gateway.clients[0].id
    engine.state.quarantine_excluded = [key]
    with pytest.raises(FamilyError):
        await command(engine, "forget_device", device_id=key, confirm=False)
    revision = engine.state.revision
    await command(
        engine,
        "forget_device",
        device_id=key,
        confirm=True,
        expected_revision=revision,
        request_id="forget",
    )
    assert key not in engine.state.devices and key not in engine.state.quarantine_excluded
    await engine.refresh()
    assert engine.state.devices[key].group is None
    # A retry after rediscovery must not forget a newly assigned owner.
    await command(engine, "assign_device", device_id=key, group_id="child")
    await command(
        engine,
        "forget_device",
        device_id=key,
        confirm=True,
        expected_revision=revision,
        request_id="forget",
    )
    assert engine.state.devices[key].group == "child"


def test_older_devices_load_with_optional_observation_fields(household):
    raw = household[0].state.to_dict()
    for d in raw["devices"].values():
        for key in (
            "connected_at",
            "network_source",
            "uplink_name",
            "registrant",
            "registrant_status",
        ):
            d.pop(key)
    restored = State.from_dict(raw)
    assert all(
        d.connected_at is None and d.registrant_status == "unavailable"
        for d in restored.devices.values()
    )


async def test_reference_http_failure_falls_back_but_truncation_freezes():
    gateway = UniFiGateway(None, "https://example.local", "test", site="s", networks=["family"])
    gateway.refresh_resources = AsyncMock()
    gateway.networks = {"family": {"subnets": ["192.0.2.0/24"]}}
    row = {
        "id": "c",
        "type": "WIRED",
        "name": "Computer",
        "macAddress": "00:11:22:33:44:55",
        "ipAddress": "192.0.2.4",
    }
    gateway.pages = AsyncMock(side_effect=[[row], FamilyError("No device names")])
    gateway.request = AsyncMock(side_effect=FamilyError("Gateway HTTP 500"))
    with patch(
        "custom_components.family_network.api.unifi.registrant_database", side_effect=OSError
    ):
        devices = await gateway.discover()
    assert devices[0].network_source == "subnet_observation"
    assert devices[0].uplink_name is None and devices[0].registrant_status == "unavailable"
    assert gateway.networks["family"]["reference_status"] == "unavailable"
    gateway.pages = AsyncMock(return_value=[row])
    gateway.request = AsyncMock(
        return_value={"referenceResources": [{"resourceType": "CLIENT", "referenceCount": 1}]}
    )
    with pytest.raises(FamilyError, match="Truncated"):
        await gateway.discover()


def test_bundled_registry_is_readable_and_ambiguous_allocations_are_not_identified():
    from custom_components.family_network.inventory import registrant_database

    database = registrant_database()
    assert len(database) > 50000
    assert mac_registrant("08:00:30:00:00:01", database) == (None, "ambiguous")
    assert mac_registrant("00:00:0c:00:00:01", database)[1] == "registered"
