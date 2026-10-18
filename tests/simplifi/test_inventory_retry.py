"""Complete fresh reads may resolve skew; persistent contradictions never permit writes."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.simplifi.api.unifi import UniFiGateway
from custom_components.simplifi.diagnostics import async_get_config_entry_diagnostics
from custom_components.simplifi.inventory import InventoryScopeError
from custom_components.simplifi.models import Rule, SimpliFiError

MAC = "00:11:22:33:44:55"
NETWORKS = {
    "family": {"subnets": ["192.0.2.0/24"]},
    "outside": {"subnets": ["198.51.100.0/24"]},
}


def client(address="192.0.2.10", mac=MAC):
    return {"id": "client-" + mac, "type": "WIRED", "macAddress": mac, "ipAddress": address}


@pytest.fixture
def gateway():
    source = UniFiGateway(None, "https://example.local", "test", site="s", networks=["family"])
    source.refresh_resources = AsyncMock()
    source.networks = deepcopy(NETWORKS)
    source.request = AsyncMock(return_value={"referenceResources": []})
    source.current_network_reader = SimpleNamespace(read=AsyncMock())
    with (
        patch("custom_components.simplifi.api.unifi.registrant_database", return_value={}),
        patch("custom_components.simplifi.api.unifi.asyncio.sleep", new_callable=AsyncMock),
    ):
        yield source


async def test_retry_uses_only_second_complete_snapshot_and_refreshes_resources(gateway):
    # The IP initially lags behind the current connection. Neither side wins;
    # a subsequent complete read independently confirms the roam outside scope.
    gateway.pages = AsyncMock(side_effect=[[client()], [], [client("198.51.100.10")], []])
    gateway.current_network_reader.read.return_value = {MAC: {"network": "outside"}}
    devices = await gateway.discover()
    assert len(devices) == 1 and devices[0].network == "outside"
    assert devices[0].ip == "198.51.100.10"
    assert gateway.refresh_resources.await_count == 2
    assert gateway.current_network_reader.read.await_count == 2
    assert gateway.discovery_readback["status"] == "complete"
    assert gateway.discovery_readback["attempts"] == 2
    assert gateway.discovery_readback["scope_issues"] == ["network_subnet_disagreement"]
    assert gateway.discovery_readback["lan_clients"] == 1
    assert MAC not in str(gateway.discovery_readback)
    assert "198.51.100" not in str(gateway.discovery_readback)
    # Later ordinary discovery resets attempt evidence and never reuses rows.
    gateway.pages.side_effect = [[client()], []]
    gateway.current_network_reader.read.return_value = {MAC: {"network": "family"}}
    assert (await gateway.discover())[0].network == "family"
    assert gateway.discovery_readback["attempts"] == 1
    assert gateway.discovery_readback["scope_issues"] == []


async def test_unmapped_observation_can_only_recover_through_new_scope_evidence(gateway):
    gateway.pages = AsyncMock(side_effect=[[client("203.0.113.5")], [], [client()], []])
    gateway.current_network_reader.read.return_value = {}
    assert (await gateway.discover())[0].network == "family"
    assert gateway.discovery_readback["scope_issues"] == ["unmapped_network"]


async def test_retry_rereads_current_identity_instead_of_reusing_it(gateway):
    gateway.pages = AsyncMock(side_effect=[[client()], [], [client()], []])
    gateway.current_network_reader.read.side_effect = [
        {MAC: {"network": "outside"}},
        {MAC: {"network": "family"}},
    ]
    assert (await gateway.discover())[0].network == "family"


@pytest.mark.parametrize("second_current", [{MAC: {"network": "outside"}}, {}])
async def test_persistent_conflict_or_lost_corroboration_never_accepts_ip_fallback(
    gateway, second_current
):
    gateway.pages = AsyncMock(side_effect=[[client()], [], [client()], []])
    gateway.current_network_reader.read.side_effect = [
        {MAC: {"network": "outside"}},
        second_current,
    ]
    with pytest.raises(InventoryScopeError):
        await gateway.discover()
    assert gateway.refresh_resources.await_count == 2
    assert gateway.discovery_readback["status"] == "incomplete"
    assert gateway.discovery_readback["observed_at"] is None
    assert gateway.discovery_readback["lan_clients"] is None
    assert gateway.discovery_readback["attempts"] == 2


@pytest.mark.parametrize("failure", ["truncated", "duplicate", "resources"])
async def test_malformed_or_failed_reads_do_not_enter_scope_retry(gateway, failure):
    gateway.current_network_reader.read.return_value = {}
    if failure == "resources":
        gateway.refresh_resources.side_effect = SimpliFiError("Gateway HTTP 403")
    gateway.pages = AsyncMock(
        side_effect=SimpliFiError("Inventory cap/truncation")
        if failure == "truncated"
        else [[client(), client()], []]
    )
    with pytest.raises(SimpliFiError):
        await gateway.discover()
    assert gateway.discovery_readback["attempts"] == 1
    assert gateway.discovery_readback["status"] == "incomplete"


async def test_current_client_reads_precede_optional_display_and_reference_reads(gateway):
    calls = []

    async def pages(path, **kwargs):
        calls.append(path.rsplit("/", 1)[-1])
        return [client()] if path.endswith("/clients") else []

    async def current():
        calls.append("current")
        return {MAC: {"network": "family"}}

    async def request(*args):
        calls.append("references")
        return {"referenceResources": []}

    gateway.pages = pages
    gateway.current_network_reader.read = current
    gateway.request = request
    await gateway.discover()
    assert calls == ["clients", "current", "references", "references", "devices"]


async def test_retry_has_an_overall_time_budget(gateway, monkeypatch):
    monkeypatch.setattr("custom_components.simplifi.api.unifi.DISCOVERY_RETRY_TIMEOUT", 0.01)
    attempts = 0

    async def resources():
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            await asyncio.Event().wait()

    gateway.refresh_resources.side_effect = resources
    gateway.pages = AsyncMock(side_effect=[[client()], []])
    gateway.current_network_reader.read.return_value = {MAC: {"network": "outside"}}
    with pytest.raises(TimeoutError):
        await gateway.discover()
    assert attempts == 2 and gateway.discovery_readback["status"] == "incomplete"


async def test_failed_partial_inventories_preserve_devices_journal_and_policies(household, gateway):
    engine, fake, _, _ = household
    engine.state.management = True
    engine.state.rules["r"] = Rule("r", "Video", "category", ["child"], [4])
    await engine.refresh()
    before = deepcopy(engine.state.to_dict())
    policies = deepcopy(fake.policies)
    # A valid first client must not be ingested before a later conflict. The
    # conflict is deliberately on a new unassigned client, still part of scope.
    rows = [client(mac="00:11:22:33:44:66"), client()]
    gateway.pages = AsyncMock(side_effect=[rows, [], rows, []])
    gateway.current_network_reader.read.return_value = {MAC: {"network": "outside"}}
    fake.discover = gateway.discover
    with pytest.raises(InventoryScopeError):
        await engine.refresh()
    after = engine.state.to_dict()
    for key in ["devices", "groups", "rules", "owned", "journal", "revision"]:
        assert after[key] == before[key]
    assert fake.policies == policies
    assert not engine.state.inventory_complete


async def test_persistent_scope_conflict_has_specific_repair_and_success_clears_it(hass, entry):
    coordinator = entry.runtime_data
    gateway = coordinator.engine.gateway
    original = gateway.discover
    gateway.discover = AsyncMock(side_effect=InventoryScopeError("network_subnet_disagreement"))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    registry = ir.async_get(hass)
    issue = registry.async_get_issue("simplifi", coordinator.issue_id)
    assert issue.translation_key == "inventory_scope_failed"
    gateway.discovery_readback = {
        "status": "incomplete",
        "attempts": 2,
        "scope_issues": ["network_subnet_disagreement"],
    }
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["discovery_readback"] == gateway.discovery_readback
    gateway.discover = original
    await coordinator._async_update_data()
    assert registry.async_get_issue("simplifi", coordinator.issue_id) is None
