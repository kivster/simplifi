"""Reload must not leave an old authenticated writer behind a new household."""

import asyncio

import pytest
from homeassistant.core import Context

from custom_components.family_network.models import FamilyError, Rule


async def test_unload_drains_an_authenticated_action_before_reloading(
    hass, entry, hass_admin_user, monkeypatch
):
    coordinator = entry.runtime_data
    engine = coordinator.engine
    saving = asyncio.Event()
    release = asyncio.Event()
    original_save = engine.save

    async def delayed_save(state):
        saving.set()
        await release.wait()
        await original_save(state)

    monkeypatch.setattr(engine, "save", delayed_save)
    service = asyncio.create_task(
        hass.services.async_call(
            "family_network",
            "upsert_group",
            {"entry_id": entry.entry_id, "group_id": "demo-family", "name": "Saved before reload"},
            context=Context(user_id=hass_admin_user.id),
            blocking=True,
            return_response=True,
        )
    )
    async with asyncio.timeout(2):
        await saving.wait()
    unloading = asyncio.create_task(hass.config_entries.async_unload(entry.entry_id))
    try:
        # Even an untracked REST/service task must finish its durable mutation
        # before unload returns and another Engine can load the same store.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(unloading), 0.1)
    finally:
        release.set()
        outcomes = await asyncio.gather(service, unloading, return_exceptions=True)
    assert not isinstance(outcomes[0], BaseException), outcomes[0]
    assert outcomes[1] is True
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data is not coordinator
    assert entry.runtime_data.engine.state.groups["demo-family"].name == "Saved before reload"


async def test_reload_finishes_one_inflight_gateway_write_and_stops_the_next(
    hass, entry, monkeypatch
):
    coordinator = entry.runtime_data
    engine, gateway = coordinator.engine, coordinator.engine.gateway
    for name in ("first", "second"):
        engine.state.rules[name] = Rule(name, name, "internet", [], networks=["demo-family"])
    engine.state.management = True
    started, release = asyncio.Event(), asyncio.Event()
    create = gateway.create

    async def delayed_create(body):
        started.set()
        await release.wait()
        return await create(body)

    monkeypatch.setattr(gateway, "create", delayed_create)
    refresh = asyncio.create_task(coordinator.async_refresh())
    async with asyncio.timeout(2):
        await started.wait()
    unloading = asyncio.create_task(hass.config_entries.async_unload(entry.entry_id))
    queued = None
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(unloading), 0.1)
        assert coordinator.closing and not coordinator.start_dns()
        queued = asyncio.create_task(
            engine.command(
                "upsert_group",
                {"group_id": "demo-family", "name": "Old queued writer"},
                "admin-id",
                administrator=True,
            )
        )
    finally:
        release.set()
        await asyncio.gather(refresh, unloading)
    if queued:
        with pytest.raises(FamilyError, match="stopping"):
            await queued
    assert gateway.counter == len(gateway.policies) == 1
    assert all(j["status"] == "verified" for j in engine.state.journal)
    assert coordinator.storage.history.data["runs"][-1]["outcome"] == "interrupted"
    monkeypatch.setattr("custom_components.family_network.FakeGateway", lambda: gateway)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert gateway.counter == len(gateway.policies) == 2
    assert entry.runtime_data.engine.state.groups["demo-family"].name != "Old queued writer"
    assert entry.runtime_data.engine.state.sync_status == "applied"


async def test_unload_drains_dns_without_late_result_persistence(hass, entry, monkeypatch):
    coordinator = entry.runtime_data
    started, release = asyncio.Event(), asyncio.Event()
    from custom_components.family_network.dns_checks import simulated_probe

    async def delayed_probe(*args, **kwargs):
        started.set()
        await release.wait()
        return await simulated_probe(*args, **kwargs)

    monkeypatch.setattr(
        "custom_components.family_network.coordinator.simulated_probe", delayed_probe
    )
    assert coordinator.start_dns()
    async with asyncio.timeout(2):
        await started.wait()
    unloading = asyncio.create_task(hass.config_entries.async_unload(entry.entry_id))
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(unloading), 0.1)
        assert not coordinator.start_dns()
    finally:
        release.set()
        assert await unloading
    assert not coordinator.probe_task.cancelled()
    assert not coordinator.engine.state.probe_results
    assert not coordinator._active_operations
