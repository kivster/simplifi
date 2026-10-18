"""Behavioral precedence, durability, stale edits, permission and scope regressions."""

from copy import deepcopy
from datetime import timedelta

import pytest

from custom_components.simplifi.models import Conflict, Rule, SimpliFiError, State, Window
from custom_components.simplifi.planner import group_status, next_change, plan

from .conftest import command


def bedtime(state, key="bedtime", start="20:00", end="23:00"):
    state.rules[key] = Rule(
        key, key, "internet", ["child"], windows=[Window(key, key, list(range(7)), start, end)]
    )


async def test_pause_resume_and_extension(household):
    engine, _, now, _ = household
    bedtime(engine.state)
    await command(engine, "pause_internet", group_id="child", duration_minutes=30)
    first = next(iter(engine.state.exceptions.values())).expires_at
    await command(engine, "extend_pause", group_id="child", duration_minutes=30)
    assert next(iter(engine.state.exceptions.values())).expires_at != first
    assert engine.status("child")["state"] == "paused"
    await command(engine, "resume_internet", group_id="child")
    assert engine.status("child")["state"] == "scheduled_block"
    now[0] += timedelta(hours=3)
    assert engine.status("child")["state"] == "available"


async def test_allowance_captures_current_rules_and_new_pause_cancels(household):
    engine, _, now, _ = household
    bedtime(engine.state)
    bedtime(engine.state, "later", "22:00", "23:00")
    engine.state.rules["content"] = Rule("content", "Content", "category", ["child"], [0])
    await command(engine, "allow_internet", group_id="child", duration_minutes=120)
    allowance = next(iter(engine.state.exceptions.values()))
    assert allowance.captured == ["bedtime"]
    assert engine.status("child")["state"] == "allowed"
    assert next_change(engine.state, "child", now[0]) == now[0].replace(
        hour=21, minute=0
    )  # 22:00 BST
    now[0] += timedelta(minutes=40)
    assert engine.status("child")["state"] == "scheduled_block"
    await command(engine, "pause_internet", group_id="child", indefinite=True)
    assert all(e.kind != "internet_allow" for e in engine.state.exceptions.values())
    await command(engine, "resume_internet", group_id="child")
    assert not engine.state.exceptions


async def test_whole_and_group_rule_lifts_compose(household):
    engine, _, _, _ = household
    bedtime(engine.state)
    await command(engine, "suspend_rule", rule_id="bedtime", duration_minutes=30)
    await command(engine, "allow_rule", rule_id="bedtime", group_id="child", duration_minutes=60)
    await command(engine, "resume_rule", rule_id="bedtime")
    assert engine.status("child")["state"] == "allowed"
    await command(engine, "end_rule_allowance", rule_id="bedtime", group_id="child")
    assert engine.status("child")["state"] == "scheduled_block"


@pytest.mark.parametrize(
    "actor,admin", [(None, True), ("", True), ("child", False), ("unknown", False)]
)
async def test_unauthorised_never_saves(household, actor, admin):
    engine, _, _, saved = household
    before = deepcopy(engine.state.to_dict())
    with pytest.raises(SimpliFiError):
        await engine.command(
            "pause_internet", {"group_id": "child", "indefinite": True}, actor, administrator=admin
        )
    assert not saved
    assert engine.state.to_dict() == before


@pytest.mark.parametrize(
    "payload",
    [
        {"group_id": "child", "duration_minutes": 30, "indefinite": True},
        {"group_id": "missing", "indefinite": True},
        {"group_id": "child", "duration_minutes": 10081},
        {"group_id": "child", "duration_minutes": 30, "actor": "forged"},
        {"group_id": "child", "expires_at": "2026-10-14T12:00:00"},
    ],
)
async def test_bad_pause_payload_rejected_atomically(household, payload):
    engine, _, _, saved = household
    with pytest.raises(SimpliFiError):
        await engine.command("pause_internet", payload, "admin", administrator=True)
    assert not saved


async def test_idempotency_and_stale_revision(household):
    engine, _, _, _ = household
    data = {
        "group_id": "child",
        "duration_minutes": 30,
        "request_id": "click-1",
        "expected_revision": 0,
    }
    first = await engine.command("pause_internet", data, "admin", administrator=True)
    second = await engine.command("pause_internet", data, "admin", administrator=True)
    assert first == second
    assert engine.state.revision == 1
    with pytest.raises(Conflict):
        await command(engine, "resume_internet", group_id="child", expected_revision=0)
    with pytest.raises(Conflict):
        await engine.command(
            "pause_internet", {**data, "duration_minutes": 60}, "admin", administrator=True
        )


async def test_failed_persistence_does_not_commit_intent(household):
    engine, _, _, _ = household

    async def fail(state):
        raise OSError("disk full")

    engine.save = fail
    with pytest.raises(OSError):
        await command(engine, "pause_internet", group_id="child", indefinite=True)
    assert engine.state.revision == 0
    assert not engine.state.exceptions


async def test_assignment_releases_only_quarantine_and_preserves_manual_pause(household):
    engine, gateway, now, _ = household
    engine.state.devices[gateway.clients[0].id].group = None
    await command(engine, "set_quarantine", enabled=True, excluded_devices=[], confirm=True)
    await command(engine, "pause_internet", group_id="child", indefinite=True)
    desired = plan(
        engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0]
    )
    assert any(k.startswith("quarantine:") for k in desired)
    await command(engine, "assign_device", device_id=gateway.clients[0].id, group_id="child")
    desired = plan(
        engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0]
    )
    assert not any(k.startswith("quarantine:") for k in desired)
    assert len(desired) == 2


async def test_delete_group_requires_review_and_leaves_no_orphan(household):
    engine, _, _, _ = household
    bedtime(engine.state)
    with pytest.raises(SimpliFiError):
        await command(engine, "delete_group", group_id="child", confirm=False)
    await command(engine, "delete_group", group_id="child", confirm=True)
    assert not engine.state.groups and not engine.state.rules
    assert all(d.group is None for d in engine.state.devices.values())


async def test_export_import_bound_to_actor_revision_scope(household):
    engine, _, _, _ = household
    bedtime(engine.state)
    exported = (await command(engine, "export_configuration"))["configuration"]
    assert not {"api_key", "devices", "owned", "journal", "exceptions"} & exported.keys()
    preview = await command(engine, "preview_import", configuration=exported)
    with pytest.raises(Conflict):
        await engine.command(
            "apply_import",
            {
                "configuration": exported,
                "preview_hash": preview["preview_hash"],
                "expected_revision": 0,
            },
            "another-admin",
            administrator=True,
        )
    await command(
        engine,
        "apply_import",
        configuration=exported,
        preview_hash=preview["preview_hash"],
        expected_revision=0,
    )
    assert not engine.state.management
    changed = {**exported, "site": "other"}
    with pytest.raises(SimpliFiError):
        await command(engine, "preview_import", configuration=changed)


@pytest.mark.parametrize("schema", [0, 2, "1"])
def test_unknown_storage_schema_is_not_reset(household, schema):
    engine, _, _, _ = household
    raw = engine.state.to_dict()
    raw["schema"] = schema
    with pytest.raises(SimpliFiError):
        State.from_dict(raw)


async def test_restart_expired_allowance_replans(household):
    engine, gateway, now, _ = household
    bedtime(engine.state)
    await command(engine, "allow_internet", group_id="child", duration_minutes=10)
    engine.state = State.from_dict(engine.state.to_dict())
    now[0] += timedelta(minutes=11)
    assert group_status(engine.state, "child", now[0])["state"] == "scheduled_block"
    assert plan(engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0])
