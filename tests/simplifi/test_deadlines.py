"""Timed policy intent must not outrun confirmation or wait for the polling interval."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import Context
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed_exact

from custom_components.simplifi.binary_sensor import SimpliFiBinarySensor
from custom_components.simplifi.presentation import dashboard_data
from custom_components.simplifi.sensor import SimpliFiSensor

from .conftest import command


async def managed(entry):
    coordinator = entry.runtime_data
    engine = coordinator.engine
    now = [dt_util.utcnow()]
    engine.clock = lambda: now[0]
    for device in list(engine.state.devices):
        await command(engine, "assign_device", device_id=device, group_id="demo-family")
    await command(engine, "set_management", enabled=True, expiry_acknowledged=True)
    await command(
        engine,
        "set_access_grant",
        user_id="delegate",
        scope="read_only",
        groups=["demo-family"],
        confirm=True,
    )
    return coordinator, engine, now


async def test_expired_pause_is_not_confirmed_until_policy_readback(hass, entry):
    coordinator, engine, now = await managed(entry)
    deadline = now[0] + timedelta(seconds=5)
    await command(engine, "pause_internet", group_id="demo-family", expires_at=deadline.isoformat())
    await coordinator.async_refresh()
    assert (await dashboard_data(hass, entry))["confirmed"]
    assert len(engine.gateway.policies) == 2
    now[0] = deadline
    # Time advanced, but no callback or gateway read has happened yet.
    view = await dashboard_data(hass, entry)
    assert not view["confirmed"]
    assert view["groups"][0]["state"] == "unknown"
    assert view["groups"][0]["control_state"] == "available"
    scoped = await engine.command("access_status", {}, "delegate")
    assert not scoped["groups"][0]["confirmed"]
    sensor = SimpliFiSensor(coordinator, entry, "group:demo-family:internet", "Internet")
    assert sensor.native_value == "unknown"
    await coordinator.async_refresh()
    assert not engine.gateway.policies
    assert (await dashboard_data(hass, entry))["confirmed"]
    assert sensor.native_value == "available"


async def test_expiry_triggers_real_ha_timer_before_regular_poll(hass, entry):
    coordinator, engine, now = await managed(entry)
    deadline = now[0] + timedelta(seconds=5)
    await command(engine, "pause_internet", group_id="demo-family", expires_at=deadline.isoformat())
    await coordinator.async_refresh()
    assert len(engine.gateway.policies) == 2
    now[0] = deadline
    assert coordinator._deadline_at == deadline
    # Avoid platform floating-point differences between wall and monotonic time.
    # The separate boundary test above still checks intent at the exact deadline.
    async_fire_time_changed_exact(hass, deadline + timedelta(milliseconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not engine.gateway.policies
    assert (await dashboard_data(hass, entry))["confirmed"]


@pytest.mark.parametrize(
    "action", ["allow_internet", "allow_rule", "suspend_rule", "suspend_quarantine"]
)
async def test_expiry_reenables_restrictions_after_readback(hass, entry, action):
    coordinator, engine, now = await managed(entry)
    deadline = now[0] + timedelta(seconds=5)
    if action == "suspend_quarantine":
        for device in list(engine.state.devices):
            await command(engine, "assign_device", device_id=device)
        await command(engine, "set_quarantine", enabled=True, excluded_devices=[], confirm=True)
        target = {}
    else:
        await command(
            engine,
            "upsert_rule",
            rule_id="r",
            name="Restriction",
            kind="internet",
            groups=["demo-family"],
        )
        target = {"group_id": "demo-family"} if action == "allow_internet" else {"rule_id": "r"}
    await coordinator.async_refresh()
    assert all(p["enabled"] for p in engine.gateway.policies.values())
    await command(engine, action, **target, expires_at=deadline.isoformat())
    await coordinator.async_refresh()
    assert engine.gateway.policies and all(
        not p["enabled"] for p in engine.gateway.policies.values()
    )
    dependency = SimpliFiBinarySensor(coordinator, entry, "expiry_dependency", "Expiry")
    assert dependency.is_on and engine.configuration_confirmed()
    now[0] = deadline
    assert not engine.configuration_confirmed()
    assert not dependency.is_on
    async_fire_time_changed_exact(hass, deadline + timedelta(milliseconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert all(p["enabled"] for p in engine.gateway.policies.values())
    assert engine.configuration_confirmed()


async def test_service_replaces_deadline_and_cancels_on_resume(
    hass, entry, hass_admin_user, monkeypatch
):
    coordinator, engine, now = await managed(entry)
    # Accepted actions must rearm even while the normal refresh is debounced.
    monkeypatch.setattr(coordinator, "async_request_refresh", AsyncMock())

    async def act(action, **payload):
        return await hass.services.async_call(
            "simplifi",
            action,
            {"entry_id": entry.entry_id, **payload},
            context=Context(user_id=hass_admin_user.id),
            blocking=True,
            return_response=True,
        )

    deadline = now[0] + timedelta(seconds=5)
    await act("pause_internet", group_id="demo-family", expires_at=deadline.isoformat())
    await coordinator.async_refresh()
    await act("extend_pause", group_id="demo-family", duration_minutes=1)
    assert coordinator._deadline_at == deadline + timedelta(minutes=1)
    now[0] = deadline
    async_fire_time_changed_exact(hass, deadline + timedelta(milliseconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert engine.gateway.policies  # The cancelled timer cannot remove the extended pause.
    await act("resume_internet", group_id="demo-family")
    assert coordinator._deadline_at is None and coordinator._deadline_cancel is None
    await coordinator.async_refresh()
    assert not engine.gateway.policies and engine.configuration_confirmed()


async def test_failed_deadline_refresh_waits_for_normal_retry(hass, entry):
    coordinator, engine, now = await managed(entry)
    deadline = now[0] + timedelta(seconds=5)
    await command(engine, "pause_internet", group_id="demo-family", expires_at=deadline.isoformat())
    await coordinator.async_refresh()
    count = len(coordinator.storage.history.data["runs"])
    engine.gateway.failure = "inventory"
    now[0] = deadline
    async_fire_time_changed_exact(hass, deadline + timedelta(milliseconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(coordinator.storage.history.data["runs"]) == count + 1
    assert engine.gateway.policies and not engine.configuration_confirmed()
    assert coordinator._deadline_at is None
    await coordinator.async_refresh()
    assert not engine.gateway.policies and engine.configuration_confirmed()


async def test_slow_refresh_crossing_deadline_catches_up(hass, entry, monkeypatch):
    coordinator, engine, now = await managed(entry)
    deadline = now[0] + timedelta(seconds=5)
    await command(engine, "pause_internet", group_id="demo-family", expires_at=deadline.isoformat())
    discover = engine.gateway.discover

    async def cross_deadline():
        now[0] = deadline
        return await discover()

    monkeypatch.setattr(engine.gateway, "discover", cross_deadline)
    # This refresh captured its plan time before discovery crossed the deadline.
    await coordinator.async_refresh()
    assert engine.gateway.policies and not engine.configuration_confirmed()
    assert coordinator._deadline_at == deadline
    async_fire_time_changed_exact(hass, deadline + timedelta(milliseconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not engine.gateway.policies and engine.configuration_confirmed()


async def test_deadline_waits_for_inflight_refresh_then_catches_up(hass, entry, monkeypatch):
    coordinator, engine, now = await managed(entry)
    deadline = now[0] + timedelta(seconds=5)
    await command(engine, "pause_internet", group_id="demo-family", expires_at=deadline.isoformat())
    await coordinator.async_refresh()
    started, release = asyncio.Event(), asyncio.Event()
    discover = engine.gateway.discover
    calls, inflight = 0, 0

    async def delayed_discover():
        nonlocal calls, inflight
        calls += 1
        inflight += 1
        assert inflight == 1
        try:
            if calls == 1:
                started.set()
                await release.wait()
            return await discover()
        finally:
            inflight -= 1

    monkeypatch.setattr(engine.gateway, "discover", delayed_discover)
    pending = asyncio.create_task(coordinator.async_refresh())
    try:
        async with asyncio.timeout(2):
            await started.wait()
        now[0] = deadline
        async_fire_time_changed_exact(hass, deadline + timedelta(milliseconds=1))
        await asyncio.sleep(0)
        assert calls == 1
    finally:
        release.set()
        await pending
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls == 2
    assert not engine.gateway.policies and engine.configuration_confirmed()


async def test_reload_rearms_deadline_and_unload_cancels_it(hass, entry, monkeypatch):
    coordinator, engine, now = await managed(entry)
    deadline = now[0] + timedelta(seconds=5)
    await command(engine, "pause_internet", group_id="demo-family", expires_at=deadline.isoformat())
    await coordinator.async_refresh()
    gateway = engine.gateway
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert coordinator._deadline_at is None and coordinator._deadline_cancel is None
    monkeypatch.setattr("custom_components.simplifi.FakeGateway", lambda: gateway)
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = entry.runtime_data
    assert coordinator._deadline_at == deadline
    coordinator.engine.clock = lambda: deadline
    async_fire_time_changed_exact(hass, deadline + timedelta(milliseconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not gateway.policies and coordinator.engine.configuration_confirmed()


async def test_unload_drains_deadline_write_receipt(hass, entry, monkeypatch):
    coordinator, engine, now = await managed(entry)
    deadline = now[0] + timedelta(seconds=5)
    await command(engine, "pause_internet", group_id="demo-family", expires_at=deadline.isoformat())
    await coordinator.async_refresh()
    started, release = asyncio.Event(), asyncio.Event()
    delete = engine.gateway.delete

    async def delayed_delete(policy_id):
        started.set()
        await release.wait()
        await delete(policy_id)

    monkeypatch.setattr(engine.gateway, "delete", delayed_delete)
    now[0] = deadline
    async_fire_time_changed_exact(hass, deadline + timedelta(milliseconds=1))
    async with asyncio.timeout(2):
        await started.wait()
    unloading = asyncio.create_task(hass.config_entries.async_unload(entry.entry_id))
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(unloading), 0.1)
    finally:
        release.set()
        assert await unloading
    assert len(engine.gateway.policies) == 1  # Stop before the next gateway write.
    assert all(row["status"] == "verified" for row in engine.state.journal)
    assert coordinator._deadline_at is None and not coordinator._active_operations


async def test_disabled_management_cancels_deadline_without_deleting_policies(hass, entry):
    coordinator, engine, now = await managed(entry)
    deadline = now[0] + timedelta(seconds=5)
    await command(engine, "pause_internet", group_id="demo-family", expires_at=deadline.isoformat())
    await coordinator.async_refresh()
    await command(engine, "set_management", enabled=False)
    await coordinator.async_refresh()
    assert coordinator._deadline_at is None
    now[0] = deadline
    async_fire_time_changed_exact(hass, deadline + timedelta(milliseconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(engine.gateway.policies) == 2
    assert not engine.configuration_confirmed()
