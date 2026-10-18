"""Read-only context must not imply ownership, caller permission or enforcement."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.family_network.coexistence import (
    MAX_ORDER_PAIRS,
    CoexistenceReader,
    normalize_policy,
    ordering_positions,
    source_match,
)
from custom_components.family_network.models import FamilyError
from custom_components.family_network.planner import policy_fingerprint


def policy(key="foreign", **changes):
    return {
        "id": key,
        "name": "Other rule",
        "enabled": True,
        "index": 5,
        "metadata": {"origin": "USER_DEFINED"},
        "action": {"type": "BLOCK"},
        "source": {
            "zoneId": "demo-home",
            "trafficFilter": {
                "type": "NETWORK",
                "networkFilter": {"networkIds": ["demo-family"], "matchOpposite": False},
            },
        },
        "destination": {"zoneId": "demo-internet"},
        "ipProtocolScope": {"ipVersion": "IPV4_AND_IPV6"},
        "loggingEnabled": False,
        **changes,
    }


@pytest.mark.parametrize(
    "opposite,selected,expected",
    [(False, True, True), (False, False, False), (True, True, False), (True, False, True)],
)
def test_source_network_exclusions_and_zone_conjunction(household, opposite, selected, expected):
    engine, gateway, _, _ = household
    device = next(iter(engine.state.devices.values()))
    row = policy()
    row["source"]["trafficFilter"]["networkFilter"] = {
        "networkIds": [device.network if selected else "other"],
        "matchOpposite": opposite,
    }
    assert source_match(row, device, gateway.networks) is expected
    row["source"]["zoneId"] = "other-zone"
    assert source_match(row, device, gateway.networks) is False


def test_network_and_mac_are_both_required_and_invalid_mac_is_unknown(household):
    engine, gateway, _, _ = household
    device = next(iter(engine.state.devices.values()))
    row = policy()
    selector = row["source"]["trafficFilter"]
    selector["macAddressFilter"] = device.mac.upper()
    assert source_match(row, device, gateway.networks) is True
    selector["macAddressFilter"] = "02:00:00:00:00:99"
    assert source_match(row, device, gateway.networks) is False
    selector["macAddressFilter"] = "invalid"
    assert source_match(row, device, gateway.networks) is None
    selector["macAddressFilter"] = {"secret": "not a MAC"}
    assert source_match(row, device, gateway.networks) is None


@pytest.mark.parametrize(
    "selector",
    [
        {"type": "IP_ADDRESS", "value": "192.0.2.10"},
        {"type": "SUBNET", "value": "192.0.2.0/24"},
        {"type": "IP_ADDRESS_RANGE", "start": "192.0.2.9", "stop": "192.0.2.11"},
    ],
)
def test_ip_source_matches_but_nonmatch_does_not_exclude_other_addresses(household, selector):
    engine, gateway, _, _ = household
    device = next(iter(engine.state.devices.values()))
    row = policy()
    row["source"]["trafficFilter"] = {
        "type": "IP_ADDRESS",
        "ipAddressFilter": {"type": "IP_ADDRESSES", "matchOpposite": False, "items": [selector]},
    }
    assert source_match(row, device, gateway.networks) is True
    row["source"]["trafficFilter"]["ipAddressFilter"]["matchOpposite"] = True
    assert source_match(row, device, gateway.networks) is None
    device.ip = None
    assert source_match(row, device, gateway.networks) is None


def test_unknown_selectors_remain_possible_and_explicit_mac_list_is_supported(household):
    engine, gateway, _, _ = household
    device = next(iter(engine.state.devices.values()))
    row = policy()
    row["source"]["trafficFilter"] = {"type": "IPV6_IID"}
    assert source_match(row, device, gateway.networks) is None
    row["source"]["trafficFilter"] = {
        "type": "MAC_ADDRESS",
        "macAddressFilter": {"macAddresses": [device.mac]},
    }
    assert source_match(row, device, gateway.networks) is True
    row["source"]["trafficFilter"] = None
    assert source_match(row, device, gateway.networks) is True
    assert source_match(row, device, {}) is None


async def test_reader_preserves_foreign_policies_and_requires_recorded_fingerprint_ownership(
    household,
):
    engine, gateway, now, _ = household
    gateway.policies = {
        "foreign": policy(name="Family Network deceptive prefix", unexpected_secret="withheld")
    }
    original = deepcopy(gateway.policies)
    reader = CoexistenceReader(None, gateway)
    await reader.refresh(now[0])
    result = reader.snapshot(now[0], engine.state)
    assert result["fresh"] and result["policy_count"] == 1
    assert result["policies"][0]["ownership"] == "external"
    assert result["policies"][0]["matched_groups"] == ["child"]
    assert "withheld" not in str(result)
    assert gateway.policies == original and gateway.counter == 0
    engine.state.owned["key"] = {
        "id": "foreign",
        "controller": engine.state.controller,
        "site": engine.state.site,
        "fingerprint": policy_fingerprint(original["foreign"]),
    }
    assert reader.snapshot(now[0], engine.state)["policies"][0]["ownership"] == "managed"
    engine.state.owned["key"]["fingerprint"] = "different"
    assert reader.snapshot(now[0], engine.state)["policies"][0]["ownership"] == "drift"


async def test_stale_and_offline_matches_never_become_current(household):
    engine, gateway, now, _ = household
    gateway.policies = {"foreign": policy()}
    reader = CoexistenceReader(None, gateway)
    await reader.refresh(now[0])
    for d in engine.state.devices.values():
        d.connected = False
    result = reader.snapshot(now[0], engine.state)
    assert result["policies"][0]["matched_groups"] == []
    assert result["policies"][0]["possible_groups"] == ["child"]
    gateway.list_policies = AsyncMock(side_effect=RuntimeError("secret server body"))
    await reader.refresh(now[0] + timedelta(seconds=61))
    result = reader.snapshot(now[0] + timedelta(seconds=61), engine.state)
    assert not result["fresh"] and result["status"] == "stale" and result["policy_count"] == 1
    assert "secret server body" not in str(result)


async def test_empty_collection_and_failed_collection_are_distinct_and_reads_are_throttled(
    household,
):
    engine, gateway, now, _ = household
    gateway.list_policies = AsyncMock(return_value={})
    reader = CoexistenceReader(None, gateway)
    await reader.refresh(now[0])
    await reader.refresh(now[0] + timedelta(seconds=30))
    gateway.list_policies.assert_awaited_once()
    assert reader.snapshot(now[0], engine.state)["status"] == "available"
    assert reader.snapshot(now[0], engine.state)["policy_count"] == 0
    assert reader.snapshot(now[0] + timedelta(seconds=121), engine.state)["status"] == "stale"
    other = CoexistenceReader(None, gateway)
    gateway.list_policies.side_effect = FamilyError("failed")
    await other.refresh(now[0])
    assert other.snapshot(now[0], engine.state)["status"] == "unavailable"


async def test_order_failure_does_not_discard_valid_policies_or_invent_precedence(household):
    engine, gateway, now, _ = household
    gateway.policies = {"foreign": policy()}
    gateway.policy_ordering = AsyncMock(side_effect=RuntimeError("secret response"))
    reader = CoexistenceReader(None, gateway)
    await reader.refresh(now[0])
    s = reader.snapshot(now[0], engine.state)
    assert s["fresh"] and s["ordering"]["status"] == "partial" and s["ordering"]["failed"] == 1
    assert s["policies"][0]["order"] is None


async def test_old_inventory_cannot_confirm_scope_even_with_fresh_policies(household):
    engine, gateway, now, _ = household
    gateway.policies = {"foreign": policy()}
    reader = CoexistenceReader(None, gateway)
    await reader.refresh(now[0])
    result = reader.snapshot(now[0] + timedelta(seconds=91), engine.state)
    assert result["fresh"]
    assert result["policies"][0]["matched_groups"] == []
    assert result["policies"][0]["possible_groups"] == ["child"]
    assert not reader.snapshot(now[0] - timedelta(seconds=1), engine.state)["fresh"]


async def test_newer_owned_write_is_pending_until_a_new_policy_observation(household):
    engine, gateway, now, _ = household
    gateway.policies = {"foreign": policy()}
    reader = CoexistenceReader(None, gateway)
    await reader.refresh(now[0])
    gateway.policies["foreign"]["enabled"] = False
    engine.state.owned["key"] = {
        "id": "foreign",
        "controller": engine.state.controller,
        "site": engine.state.site,
        "fingerprint": policy_fingerprint(gateway.policies["foreign"]),
        "readback_at": (now[0] + timedelta(seconds=1)).isoformat(),
    }
    assert reader.snapshot(now[0], engine.state)["policies"][0]["ownership"] == "pending"
    await reader.refresh(now[0] + timedelta(seconds=61))
    assert reader.snapshot(now[0], engine.state)["policies"][0]["ownership"] == "managed"


async def test_optional_policy_read_failure_keeps_actual_ha_sync_available(hass, entry):
    coordinator = entry.runtime_data
    coordinator.coexistence.last_attempt = None
    gateway = coordinator.engine.gateway
    gateway.list_policies = AsyncMock(side_effect=FamilyError("Optional context unavailable"))
    before = coordinator.engine.state.revision
    await coordinator.async_refresh()
    gateway.list_policies.assert_awaited_once()
    assert coordinator.last_update_success
    assert coordinator.engine.state.revision == before
    assert not coordinator.coexistence.snapshot(
        coordinator.engine.clock(), coordinator.engine.state
    )["fresh"]


async def test_ordering_adapter_uses_read_only_site_route():
    from custom_components.family_network.api.unifi import UniFiGateway

    gateway = UniFiGateway(None, "https://192.0.2.1", "test-only-key", site="site-id")
    gateway.request = AsyncMock(return_value={"orderedFirewallPolicyIds": {}})
    await gateway.policy_ordering("source-zone", "destination-zone")
    gateway.request.assert_awaited_once_with(
        "GET",
        gateway.site_path + "/firewall/policies/ordering",
        params={
            "sourceFirewallZoneId": "source-zone",
            "destinationFirewallZoneId": "destination-zone",
        },
    )


def test_ordering_rejects_missing_duplicate_foreign_and_cross_zone_ids():
    policies = {"foreign": policy()}
    pair = ("demo-home", "demo-internet")
    result = ordering_positions(
        {
            "orderedFirewallPolicyIds": {
                "beforeSystemDefined": ["foreign"],
                "afterSystemDefined": [],
            }
        },
        pair,
        policies,
    )
    assert result["foreign"] == {"section": "beforeSystemDefined", "position": 1}
    for ids in ([], ["foreign", "foreign"], ["unknown"]):
        with pytest.raises(FamilyError):
            ordering_positions(
                {
                    "orderedFirewallPolicyIds": {
                        "beforeSystemDefined": ids,
                        "afterSystemDefined": [],
                    }
                },
                pair,
                policies,
            )
    with pytest.raises(FamilyError):
        ordering_positions(
            {
                "orderedFirewallPolicyIds": {
                    "beforeSystemDefined": ["foreign"],
                    "afterSystemDefined": [],
                }
            },
            ("other", "demo-internet"),
            policies,
        )


async def test_order_pair_cap_is_explicit_and_no_unbounded_tasks_start(household):
    engine, gateway, now, _ = household
    gateway.policies = {
        str(i): policy(str(i), source={"zoneId": f"zone-{i}"}) for i in range(MAX_ORDER_PAIRS + 1)
    }
    original = gateway.policy_ordering
    gateway.policy_ordering = AsyncMock(side_effect=original)
    reader = CoexistenceReader(None, gateway)
    await reader.refresh(now[0])
    s = reader.snapshot(now[0], engine.state)
    assert gateway.policy_ordering.await_count == MAX_ORDER_PAIRS
    assert s["ordering"]["status"] == "capped" and s["policy_count"] == MAX_ORDER_PAIRS + 1


@pytest.mark.parametrize("field", ["id", "enabled", "source", "destination", "action"])
async def test_malformed_rows_make_collection_unavailable(household, field):
    engine, gateway, now, _ = household
    row = policy()
    del row[field]
    gateway.policies = {"foreign": row}
    reader = CoexistenceReader(None, gateway)
    await reader.refresh(now[0])
    assert reader.snapshot(now[0], engine.state)["status"] == "unavailable"


def test_display_keeps_explicit_schedule_and_conditions_without_raw_fields(household):
    _, gateway, _, _ = household
    row = policy(
        schedule={
            "mode": "EVERY_WEEK",
            "repeatOnDays": ["MONDAY"],
            "timeFilter": {"startTime": "20:00", "stopTime": "06:00"},
            "secret": "withheld",
        },
        connectionStateFilter=["NEW"],
    )
    result = normalize_policy(row, gateway)
    assert (
        "gateway timing not evaluated" in result["schedule"] and "20:00–06:00" in result["schedule"]
    )
    assert "Connection states: NEW" in result["conditions"] and "withheld" not in str(result)


async def test_control_inventory_is_scoped_and_reports_disabled_hidden_unavailable(
    hass, monkeypatch
):
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="unifi")
    entry.add_to_hass(hass)
    other = MockConfigEntry(domain="unifi")
    other.add_to_hass(hass)
    registry = er.async_get(hass)
    a = registry.async_get_or_create(
        "switch",
        "unifi",
        "firewall_policy-one",
        config_entry=entry,
        original_name="Firewall",
        hidden_by=er.RegistryEntryHider.USER,
    )
    registry.async_get_or_create(
        "switch",
        "unifi",
        "wlan-two",
        config_entry=entry,
        original_name="Wi-Fi",
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    registry.async_get_or_create(
        "switch", "unifi", "no-prefix", config_entry=entry, original_name="Legacy application group"
    )
    registry.async_get_or_create("switch", "unifi", "firewall_policy-other", config_entry=other)
    hass.states.async_set(a.entity_id, "unavailable")
    monkeypatch.setattr(
        "custom_components.family_network.coexistence.matching_unifi_entry", lambda *_: entry
    )
    reader = CoexistenceReader(hass, SimpleNamespace(simulation=False))
    from homeassistant.util import dt as dt_util

    reader.read_controls(dt_util.utcnow())
    items = reader.controls["items"]
    assert len(items) == 3
    one = next(r for r in items if r["name"] == "Firewall")
    assert one["registry_enabled"] and one["hidden"] and one["state"] == "unavailable"
    assert next(r for r in items if r["name"] == "Wi-Fi")["registry_enabled"] is False
