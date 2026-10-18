"""Guided setup reviews exact inventory then commits one durable household change."""

from copy import deepcopy
from datetime import timedelta

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized

from custom_components.simplifi.models import Conflict, SimpliFiError

from .conftest import command


def configuration(engine):
    return {
        "name": "New person",
        "devices": list(engine.state.devices),
        "schedules": [
            {
                "name": "School nights",
                "days": [0, 1, 2, 3, 6],
                "start": "21:00",
                "end": "07:00",
                "overnight": True,
            }
        ],
    }


def unassign(engine):
    for device in engine.state.devices.values():
        device.group = None


async def test_review_is_read_only_then_atomically_applies_assignments_and_rules(household):
    engine, gateway, _, saved = household
    unassign(engine)
    config = configuration(engine)
    before = engine.state.to_dict()
    review = await command(engine, "preview_setup", configuration=config)
    assert engine.state.to_dict() == before and not saved and not gateway.policies
    assert review["group"]["name"] == "New person" and len(review["rules"]) == 1
    change = await command(
        engine,
        "apply_setup",
        configuration=config,
        preview_hash=review["preview_hash"],
        expected_revision=0,
        confirm=True,
        request_id="setup",
    )
    assert engine.state.revision == 1 and len(saved) == 1
    group = review["group"]["id"]
    assert change["targets"] == {"group_id": group}
    assert all(d.group == group for d in engine.state.devices.values())
    assert engine.state.rules[review["rules"][0]["id"]].windows[0].overnight
    assert change == await command(
        engine,
        "apply_setup",
        configuration=config,
        preview_hash=review["preview_hash"],
        expected_revision=0,
        confirm=True,
        request_id="setup",
    )
    assert len(saved) == 1 and not gateway.policies


async def test_stale_or_changed_inventory_actor_configuration_and_revision_require_review(
    household,
):
    engine, _, now, _ = household
    unassign(engine)
    config = configuration(engine)
    review = await command(engine, "preview_setup", configuration=config)
    payload = {
        "configuration": config,
        "preview_hash": review["preview_hash"],
        "expected_revision": 0,
        "confirm": True,
    }
    with pytest.raises(Conflict):
        await engine.command("apply_setup", payload, "different-admin", administrator=True)
    with pytest.raises(Conflict):
        await command(
            engine, "apply_setup", **{**payload, "configuration": {**config, "name": "Changed"}}
        )
    device = next(iter(engine.state.devices.values()))
    device.mac = "02:11:22:33:44:99"
    with pytest.raises(Conflict):
        await command(engine, "apply_setup", **payload)
    now[0] += timedelta(seconds=91)
    with pytest.raises(SimpliFiError, match="inventory"):
        await command(engine, "apply_setup", **payload)
    engine.state.last_observed = now[0].isoformat()
    engine.state.revision += 1
    with pytest.raises(Conflict):
        await command(engine, "apply_setup", **payload)


async def test_existing_group_retains_settings_rules_exceptions_and_nonselected_assignments(
    household,
):
    engine, _, _, _ = household
    await command(
        engine,
        "upsert_rule",
        rule_id="existing",
        name="Existing",
        kind="internet",
        groups=["child"],
    )
    await command(engine, "pause_internet", group_id="child", duration_minutes=30)
    before = deepcopy(engine.state)
    config = {"group_id": "child", "name": "Ignored new name", "devices": [], "schedules": []}
    review = await command(engine, "preview_setup", configuration=config)
    await command(
        engine,
        "apply_setup",
        configuration=config,
        preview_hash=review["preview_hash"],
        expected_revision=engine.state.revision,
        confirm=True,
    )
    assert engine.state.groups == before.groups and engine.state.rules == before.rules
    assert engine.state.exceptions == before.exceptions and engine.state.devices == before.devices


@pytest.mark.parametrize(
    "case",
    [
        "owned",
        "out_of_scope",
        "missing",
        "duplicate",
        "invalid_window",
        "duplicate_name",
        "no_confirmation",
        "unknown_field",
    ],
)
async def test_rejects_ambiguous_or_unreviewed_setup(household, case):
    engine, _, _, saved = household
    if case != "owned":
        unassign(engine)
    config = configuration(engine)
    first = next(iter(engine.state.devices.values()))
    if case == "out_of_scope":
        first.network = "outside"
    if case == "missing":
        config["devices"] = ["absent"]
    if case == "duplicate":
        config["devices"] *= 2
    if case == "invalid_window":
        config["schedules"][0]["overnight"] = False
    if case == "duplicate_name":
        config["name"] = engine.state.groups["child"].name
    if case == "unknown_field":
        config["management"] = True
    before = engine.state.to_dict()
    if case == "no_confirmation":
        review = await command(engine, "preview_setup", configuration=config)
        with pytest.raises(SimpliFiError):
            await command(
                engine,
                "apply_setup",
                configuration=config,
                preview_hash=review["preview_hash"],
                expected_revision=0,
                confirm=False,
            )
    else:
        with pytest.raises(SimpliFiError):
            await command(engine, "preview_setup", configuration=config)
    assert engine.state.to_dict() == before and not saved


async def test_failed_save_never_leaves_partial_person_or_assignments(household):
    engine, _, _, _ = household
    unassign(engine)
    config = configuration(engine)
    review = await command(engine, "preview_setup", configuration=config)
    before = engine.state.to_dict()

    async def fail(_):
        raise OSError("disk unavailable")

    engine.save = fail
    with pytest.raises(OSError):
        await command(
            engine,
            "apply_setup",
            configuration=config,
            preview_hash=review["preview_hash"],
            expected_revision=0,
            confirm=True,
        )
    assert engine.state.to_dict() == before


async def test_ha_guided_setup_administrator_only_and_preview_does_not_sync(
    hass, entry, hass_admin_user, hass_read_only_user, monkeypatch
):
    engine = entry.runtime_data.engine
    config = {"name": "New", "devices": []}

    async def forbidden():
        raise AssertionError("Preview requested a policy refresh")

    monkeypatch.setattr(entry.runtime_data, "async_request_refresh", forbidden)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "simplifi",
            "preview_setup",
            {"entry_id": entry.entry_id, "configuration": config},
            context=Context(user_id=hass_read_only_user.id),
            blocking=True,
            return_response=True,
        )
    result = await hass.services.async_call(
        "simplifi",
        "preview_setup",
        {"entry_id": entry.entry_id, "configuration": config},
        context=Context(user_id=hass_admin_user.id),
        blocking=True,
        return_response=True,
    )
    assert result["group"]["name"] == "New" and engine.state.revision == 0
    await hass.async_block_till_done()


async def test_new_setup_requires_explicit_gateway_schedule_verification(household):
    engine, _, _, _ = household
    unassign(engine)
    engine.state.gateway_timezone_confirmed = False
    config = configuration(engine)
    with pytest.raises(SimpliFiError, match="timezone"):
        await command(engine, "preview_setup", configuration=config)
    config["gateway_timezone_confirmed"] = True
    review = await command(engine, "preview_setup", configuration=config)
    assert review["confirms_gateway_timezone"] and not engine.state.gateway_timezone_confirmed
    await command(
        engine,
        "apply_setup",
        configuration=config,
        preview_hash=review["preview_hash"],
        expected_revision=0,
        confirm=True,
    )
    assert engine.state.gateway_timezone_confirmed
