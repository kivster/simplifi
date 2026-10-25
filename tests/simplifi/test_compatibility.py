"""Unknown versions and schema drift through the real adapter and policy engine."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.simplifi.api.unifi import UniFiGateway
from custom_components.simplifi.models import (
    CapabilityError,
    GatewayAuthenticationError,
    Group,
    SimpliFiError,
    State,
)
from custom_components.simplifi.storage import HouseholdStorage

from .conftest import command


class ContractAPI:
    """Independent in-memory HTTP boundary; no gateway writes reach a network."""

    site_path = "/v1/sites/demo-site"

    def __init__(self):
        self.version = "99.1.234"
        self.faults = {}
        self.calls = []
        self.writes = []
        self.policies = {}
        self.counter = 0

    async def request(self, method, path, body=None, params=None):
        self.calls.append((method, path))
        if path in self.faults:
            fault = self.faults[path]
            if isinstance(fault, Exception):
                raise fault
            return deepcopy(fault)
        policy_path = self.site_path + "/firewall/policies"
        if method != "GET":
            self.writes.append((method, path, deepcopy(body)))
            if method == "POST" and path == policy_path:
                self.counter += 1
                key = f"policy-{self.counter}"
                self.policies[key] = {"id": key, **deepcopy(body)}
                return deepcopy(self.policies[key])
            key = path.rsplit("/", 1)[1]
            assert key in self.policies
            if method == "PUT":
                self.policies[key] = {"id": key, **deepcopy(body)}
                return deepcopy(self.policies[key])
            assert method == "DELETE"
            del self.policies[key]
            return None
        if path == "/v1/info":
            return {"applicationVersion": self.version, "newField": {"ignored": True}}
        if path.endswith("/networks/demo-family"):
            return {
                "id": "demo-family",
                "internetAccessEnabled": True,
                "ipv4Configuration": {"hostIpAddress": "192.0.2.1", "prefixLength": 24},
                "newDisplayField": "ignored",
            }
        if path.endswith("/references"):
            return {"referenceResources": []}
        rows = {
            "/v1/sites": [{"id": "demo-site", "name": "Home", "internalReference": "default"}],
            self.site_path + "/networks": [
                {"id": "demo-family", "name": "Family", "zoneId": "demo-home"}
            ],
            self.site_path + "/firewall/zones": [
                {"id": "demo-home", "name": "Internal"},
                {
                    "id": "demo-internet",
                    "name": "External",
                    "metadata": {"origin": "SYSTEM_DEFINED"},
                },
            ],
            "/v1/dpi/categories": [{"id": 0, "name": "Messaging"}],
            "/v1/dpi/applications": [{"id": 123, "name": "Example app"}],
            self.site_path + "/clients": [
                {
                    "id": "client",
                    "type": "WIRED",
                    "name": "Phone",
                    "macAddress": "02:00:00:00:00:01",
                    "ipAddress": "192.0.2.10",
                }
            ],
            self.site_path + "/devices": [],
            policy_path: list(self.policies.values()),
        }[path]
        return {
            "data": deepcopy(rows),
            "offset": 0,
            "count": len(rows),
            "totalCount": len(rows),
            "futureMetadata": True,
        }


@pytest.fixture
def contract(household):
    engine, _, now, saved = household
    api = ContractAPI()
    gateway = UniFiGateway(
        None, "https://example.local", "private-key", "demo-site", ["demo-family"], "demo-internet"
    )
    gateway.request = api.request
    engine.gateway = engine.reconciler.gateway = gateway
    engine.state.controller = gateway.controller
    return engine, gateway, api, now, saved


async def test_unknown_version_checked_each_refresh_and_real_policy_readback(contract):
    engine, gateway, api, _, _ = contract
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await command(engine, "pause_internet", group_id="child", duration_minutes=30)
    await engine.refresh()
    assert engine.state.sync_status == "applied" and engine.state.owned
    assert gateway.compatibility["status"] == "available"
    assert not gateway.compatibility["tested_version"]
    before = deepcopy(api.writes)
    api.version = "100.0.1"
    await engine.refresh()
    assert gateway.version == "100.0.1" and api.writes == before
    assert all(j["status"] == "verified" for j in engine.state.journal)


@pytest.mark.parametrize(
    "path",
    [
        "/v1/sites",
        "/v1/sites/demo-site/networks",
        "/v1/sites/demo-site/firewall/zones",
        "/v1/sites/demo-site/firewall/policies",
    ],
)
async def test_missing_required_endpoint_retains_policies_and_recovers(contract, path):
    engine, gateway, api, _, _ = contract
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await command(engine, "pause_internet", group_id="child", duration_minutes=30)
    await engine.refresh()
    policies, writes, owned = deepcopy(api.policies), len(api.writes), deepcopy(engine.state.owned)
    api.faults[path] = SimpliFiError("Gateway HTTP 404; response body withheld")
    with pytest.raises(SimpliFiError):
        await engine.refresh()
    assert api.policies == policies and len(api.writes) == writes and engine.state.owned == owned
    assert not engine.configuration_confirmed() and gateway.compatibility["status"] == "paused"
    del api.faults[path]
    await engine.refresh()
    assert engine.configuration_confirmed() and len(api.writes) == writes


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", []),
        ("enabled", "true"),
        ("source", []),
        ("destination", {}),
        ("action", "BLOCK"),
        ("ipProtocolScope", []),
        ("loggingEnabled", 1),
        ("schedule", "always"),
    ],
)
async def test_malformed_policy_cannot_trigger_any_write(contract, field, value):
    engine, gateway, api, _, _ = contract
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await command(engine, "pause_internet", group_id="child", duration_minutes=30)
    await engine.refresh()
    original = deepcopy(api.policies)
    next(iter(api.policies.values()))[field] = value
    writes = len(api.writes)
    await command(engine, "resume_internet", group_id="child")
    with pytest.raises(SimpliFiError):
        await engine.refresh()
    assert len(api.writes) == writes and engine.state.owned
    api.policies = original
    await engine.refresh()
    assert engine.configuration_confirmed() and not api.policies


@pytest.mark.parametrize(
    "kind,path", [("category", "/v1/dpi/categories"), ("application", "/v1/dpi/applications")]
)
async def test_missing_optional_catalogue_keeps_independent_internet_controls(contract, kind, path):
    engine, gateway, api, _, _ = contract
    api.faults[path] = SimpliFiError("Gateway HTTP 404")
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await command(engine, "pause_internet", group_id="child", duration_minutes=30)
    await engine.refresh()
    assert engine.configuration_confirmed() and api.policies
    assert gateway.compatibility["status"] == "limited"
    assert gateway.capabilities[kind] == "unavailable" and gateway.catalogues[kind] == set()
    del api.faults[path]
    await engine.refresh()
    assert gateway.compatibility["status"] == "available"


async def test_catalogue_loss_never_deletes_dependent_saved_rules(contract):
    engine, gateway, api, _, _ = contract
    await engine.refresh()
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await command(
        engine, "upsert_rule", name="Apps", kind="application", groups=["child"], targets=[123]
    )
    await engine.refresh()
    before, writes = deepcopy(api.policies), len(api.writes)
    api.faults["/v1/dpi/applications"] = SimpliFiError("Gateway HTTP 404")
    with pytest.raises(CapabilityError, match="preserve existing rules"):
        await engine.refresh()
    assert api.policies == before and len(api.writes) == writes
    del api.faults["/v1/dpi/applications"]
    await engine.refresh()
    assert engine.configuration_confirmed() and len(api.writes) == writes


@pytest.mark.parametrize(
    "path",
    [
        "/v1/info",
        "/v1/dpi/categories",
        "/v1/sites/demo-site/networks/demo-family/references",
        "/v1/sites/demo-site/devices",
    ],
)
async def test_auth_failures_are_not_hidden_by_optional_reads(contract, path):
    engine, gateway, api, _, _ = contract
    api.faults[path] = GatewayAuthenticationError("UniFi rejected the API key (HTTP 401)")
    with pytest.raises(GatewayAuthenticationError):
        await engine.refresh()
    assert gateway.compatibility["status"] == "authentication_required"
    assert not api.writes


async def setup_live_entry(hass, api, *, initial_failure=None):
    item = MockConfigEntry(
        domain="simplifi",
        data={
            "simulation": False,
            "controller": "https://example.local",
            "api_key": "private-key",
            "site": "demo-site",
            "networks": ["demo-family"],
            "external_zone": "demo-internet",
            "timezone": "Europe/London",
        },
    )
    item.add_to_hass(hass)
    storage = HouseholdStorage(hass, item.entry_id)
    state = State("https://example.local", "demo-site", ["demo-family"])
    state.groups["child"] = Group("child", "Child")
    await storage.save(state)
    if initial_failure:
        api.faults["/v1/sites"] = initial_failure

    async def read(_gateway, *args, **kwargs):
        return await api.request(*args, **kwargs)

    with patch("custom_components.simplifi.api.unifi.UniFiGateway.request", new=read):
        await hass.config_entries.async_setup(item.entry_id)
        await hass.async_block_till_done()
    return item, read


async def test_native_loaded_offline_dashboard_and_poll_recovery(hass, hass_admin_user):
    api = ContractAPI()
    item, read = await setup_live_entry(
        hass, api, initial_failure=SimpliFiError("Controller unavailable")
    )
    assert item.state is ConfigEntryState.LOADED
    assert item.runtime_data.engine.state.groups["child"].name == "Child"
    result = await hass.services.async_call(
        "simplifi",
        "dashboard_data",
        {"entry_id": item.entry_id},
        blocking=True,
        return_response=True,
        context=Context(user_id=hass_admin_user.id),
    )
    assert (
        result["groups"] and not result["fresh"] and result["compatibility"]["status"] == "paused"
    )
    assert hass.states.get("sensor.simplifi_sync_status").state == "failed"
    api.faults.clear()
    with patch("custom_components.simplifi.api.unifi.UniFiGateway.request", new=read):
        from datetime import timedelta

        from homeassistant.util import dt as dt_util
        from pytest_homeassistant_custom_component.common import async_fire_time_changed_exact

        async_fire_time_changed_exact(hass, dt_util.utcnow() + timedelta(seconds=31))
        await hass.async_block_till_done(wait_background_tasks=True)
    assert item.runtime_data.last_update_success
    assert hass.states.get("sensor.simplifi_gateway_compatibility").state == "available"
    assert hass.states.get("binary_sensor.simplifi_connected").state == "on"
    assert not api.writes


async def test_native_authentication_failure_starts_reauth(hass):
    api = ContractAPI()
    item, _ = await setup_live_entry(
        hass,
        api,
        initial_failure=GatewayAuthenticationError("UniFi rejected the API key (HTTP 401)"),
    )
    assert item.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_optional_version_info_outage_does_not_block_working_api(contract):
    engine, gateway, api, _, _ = contract
    api.faults["/v1/info"] = SimpliFiError("Gateway HTTP 404")
    await engine.refresh()
    assert engine.state.inventory_complete and gateway.version == "unknown"
    assert gateway.compatibility["features"]["application_info"] == "unavailable"
    assert not api.writes


@pytest.mark.parametrize(
    "fault",
    [
        "site_id",
        "network_zone",
        "network_subnet",
        "client_type",
        "client_ip",
        "catalogue_name",
        "dhcp",
    ],
)
async def test_changed_response_shapes_fail_closed_or_isolate_optional_feature(contract, fault):
    engine, gateway, api, _, _ = contract
    path = {
        "site_id": "/v1/sites",
        "network_zone": api.site_path + "/networks",
        "network_subnet": api.site_path + "/networks/demo-family",
        "client_type": api.site_path + "/clients",
        "client_ip": api.site_path + "/clients",
        "catalogue_name": "/v1/dpi/applications",
        "dhcp": api.site_path + "/networks/demo-family",
    }[fault]
    response = await api.request("GET", path)
    if fault == "site_id":
        response["data"][0]["id"] = 123
    elif fault == "network_zone":
        response["data"][0]["zoneId"] = []
    elif fault == "network_subnet":
        response["ipv4Configuration"] = "changed"
    elif fault == "client_type":
        response["data"][0]["type"] = "NEW_LAN_TYPE"
    elif fault == "client_ip":
        response["data"][0]["ipAddress"] = 123
    elif fault == "catalogue_name":
        response["data"][0]["name"] = {}
    elif fault == "dhcp":
        response["ipv4Configuration"]["dhcpConfiguration"] = "changed"
    api.faults[path] = response
    if fault in ("catalogue_name", "dhcp"):
        await engine.refresh()
        assert engine.state.inventory_complete
        if fault == "catalogue_name":
            assert gateway.capabilities["application"] == "unavailable"
        else:
            assert gateway.networks["demo-family"]["dns"]["source"] == "unavailable"
    else:
        with pytest.raises(CapabilityError):
            await engine.refresh()
        assert not engine.state.inventory_complete
    assert not api.writes


async def test_unavailable_catalogue_rejects_direct_editor_action_without_saving(contract):
    engine, _, api, _, saved = contract
    api.faults["/v1/dpi/applications"] = SimpliFiError("Gateway HTTP 404")
    await engine.refresh()
    before, saves = engine.state.to_dict(), len(saved)
    with pytest.raises(CapabilityError, match="catalogue is unavailable"):
        await command(
            engine, "upsert_rule", name="Apps", kind="application", groups=["child"], targets=[123]
        )
    assert engine.state.to_dict() == before and len(saved) == saves and not api.writes
