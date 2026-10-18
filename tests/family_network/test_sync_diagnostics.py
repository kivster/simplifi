"""Actionable sync failures survive recovery without leaking transport contents."""

from copy import deepcopy

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.family_network.diagnostics import async_get_config_entry_diagnostics
from custom_components.family_network.models import FamilyError
from custom_components.family_network.presentation import dashboard_data


async def test_failure_reason_is_retained_in_history_after_success(hass, entry):
    coordinator = entry.runtime_data
    engine = coordinator.engine
    engine.gateway.failure = "inventory"
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    expected = "Sync unconfirmed during device discovery: Simulated incomplete inventory"
    assert engine.state.issue == expected
    assert (await dashboard_data(hass, entry))["issue"] == expected
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["issue"] == expected
    await coordinator._async_update_data()
    assert engine.state.issue is None
    history = (await coordinator.storage.history.read())["items"]
    assert history[0]["issue"] is None
    assert history[1]["issue"] == expected
    assert history[1]["outcome"] == "failed"


async def test_timeout_details_are_never_published(household, monkeypatch):
    engine, gateway, _, _ = household

    async def timeout():
        raise TimeoutError("https://private-controller/ secret-key=DO_NOT_EXPOSE")

    monkeypatch.setattr(gateway, "discover", timeout)
    with pytest.raises(TimeoutError):
        await engine.refresh()
    assert engine.state.issue == "Sync unconfirmed during device discovery: The operation timed out"
    assert "DO_NOT_EXPOSE" not in str(engine.state.to_dict())


async def test_planning_failure_explains_missing_zone_without_gateway_writes(household):
    engine, gateway, _, _ = household
    engine.state.management = True
    gateway.external_zone = ""
    with pytest.raises(FamilyError):
        await engine.refresh()
    assert engine.state.issue == (
        "Sync unconfirmed during planning restrictions: Select and verify the internet destination zone"
    )
    assert not gateway.policies and not engine.state.journal


async def test_failed_policy_read_preserves_existing_policy_and_names_stage(household):
    engine, gateway, _, _ = household
    engine.state.management = True
    gateway.policies["foreign"] = {"id": "foreign", "name": "Existing household policy"}
    before = deepcopy(gateway.policies)
    gateway.failure = "list"
    with pytest.raises(FamilyError):
        await engine.refresh()
    assert engine.state.issue == (
        "Sync unconfirmed during policy reconciliation: Simulated policy read failure"
    )
    assert gateway.policies == before


@pytest.mark.parametrize("failed_save", [1, 2])
async def test_save_failure_names_observation_or_result_stage(household, failed_save):
    engine, _, _, saved = household
    original = engine.save
    calls = 0

    async def fail_once(value):
        nonlocal calls
        calls += 1
        if calls == failed_save:
            raise FamilyError("Unable to persist SimpliFi state; the operation cannot continue")
        await original(value)

    engine.save = fail_once
    with pytest.raises(FamilyError):
        await engine.refresh()
    stage = "saving device observations" if failed_save == 1 else "saving sync results"
    assert saved[-1]["issue"].startswith(f"Sync unconfirmed during {stage}: Unable to persist")
    assert saved[-1]["sync_status"] == "failed"
