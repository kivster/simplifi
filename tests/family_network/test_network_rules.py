"""Whole-network scope, individual exceptions and stable controller identities."""

from copy import deepcopy
from datetime import timedelta

import pytest

from custom_components.family_network.models import FamilyError, Rule, State
from custom_components.family_network.planner import next_change, plan

from .conftest import command


async def network_rule(engine, **extra):
    await command(
        engine,
        "upsert_rule",
        rule_id="wide",
        name="Family network bedtime",
        kind="internet",
        networks=["demo-family"],
        **extra,
    )


@pytest.mark.parametrize(
    "scope",
    [
        {},
        {"groups": ["child"], "networks": ["demo-family"]},
        {"networks": ["outside"]},
        {"networks": ["demo-family", "demo-family"]},
    ],
)
async def test_explicit_exclusive_managed_scope_required(household, scope):
    engine, _, _, saved = household
    with pytest.raises(FamilyError):
        await command(engine, "upsert_rule", name="Invalid", kind="internet", **scope)
    assert not engine.state.rules and not saved


async def test_wide_policy_does_not_depend_on_assigned_clients(household):
    engine, gateway, now, _ = household
    engine.state.devices.clear()
    await network_rule(engine)
    desired = plan(
        engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0]
    )
    assert len(desired) == 1
    body = next(iter(desired.values()))
    assert body["source"]["trafficFilter"] == {
        "type": "NETWORK",
        "networkFilter": {"networkIds": ["demo-family"], "matchOpposite": False},
    }
    assert body["destination"] == {"zoneId": gateway.external_zone}
    assert body["enabled"] is True
    # Deleting an unrelated group must not remove whole-network rules.
    await command(engine, "delete_group", group_id="child", confirm=True)
    assert "wide" in engine.state.rules


async def test_allowance_never_bypasses_network_rule_and_partial_coverage_is_visible(household):
    engine, gateway, now, _ = household
    await network_rule(engine)
    assert engine.status("child")["state"] == "network_blocked"
    with pytest.raises(FamilyError, match="No active managed"):
        await command(engine, "allow_internet", group_id="child", duration_minutes=30)
    with pytest.raises(FamilyError, match="not targeted"):
        await command(engine, "allow_rule", rule_id="wide", group_id="child", duration_minutes=30)
    engine.state.rules["personal"] = Rule("personal", "Personal", "internet", ["child"])
    await command(engine, "allow_internet", group_id="child", duration_minutes=30)
    assert next(iter(engine.state.exceptions.values())).captured == ["personal"]
    assert engine.status("child")["state"] == "network_blocked"
    desired = plan(
        engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0]
    )
    assert sum(p["enabled"] for p in desired.values()) == 1
    engine.state.networks.append("other")
    list(engine.state.devices.values())[1].network = "other"
    assert engine.status("child")["state"] == "partially_blocked"
    assert engine.status("child")["blocked_devices"] == 1
    await command(engine, "allow_rule", rule_id="wide", duration_minutes=10)
    assert engine.status("child")["state"] == "allowed"
    now[0] += timedelta(minutes=11)
    assert engine.status("child")["state"] == "partially_blocked"


async def test_network_schedule_and_exception_boundaries_are_projected(household):
    engine, _, now, _ = household
    await network_rule(
        engine,
        windows=[
            {
                "id": "bed",
                "name": "Bedtime",
                "days": list(range(7)),
                "start": "20:00",
                "end": "23:00",
            }
        ],
    )
    assert engine.status("child")["state"] == "network_blocked"
    assert next_change(engine.state, "child", now[0]) == now[0].replace(hour=22, minute=0)
    await command(engine, "suspend_rule", rule_id="wide", duration_minutes=15)
    assert next_change(engine.state, "child", now[0]) == now[0] + timedelta(minutes=15)


@pytest.mark.parametrize("network", [False, True])
async def test_disable_lift_restart_resume_preserve_policy_ids_and_foreign_rules(
    household, network
):
    engine, gateway, now, _ = household
    if network:
        await network_rule(engine)
    else:
        engine.state.rules["wide"] = Rule("wide", "People rule", "internet", ["child"])
    foreign = {"id": "foreign", "name": "Someone else's rule", "enabled": True}
    gateway.policies["foreign"] = deepcopy(foreign)
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await engine.refresh()
    ids = {k: v["id"] for k, v in engine.state.owned.items()}
    for action, fields in [
        ("set_rule_enabled", {"enabled": False}),
        ("set_rule_enabled", {"enabled": True}),
        ("suspend_rule", {"duration_minutes": 15}),
        ("resume_rule", {}),
    ]:
        await command(engine, action, rule_id="wide", **fields)
        await engine.refresh()
        assert {k: v["id"] for k, v in engine.state.owned.items()} == ids
        expected = action == "resume_rule" or fields.get("enabled", False)
        assert all(gateway.policies[i]["enabled"] is expected for i in ids.values())
        engine.state = State.from_dict(engine.state.to_dict())
        before = len(engine.state.journal)
        await engine.refresh()
        assert len(engine.state.journal) == before
        assert gateway.policies["foreign"] == foreign
    await command(engine, "delete_rule", rule_id="wide")
    await engine.refresh()
    assert not engine.state.owned and gateway.policies == {"foreign": foreign}


async def test_quarantine_keeps_disabled_owned_policy_but_does_not_create_unused_ones(household):
    engine, gateway, now, _ = household
    for device in engine.state.devices.values():
        device.group = None
    assert not plan(
        engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0]
    )
    await command(engine, "set_quarantine", enabled=True, excluded_devices=[], confirm=True)
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await engine.refresh()
    ids = {v["id"] for v in engine.state.owned.values()}
    await command(engine, "set_quarantine", enabled=False, excluded_devices=[], confirm=True)
    await engine.refresh()
    assert {v["id"] for v in engine.state.owned.values()} == ids
    assert not any(gateway.policies[i]["enabled"] for i in ids)
    await command(engine, "assign_device", device_id=gateway.clients[0].id, group_id="child")
    await engine.refresh()
    assert len(engine.state.owned) == 1


def test_old_rules_load_as_group_targets_without_rebinding(household):
    engine, _, _, _ = household
    engine.state.rules["old"] = Rule("old", "Old", "internet", ["child"])
    raw = engine.state.to_dict()
    raw["rules"]["old"].pop("networks")
    restored = State.from_dict(raw)
    assert restored.rules["old"].groups == ["child"]
    assert restored.rules["old"].networks == []


def test_category_network_coverage_is_explicit(household):
    from custom_components.family_network.dns_catalog import CATEGORIES
    from custom_components.family_network.filter_status import category_marks

    engine, gateway, now, _ = household
    category = CATEGORIES["video"]["dpi"]
    engine.state.networks.append("other")
    list(engine.state.devices.values())[1].network = "other"
    engine.state.rules["wide"] = Rule(
        "wide", "Network video", "category", [], [category], networks=["demo-family"]
    )
    marks, _ = category_marks(
        engine.state,
        gateway.networks,
        "child",
        {"profiles": [], "fresh": True},
        True,
        {category},
        now[0],
    )
    video = next(m for m in marks if m["slug"] == "video")
    assert video["rules"] == ["wide"]
    assert video["label"] == "Some devices restricted"
    assert "Managed rules cover 1 of 2 assigned devices" in video["reasons"]


async def test_network_rule_upgrade_preserves_old_shape_once(hass, household):
    from custom_components.family_network.storage import HouseholdStorage

    engine, _, _, _ = household
    engine.state.rules["old"] = Rule("old", "Old rule", "internet", ["child"])
    raw = engine.state.to_dict()
    raw["rules"]["old"].pop("networks")
    storage = HouseholdStorage(hass, "network-upgrade")
    await storage.store.async_save(raw)
    loaded = await storage.load(engine.state)
    assert loaded.rules["old"].networks == []
    assert await storage.network_rules_backup.async_load() == raw
    await storage.save(loaded)
    await storage.load(engine.state)
    assert await storage.network_rules_backup.async_load() == raw
