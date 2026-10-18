"""Rule lifetime, scope composition and default deadlines across durable reloads."""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta

import pytest

from custom_components.family_network.models import FamilyError, Group, Rule, State, Window
from custom_components.family_network.planner import plan
from custom_components.family_network.storage import HouseholdStorage

from .conftest import command
from .test_access import grant, limited
from .test_engine import bedtime


async def edit(engine, rule_id, **changes):
    payload = asdict(engine.state.rules[rule_id])
    payload.pop("id")
    return await command(engine, "upsert_rule", rule_id=rule_id, **(payload | changes))


async def test_rule_edit_retains_exceptions_but_off_on_cannot_revive_them(household):
    engine, _, _, _ = household
    bedtime(engine.state)
    await command(engine, "suspend_rule", rule_id="bedtime")
    await command(engine, "allow_rule", rule_id="bedtime", group_id="child")
    before = deepcopy(engine.state.exceptions)
    await edit(engine, "bedtime", name="Renamed")
    assert engine.state.exceptions == before
    await command(engine, "set_rule_enabled", rule_id="bedtime", enabled=False)
    assert not engine.state.exceptions
    await command(engine, "set_rule_enabled", rule_id="bedtime", enabled=True)
    assert engine.status("child")["state"] == "scheduled_block"
    await command(engine, "allow_internet", group_id="child")
    await edit(engine, "bedtime", enabled=False)
    assert not engine.state.exceptions
    await edit(engine, "bedtime", enabled=True)
    assert engine.status("child")["state"] == "scheduled_block"


async def test_target_removal_prunes_only_affected_scopes_and_captures(household):
    engine, _, _, _ = household
    bedtime(engine.state)
    bedtime(engine.state, "other")
    engine.state.groups["second"] = Group("second", "Second")
    engine.state.rules["bedtime"].groups.append("second")
    await command(engine, "allow_internet", group_id="child", duration_minutes=30)
    await command(engine, "suspend_rule", rule_id="bedtime", group_id="second")
    await command(engine, "suspend_rule", rule_id="bedtime")
    await edit(engine, "bedtime", groups=["second"])
    assert len(engine.state.exceptions) == 3
    allowance = next(e for e in engine.state.exceptions.values() if e.kind == "internet_allow")
    assert allowance.captured == ["other"]
    assert all(e.captured == ["bedtime"] for e in engine.state.exceptions.values() if e.rule)
    await command(engine, "delete_rule", rule_id="other")
    assert all(e.kind != "internet_allow" for e in engine.state.exceptions.values())


@pytest.mark.parametrize("action", ["suspend_rule", "allow_rule", "extend_rule_suspension"])
async def test_disabled_rule_rejects_new_exception_without_saving(household, action):
    engine, _, _, saved = household
    bedtime(engine.state)
    engine.state.rules["bedtime"].enabled = False
    with pytest.raises(FamilyError, match="Enable the rule"):
        await command(engine, action, rule_id="bedtime", duration_minutes=30)
    assert not saved


@pytest.mark.parametrize(
    "action", ["pause_internet", "suspend_rule", "allow_rule", "allow_internet"]
)
async def test_default_deadlines_and_conflicting_modes(household, action):
    engine, _, _, _ = household
    engine.state.rules["r"] = Rule("r", "Always", "internet", ["child"])
    target = {"group_id": "child"} if action.endswith("internet") else {"rule_id": "r"}
    with pytest.raises(FamilyError, match="exactly one"):
        await command(engine, action, **target, duration_minutes=10, next_window_end=True)
    await command(engine, action, **target)
    assert next(iter(engine.state.exceptions.values())).expires_at is None
    engine.state = State.from_dict(engine.state.to_dict())
    assert next(iter(engine.state.exceptions.values())).expires_at is None


async def test_default_internet_allowance_ends_each_rule_at_its_own_window(household):
    engine, _, now, _ = household
    bedtime(engine.state, "early", end="22:00")
    bedtime(engine.state, "late", end="23:00")
    await command(engine, "allow_internet", group_id="child")
    records = {e.captured[0]: e.expires_at for e in engine.state.exceptions.values()}
    assert records == {
        "early": now[0].replace(hour=21, minute=0).isoformat(),
        "late": now[0].replace(hour=22, minute=0).isoformat(),
    }
    now[0] += timedelta(minutes=31)
    assert engine.status("child")["state"] == "allowed"
    assert len([e for e in engine.state.exceptions.values() if e.active(now[0])]) == 1


async def test_default_rule_allowance_covers_overlapping_windows_not_future_window(household):
    engine, _, now, _ = household
    bedtime(engine.state, end="22:00")
    engine.state.rules["bedtime"].windows.append(
        Window("overlap", "Overlap", list(range(7)), "21:00", "23:00")
    )
    await command(engine, "allow_rule", rule_id="bedtime")
    assert (
        next(iter(engine.state.exceptions.values())).expires_at
        == now[0].replace(hour=22, minute=0).isoformat()
    )
    bedtime(engine.state, "future", "23:00", "23:59")
    with pytest.raises(FamilyError, match="No active window"):
        await command(engine, "allow_rule", rule_id="future")
    await command(engine, "allow_rule", rule_id="future", duration_minutes=60)


async def test_same_scope_replaces_opposite_kind_but_wrong_end_does_nothing(household):
    engine, _, _, _ = household
    bedtime(engine.state)
    await command(engine, "suspend_rule", rule_id="bedtime")
    await command(engine, "allow_rule", rule_id="bedtime", duration_minutes=30)
    assert [e.kind for e in engine.state.exceptions.values()] == ["rule_allow"]
    await command(engine, "resume_rule", rule_id="bedtime")
    assert len(engine.state.exceptions) == 1
    await command(engine, "suspend_rule", rule_id="bedtime")
    await command(engine, "end_rule_allowance", rule_id="bedtime")
    assert [e.kind for e in engine.state.exceptions.values()] == ["suspension"]


async def test_group_internet_allow_replaces_pause_and_individual_rule_allow(household):
    engine, _, now, _ = household
    bedtime(engine.state)
    await command(engine, "pause_internet", group_id="child")
    await command(engine, "allow_internet", group_id="child", duration_minutes=20)
    assert [e.kind for e in engine.state.exceptions.values()] == ["internet_allow"]
    await command(engine, "allow_internet", group_id="child", duration_minutes=40)
    assert len(engine.state.exceptions) == 1
    assert (
        next(iter(engine.state.exceptions.values())).expires_at
        == (now[0] + timedelta(minutes=40)).isoformat()
    )
    await command(engine, "allow_rule", rule_id="bedtime", group_id="child")
    assert [e.kind for e in engine.state.exceptions.values()] == ["rule_allow"]
    await command(engine, "end_allowance", group_id="child")
    assert not engine.state.exceptions
    await command(engine, "allow_internet", group_id="child")
    await command(engine, "end_rule_allowance", rule_id="bedtime", group_id="child")
    assert not engine.state.exceptions


@pytest.mark.parametrize(
    "changes",
    [{"kind": "domain", "targets": ["example.org"]}, {"groups": [], "networks": ["demo-family"]}],
)
async def test_existing_rule_kind_and_scope_type_are_immutable(household, changes):
    engine, _, _, saved = household
    bedtime(engine.state)
    with pytest.raises(FamilyError, match="keeps its kind and scope type"):
        await edit(engine, "bedtime", **changes)
    assert not saved


async def test_quarantine_indefinite_pause_restart_resume_and_off_on(household):
    engine, gateway, now, _ = household
    for device in engine.state.devices.values():
        device.group = None
    await command(engine, "set_quarantine", enabled=True, excluded_devices=[], confirm=True)
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await engine.refresh()

    def desired():
        return plan(
            engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0]
        )

    active = desired()
    await command(engine, "suspend_quarantine")
    engine.state = State.from_dict(engine.state.to_dict())
    assert engine.state.quarantine_paused(now[0])
    paused = desired()
    assert set(paused) == set(active) and all(not p["enabled"] for p in paused.values())
    await command(engine, "set_quarantine", enabled=True, excluded_devices=[], confirm=True)
    assert engine.state.quarantine_paused(now[0])
    await command(engine, "resume_quarantine")
    assert desired() == active
    await command(engine, "suspend_quarantine", duration_minutes=10)
    now[0] += timedelta(minutes=11)
    assert not engine.state.quarantine_paused(now[0])
    assert desired() == active
    await command(engine, "suspend_quarantine")
    await command(engine, "set_quarantine", enabled=False, excluded_devices=[])
    with pytest.raises(FamilyError, match="Enable quarantine"):
        await command(engine, "suspend_quarantine")
    await command(engine, "set_quarantine", enabled=True, excluded_devices=[], confirm=True)
    assert not engine.state.quarantine_paused(now[0])


async def test_quarantine_scoped_status_and_authorization_agree(household):
    engine, _, _, _ = household
    await grant(engine)
    assert "quarantine_rule" not in await limited(engine, "access_status")
    await grant(engine, "read_only", networks=engine.state.networks)
    q = (await limited(engine, "access_status"))["quarantine_rule"]
    assert not q["can_control"] and not q["can_toggle"]
    await grant(engine, networks=engine.state.networks)
    q = (await limited(engine, "access_status"))["quarantine_rule"]
    assert q["can_control"] and not q["can_toggle"]
    with pytest.raises(FamilyError):
        await limited(engine, "set_quarantine", enabled=True, excluded_devices=[], confirm=True)
    await command(engine, "set_quarantine", enabled=True, excluded_devices=[], confirm=True)
    await limited(engine, "suspend_quarantine")
    assert (await limited(engine, "access_status"))["quarantine_rule"]["paused"]


async def test_upgrade_keeps_finite_pause_and_snapshots_original_once(hass, household):
    engine, _, now, _ = household
    store = HouseholdStorage(hass, "migration")
    raw = engine.state.to_dict()
    raw.pop("quarantine_suspended")
    raw["quarantine"] = True
    raw["quarantine_until"] = (now[0] + timedelta(minutes=10)).isoformat()
    await store.store.async_save(raw)
    loaded = await store.load(engine.state)
    assert loaded.quarantine_paused(now[0])
    assert await store.rule_pause_backup.async_load() == raw
    loaded.quarantine_until = None
    loaded.quarantine_suspended = False
    await store.store.async_save(loaded.to_dict())
    await store.load(engine.state)
    assert await store.rule_pause_backup.async_load() == raw


async def test_multiple_allowance_deadlines_compare_instants_not_offset_text(household):
    engine, _, _, _ = household
    bedtime(engine.state)
    bedtime(engine.state, "second")
    await command(engine, "allow_rule", rule_id="bedtime", expires_at="2026-10-13T22:00:00+01:00")
    await command(engine, "allow_rule", rule_id="second", expires_at="2026-10-13T21:30:00+00:00")
    assert engine.status("child")["expires_at"] == "2026-10-13T21:00:00+00:00"


async def test_live_finite_permissive_defaults_require_outage_acknowledgement(household):
    engine, gateway, _, _ = household
    bedtime(engine.state)
    gateway.simulation = False
    engine.state.management = True
    with pytest.raises(FamilyError, match="expiry dependence"):
        await command(engine, "allow_internet", group_id="child")
    await command(engine, "allow_rule", rule_id="bedtime", indefinite=True)
    assert next(iter(engine.state.exceptions.values())).expires_at is None
