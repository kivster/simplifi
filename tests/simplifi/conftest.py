"""Isolated HA harness and pure-engine fixtures. Network sockets are test-disabled."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.simplifi.api.simulator import FakeGateway
from custom_components.simplifi.engine import Engine
from custom_components.simplifi.models import Group, State


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def household():
    gateway = FakeGateway()
    state = State(
        "simulator",
        "demo-site",
        ["demo-family"],
        inventory_complete=True,
        gateway_timezone_confirmed=True,
    )
    state.groups["child"] = Group("child", "Test family")
    state.devices = {d.id: deepcopy(d) for d in gateway.clients}
    for device in state.devices.values():
        device.group = "child"
    now = [datetime(2026, 10, 13, 20, 30, tzinfo=UTC)]
    state.last_observed = now[0].isoformat()
    saved = []

    async def save(value):
        saved.append(deepcopy(value.to_dict()))

    engine = Engine(state, gateway, save, clock=lambda: now[0])
    return engine, gateway, now, saved


async def command(engine, action, **payload):
    return await engine.command(action, payload, "admin-id", administrator=True)


@pytest.fixture
async def entry(hass):
    entry = MockConfigEntry(
        domain="simplifi",
        title="SimpliFi simulator",
        data={
            "simulation": True,
            "controller": "simulator",
            "site": "demo-site",
            "networks": ["demo-family"],
            "timezone": "Europe/London",
        },
        unique_id="simplifi_simulator",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
