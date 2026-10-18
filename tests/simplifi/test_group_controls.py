"""Group-wide unblock never widens into another person or a whole network."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.simplifi.group_controls import summary
from custom_components.simplifi.models import Group, Rule, SimpliFiError, State, Window
from custom_components.simplifi.planner import lifted, plan

from .conftest import command


def prepare(engine):
    state = engine.state
    state.groups["other"] = Group("other", "Other person")
    list(state.devices.values())[1].group = "other"
    for key, kind, targets, end in [
        ("bed", "internet", [], "22:00"),
        ("video", "category", [4], "23:00"),
        ("chat", "application", [123], None),
        ("site", "domain", ["example.com"], "22:30"),
    ]:
        windows = [] if end is None else [Window(key, key, list(range(7)), "20:00", end)]
        state.rules[key] = Rule(key, key, kind, ["child", "other"], targets, windows)
    state.rules["later"] = Rule(
        "later",
        "Later",
        "internet",
        ["child"],
        windows=[Window("later", "Later", list(range(7)), "22:30", "23:30")],
    )
    state.rules["wide"] = Rule("wide", "Whole network", "internet", [], networks=["demo-family"])


def desired(engine, gateway, now):
    return plan(engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0])


async def test_default_unblock_all_kinds_with_independent_ends_and_exact_policy_scope(household):
    engine, gateway, now, _ = household
    prepare(engine)
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await engine.refresh()
    baseline = deepcopy(gateway.policies)
    original_rules = deepcopy(engine.state.rules)
    result = await command(
        engine, "unblock_group", group_id="child", request_id="default", reason="Homework"
    )
    records = {e.rule: e for e in engine.state.exceptions.values()}
    assert set(records) == {"bed", "video", "chat", "site"}
    assert records["bed"].expires_at == "2026-10-13T21:00:00+00:00"
    assert records["video"].expires_at == "2026-10-13T22:00:00+00:00"
    assert records["site"].expires_at == "2026-10-13T21:30:00+00:00"
    assert records["chat"].expires_at is None
    assert all(e.group == "child" and e.actor == "admin-id" for e in records.values())
    assert len(result["details"]["timing"]["changes"]) == 4
    policies = desired(engine, gateway, now)
    for key, body in policies.items():
        if any(key.startswith("rule:" + r + ":") for r in records):
            assert body["enabled"] == (
                body["source"]["trafficFilter"]["macAddressFilter"].endswith(":02")
            )
        else:
            assert body["enabled"]
    await engine.refresh()
    assert set(gateway.policies) == set(baseline)
    assert engine.state.rules == original_rules
    assert engine.status("child")["state"] == "network_blocked"
    await command(engine, "end_group_unblock", group_id="child")
    await engine.refresh()
    assert gateway.policies == baseline


@pytest.mark.parametrize("mode", ["duration_minutes", "expires_at", "indefinite"])
async def test_explicit_unblock_captures_future_rules_but_not_new_rules(household, mode):
    engine, _, now, _ = household
    prepare(engine)
    await command(engine, "pause_internet", group_id="child", duration_minutes=20)
    end = (now[0] + timedelta(hours=2)).isoformat()
    payload = {mode: {"duration_minutes": 120, "expires_at": end, "indefinite": True}[mode]}
    await command(engine, "unblock_group", group_id="child", **payload)
    assert all(e.kind == "rule_allow" for e in engine.state.exceptions.values())
    assert {e.rule for e in engine.state.exceptions.values()} == {
        "bed",
        "video",
        "chat",
        "site",
        "later",
    }
    assert {e.expires_at for e in engine.state.exceptions.values()} == (
        {None} if mode == "indefinite" else {end}
    )
    engine.state.rules["new"] = Rule("new", "New rule", "internet", ["child"])
    assert not lifted(engine.state, "new", "child", now[0])
    assert not lifted(engine.state, "wide", "child", now[0])
    now[0] += timedelta(minutes=61)
    assert lifted(engine.state, "later", "child", now[0])


async def test_existing_global_and_person_suspensions_stay_untouched(household):
    engine, _, now, _ = household
    prepare(engine)
    await command(engine, "suspend_rule", rule_id="video", group_id="child", duration_minutes=30)
    await command(engine, "suspend_rule", rule_id="site", duration_minutes=40)
    await command(engine, "allow_rule", rule_id="chat", duration_minutes=50)
    protected = deepcopy(engine.state.exceptions)
    await command(engine, "unblock_group", group_id="child", duration_minutes=60)
    assert all(engine.state.exceptions[k] == v for k, v in protected.items())
    assert {e.rule for k, e in engine.state.exceptions.items() if k not in protected} == {
        "bed",
        "later",
    }
    await command(engine, "end_group_unblock", group_id="child")
    assert engine.state.exceptions == protected
    assert not lifted(engine.state, "bed", "child", now[0])


async def test_extension_aligns_finite_allowances_to_latest_and_keeps_identity(household):
    engine, _, now, _ = household
    prepare(engine)
    await command(engine, "unblock_group", group_id="child")
    originals = deepcopy(engine.state.exceptions)
    now[0] += timedelta(minutes=5)
    result = await command(engine, "extend_group_unblock", group_id="child", duration_minutes=15)
    for key, old in originals.items():
        new = engine.state.exceptions[key]
        assert new.expires_at == ("2026-10-13T22:15:00+00:00" if old.expires_at else None)
        new_copy = deepcopy(new)
        new_copy.expires_at = old.expires_at
        assert new_copy == old
    audit = result["details"]["timing"]
    assert audit["request"] == {"mode": "extend_group_minutes", "value": 15}
    assert len(audit["changes"]) == 3
    assert summary(engine.state, "child", now[0])["latest_deadline"] == "2026-10-13T22:15:00+00:00"
    assert summary(engine.state, "child", now[0])["indefinite_allowances"] == 1


async def test_existing_internet_allowances_join_extension_and_end_without_duplicates(household):
    engine, _, now, _ = household
    prepare(engine)
    await command(engine, "allow_internet", group_id="child", duration_minutes=20)
    internet = deepcopy(next(iter(engine.state.exceptions.values())))
    await command(engine, "allow_rule", rule_id="video", group_id="child", duration_minutes=40)
    await command(engine, "extend_group_unblock", group_id="child", duration_minutes=10)
    assert {e.expires_at for e in engine.state.exceptions.values()} == {"2026-10-13T21:20:00+00:00"}
    assert engine.state.exceptions[internet.id].captured == ["bed"]
    await command(engine, "unblock_group", group_id="child")
    assert all(e.kind == "rule_allow" for e in engine.state.exceptions.values())
    assert len({e.rule for e in engine.state.exceptions.values()}) == len(engine.state.exceptions)
    await command(engine, "end_group_unblock", group_id="child")
    assert not engine.state.exceptions


async def test_pause_only_unblock_and_no_applicable_control(household):
    engine, _, _, saved = household
    with pytest.raises(SimpliFiError, match="No applicable"):
        await command(engine, "unblock_group", group_id="child")
    assert not saved
    await command(engine, "pause_internet", group_id="child", indefinite=True)
    await command(engine, "unblock_group", group_id="child")
    assert not engine.state.exceptions


@pytest.mark.parametrize(
    "payload",
    [
        {"expires_at": "2026-10-13T20:00:00Z"},
        {"duration_minutes": 10081},
        {"duration_minutes": 10, "indefinite": True},
        {"expires_at": "2026-10-13T23:00:00"},
    ],
)
async def test_invalid_unblock_never_cancels_a_pause(household, payload):
    engine, _, _, _ = household
    await command(engine, "pause_internet", group_id="child", indefinite=True)
    before = engine.state.to_dict()
    with pytest.raises(SimpliFiError):
        await command(engine, "unblock_group", group_id="child", **payload)
    assert engine.state.to_dict() == before


async def test_empty_indefinite_expired_and_too_long_extensions_reject(household):
    engine, _, now, _ = household
    prepare(engine)
    with pytest.raises(SimpliFiError, match="No active timed"):
        await command(engine, "extend_group_unblock", group_id="child", duration_minutes=15)
    await command(engine, "unblock_group", group_id="child", indefinite=True)
    with pytest.raises(SimpliFiError, match="No active timed"):
        await command(engine, "extend_group_unblock", group_id="child", duration_minutes=15)
    await command(engine, "unblock_group", group_id="child", duration_minutes=1)
    before = engine.state.to_dict()
    with pytest.raises(SimpliFiError, match="seven days"):
        await command(engine, "extend_group_unblock", group_id="child", duration_minutes=10080)
    assert engine.state.to_dict() == before
    now[0] += timedelta(minutes=2)
    with pytest.raises(SimpliFiError, match="No active timed"):
        await command(engine, "extend_group_unblock", group_id="child", duration_minutes=15)


async def test_atomic_failure_idempotency_and_persisted_capture(household):
    engine, _, _, saved = household
    prepare(engine)
    await command(engine, "pause_internet", group_id="child", indefinite=True)
    before = engine.state.to_dict()
    save = engine.save
    engine.save = AsyncMock(side_effect=OSError("disk full"))
    with pytest.raises(OSError):
        await command(engine, "unblock_group", group_id="child", duration_minutes=30)
    assert engine.state.to_dict() == before
    engine.save = save
    first = await command(
        engine, "unblock_group", group_id="child", duration_minutes=30, request_id="same"
    )
    assert (
        await command(
            engine, "unblock_group", group_id="child", duration_minutes=30, request_id="same"
        )
        == first
    )
    restored = State.from_dict(saved[-1])
    assert restored.exceptions == engine.state.exceptions
    assert restored.changes[-1] == first


@pytest.mark.parametrize("scope", ["watch_rules", "agent_controls", "read_only"])
async def test_group_grant_is_required_for_every_new_control(household, scope):
    engine, _, _, _ = household
    prepare(engine)
    await command(
        engine, "set_access_grant", user_id="delegate", scope=scope, groups=["child"], confirm=True
    )
    for action, data in [
        ("unblock_group", {"duration_minutes": 30}),
        ("extend_group_unblock", {"duration_minutes": 10}),
        ("end_group_unblock", {}),
    ]:
        with pytest.raises(SimpliFiError):
            await engine.command(action, {"group_id": "other", **data}, "delegate")
        if scope == "read_only":
            with pytest.raises(SimpliFiError):
                await engine.command(action, {"group_id": "child", **data}, "delegate")
        else:
            change = await engine.command(action, {"group_id": "child", **data}, "delegate")
            assert change["actor"] == "delegate"
    await command(engine, "revoke_access_grant", user_id="delegate", confirm=True)
    with pytest.raises(SimpliFiError):
        await engine.command(
            "unblock_group", {"group_id": "child", "duration_minutes": 30}, "delegate"
        )


async def test_live_expiry_acknowledgement_remains_required(household):
    engine, gateway, _, _ = household
    prepare(engine)
    engine.state.management = True
    gateway.simulation = False
    before = engine.state.to_dict()
    with pytest.raises(SimpliFiError, match="Acknowledge"):
        await command(engine, "unblock_group", group_id="child", duration_minutes=30)
    assert engine.state.to_dict() == before


async def test_ha_services_read_models_and_expiry_reconcile(hass, entry, hass_admin_user):
    from homeassistant.core import Context
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed_exact

    from custom_components.simplifi.presentation import dashboard_data

    coordinator = entry.runtime_data
    engine = coordinator.engine
    now = [dt_util.utcnow()]
    engine.clock = lambda: now[0]
    for device in engine.state.devices.values():
        device.group = "demo-family"
    engine.state.rules["test"] = Rule("test", "All content test", "category", ["demo-family"], [4])
    await command(engine, "set_management", enabled=True)
    await coordinator.async_refresh()
    assert all(p["enabled"] for p in engine.gateway.policies.values())
    deadline = now[0] + timedelta(seconds=5)
    await hass.services.async_call(
        "simplifi",
        "unblock_group",
        {"entry_id": entry.entry_id, "group_id": "demo-family", "expires_at": deadline.isoformat()},
        context=Context(user_id=hass_admin_user.id),
        blocking=True,
        return_response=True,
    )
    await coordinator.async_refresh()
    assert all(not p["enabled"] for p in engine.gateway.policies.values())
    view = await dashboard_data(hass, entry)
    assert view["groups"][0]["unblock"]["timed_allowances"] == 1
    await command(
        engine,
        "set_access_grant",
        user_id="delegate",
        scope="watch_rules",
        groups=["demo-family"],
        confirm=True,
    )
    status = await engine.command("access_status", {}, "delegate")
    assert status["groups"][0]["unblock"] == view["groups"][0]["unblock"]
    now[0] = deadline
    async_fire_time_changed_exact(hass, deadline + timedelta(milliseconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert all(p["enabled"] for p in engine.gateway.policies.values())
    assert (await dashboard_data(hass, entry))["groups"][0]["unblock"]["allowances"] == 0
