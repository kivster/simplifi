"""Exercise HA Store's real write/error boundary, not an Engine.save stub."""

from copy import deepcopy

import pytest
from homeassistant.core import CoreState
from homeassistant.helpers.storage import Store
from homeassistant.util.file import WriteError
from homeassistant.util.json import SerializationError

from custom_components.family_network.models import FamilyError, Rule


@pytest.mark.parametrize("error", [WriteError, SerializationError])
async def test_ha_store_write_failure_cannot_acknowledge_household_change(
    entry, monkeypatch, error
):
    engine = entry.runtime_data.engine
    key = entry.runtime_data.storage.store.key
    original = Store._async_write_data

    async def disk_full(store, data):
        if store.key == key:
            raise error("private disk path")
        await original(store, data)

    before = deepcopy(engine.state.to_dict())
    with monkeypatch.context() as patch:
        patch.setattr(Store, "_async_write_data", disk_full)
        with pytest.raises(FamilyError, match="persist"):
            await engine.command(
                "upsert_group",
                {"group_id": "demo-family", "name": "Not saved"},
                "admin-id",
                administrator=True,
            )
    assert engine.state.to_dict() == before


async def test_failed_ha_store_journal_write_prevents_gateway_effect(entry, monkeypatch):
    engine = entry.runtime_data.engine
    engine.state.management = True
    engine.state.rules["r"] = Rule("r", "Whole network", "internet", [], networks=["demo-family"])
    key = entry.runtime_data.storage.store.key
    original = Store._async_write_data

    async def journal_failure(store, data):
        if store.key == key and any(
            j["status"] == "intent" for j in data["data"].get("journal", [])
        ):
            raise WriteError("private disk path")
        await original(store, data)

    with monkeypatch.context() as patch:
        patch.setattr(Store, "_async_write_data", journal_failure)
        with pytest.raises(FamilyError, match="persist"):
            await engine.refresh()
    assert engine.gateway.counter == 0 and not engine.gateway.policies


async def test_shutdown_save_is_written_before_returning(hass, entry, hass_storage):
    engine = entry.runtime_data.engine
    key = entry.runtime_data.storage.store.key
    before = hass.state
    try:
        hass.set_state(CoreState.stopping)
        await engine.command(
            "upsert_group",
            {"group_id": "demo-family", "name": "Shutdown receipt"},
            "admin-id",
            administrator=True,
        )
        assert hass_storage[key]["data"]["groups"]["demo-family"]["name"] == "Shutdown receipt"
        assert entry.runtime_data.storage.store._data is None
    finally:
        hass.set_state(before)


async def test_lost_write_receipt_reloads_durable_intent_without_duplicate_create(
    hass, entry, hass_storage, monkeypatch
):
    engine = entry.runtime_data.engine
    gateway = engine.gateway
    engine.state.management = True
    engine.state.rules["r"] = Rule("r", "Rule", "internet", [], networks=["demo-family"])
    key = entry.runtime_data.storage.store.key
    original = Store._async_write_data

    async def lost_receipt(store, data):
        if store.key == key and any("returned_id" in j for j in data["data"].get("journal", [])):
            raise WriteError("disk full after gateway response")
        await original(store, data)

    with monkeypatch.context() as patch:
        patch.setattr(Store, "_async_write_data", lost_receipt)
        with pytest.raises(FamilyError, match="persist"):
            await engine.refresh()
    saved_operation = hass_storage[key]["data"]["journal"][-1]
    assert saved_operation["status"] == "intent" and "returned_id" not in saved_operation
    assert gateway.counter == len(gateway.policies) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    monkeypatch.setattr("custom_components.family_network.FakeGateway", lambda: gateway)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert not entry.runtime_data.last_update_success
    assert gateway.counter == 1
    assert entry.runtime_data.engine.state.journal[-1]["status"] == "intent"
