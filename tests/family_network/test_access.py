"""Explicit grants cannot widen targets, survive revocation or disclose admin data."""

from copy import deepcopy
from datetime import timedelta

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized

from custom_components.family_network.access import status
from custom_components.family_network.models import Conflict, FamilyError, Group, Rule, State

from .conftest import command


async def grant(engine, scope="watch_rules", **kw):
    return await command(
        engine,
        "set_access_grant",
        user_id="delegate",
        scope=scope,
        groups=["child"],
        confirm=True,
        **kw,
    )


async def limited(engine, action, **payload):
    return await engine.command(action, payload, "delegate")


async def test_default_deny_readonly_expiry_revocation_and_replay(household):
    engine, gateway, now, _ = household
    with pytest.raises(FamilyError):
        await limited(engine, "access_status")
    await grant(engine, "read_only")
    assert (await limited(engine, "access_status"))["scope"] == "read_only"
    with pytest.raises(FamilyError):
        await limited(engine, "pause_internet", group_id="child", duration_minutes=30)
    await grant(engine, expires_at=(now[0] + timedelta(minutes=1)).isoformat())
    before = engine.state.revision
    result = await limited(
        engine, "pause_internet", group_id="child", duration_minutes=30, request_id="one"
    )
    assert engine.state.revision == before + 1
    assert result == await limited(
        engine, "pause_internet", group_id="child", duration_minutes=30, request_id="one"
    )
    now[0] += timedelta(minutes=2)
    with pytest.raises(FamilyError):
        await limited(
            engine, "pause_internet", group_id="child", duration_minutes=30, request_id="one"
        )
    await grant(engine)
    await command(engine, "revoke_access_grant", user_id="delegate", confirm=True)
    with pytest.raises(FamilyError):
        await limited(engine, "access_status")
    assert not gateway.policies


@pytest.mark.parametrize(
    "action,payload",
    [
        ("upsert_group", {"name": "New"}),
        ("delete_group", {"group_id": "child", "confirm": True}),
        ("set_management", {"enabled": True}),
        ("sync_now", {}),
        ("dashboard_data", {}),
        ("list_access_grants", {}),
        ("export_configuration", {}),
        ("preview_recovery", {}),
        ("view_activity", {}),
        (
            "set_access_grant",
            {"user_id": "other", "scope": "watch_rules", "all_groups": True, "confirm": True},
        ),
    ],
)
async def test_watch_cannot_edit_or_administer(household, action, payload):
    engine, _, _, _ = household
    await grant(engine)
    before = engine.state.to_dict()
    with pytest.raises(FamilyError):
        await limited(engine, action, **payload)
    assert engine.state.to_dict() == before


async def test_shared_rules_group_lifts_whole_rule_and_network_scope(household):
    engine, _, _, _ = household
    engine.state.groups["other"] = Group("other", "Private group")
    engine.state.rules["shared"] = Rule("shared", "Shared rule", "internet", ["child", "other"])
    engine.state.rules["wide"] = Rule("wide", "Wide rule", "internet", [], networks=["demo-family"])
    await grant(engine)
    for action, payload in [
        ("set_rule_enabled", {"rule_id": "shared", "enabled": False}),
        ("suspend_rule", {"rule_id": "shared", "duration_minutes": 30}),
        ("allow_rule", {"rule_id": "wide", "duration_minutes": 30}),
        ("suspend_quarantine", {"duration_minutes": 30}),
        ("pause_internet", {"group_id": "other", "duration_minutes": 30}),
    ]:
        with pytest.raises(FamilyError):
            await limited(engine, action, **payload)
    for action in (
        "suspend_rule",
        "extend_rule_suspension",
        "resume_rule",
        "allow_rule",
        "end_rule_allowance",
    ):
        payload = {"rule_id": "shared", "group_id": "child"}
        if action in ("suspend_rule", "extend_rule_suspension", "allow_rule"):
            payload["duration_minutes"] = 30
        await limited(engine, action, **payload)
    await grant(engine, networks=["demo-family"])
    await limited(engine, "allow_rule", rule_id="wide", duration_minutes=30)
    await limited(engine, "set_rule_enabled", rule_id="wide", enabled=False)
    await command(engine, "set_quarantine", enabled=True, excluded_devices=[], confirm=True)
    await limited(engine, "suspend_quarantine", duration_minutes=30)
    assert engine.state.rules["shared"].enabled


async def test_agent_edits_require_old_and_new_scope(household):
    engine, _, _, _ = household
    engine.state.groups["other"] = Group("other", "Private")
    engine.state.rules["outside"] = Rule("outside", "Outside", "internet", ["other"])
    device = next(iter(engine.state.devices.values()))
    await grant(engine, "agent_controls")
    await limited(engine, "upsert_group", group_id="child", name="Updated")
    for action, payload in [
        ("assign_device", {"device_id": device.id, "group_id": "other"}),
        ("assign_device", {"device_id": device.id}),
        (
            "upsert_rule",
            {"rule_id": "outside", "name": "Take over", "kind": "internet", "groups": ["child"]},
        ),
        ("upsert_rule", {"name": "Wide", "kind": "internet", "networks": ["demo-family"]}),
        ("upsert_group", {"name": "New group"}),
    ]:
        with pytest.raises(FamilyError):
            await limited(engine, action, **payload)
    await limited(
        engine, "upsert_rule", rule_id="own", name="Own", kind="internet", groups=["child"]
    )
    with pytest.raises(FamilyError):
        await limited(
            engine, "upsert_rule", rule_id="own", name="Escape", kind="internet", groups=["other"]
        )
    engine.state.devices[device.id].group = "other"
    with pytest.raises(FamilyError):
        await limited(engine, "assign_device", device_id=device.id, group_id="child")
    await grant(engine, "agent_controls", all_groups=True)
    await limited(engine, "upsert_group", name="New group")
    assert len(engine.state.groups) == 3


async def test_exception_scope_and_filtered_status(household):
    engine, _, now, _ = household
    engine.state.groups["other"] = Group("other", "Private")
    engine.state.rules["shared"] = Rule("shared", "Shared", "internet", ["child", "other"])
    await command(
        engine,
        "allow_rule",
        rule_id="shared",
        group_id="other",
        duration_minutes=30,
        reason="private reason",
    )
    outside = next(iter(engine.state.exceptions))
    await grant(engine)
    with pytest.raises(FamilyError):
        await limited(
            engine,
            "edit_allowance",
            exception_id=outside,
            expires_at=(now[0] + timedelta(hours=1)).isoformat(),
        )
    await limited(engine, "allow_rule", rule_id="shared", group_id="child", duration_minutes=30)
    own = next(e.id for e in engine.state.exceptions.values() if e.group == "child")
    await limited(
        engine,
        "edit_allowance",
        exception_id=own,
        expires_at=(now[0] + timedelta(hours=1)).isoformat(),
    )
    data = status(engine.state, "delegate", now[0])
    assert "devices" not in data and "access_grants" not in data and "journal" not in data
    assert data["rules"][0]["groups"] == ["child"]
    assert not data["rules"][0]["whole_rule_control"]
    assert len(data["exceptions"]) == 1
    assert "private reason" not in str(data) and "admin-id" not in str(data)
    assert all("targets" not in change for change in data["changes"])
    assert all("actor" not in group for group in data["groups"])
    assert data["groups"][0]["state"] == "unknown"  # desired intent alone is not confirmation


async def test_grant_concurrency_atomic_save_and_import_revocation(household):
    engine, _, _, _ = household
    revision = engine.state.revision
    await grant(engine)
    assert engine.state.revision == revision and engine.state.access_revision == 1
    with pytest.raises(Conflict):
        await grant(engine, expected_access_revision=0)
    before = engine.state.to_dict()
    save = engine.save

    async def broken(_):
        raise OSError("storage unavailable")

    engine.save = broken
    with pytest.raises(OSError):
        await command(engine, "revoke_access_grant", user_id="delegate", confirm=True)
    assert engine.state.to_dict() == before
    engine.save = save
    config = engine.export()
    assert "access_grants" not in config
    preview = await command(engine, "preview_import", configuration=config)
    assert "revoked" in preview["note"]
    await command(
        engine,
        "apply_import",
        configuration=config,
        preview_hash=preview["preview_hash"],
        expected_revision=engine.state.revision,
    )
    assert engine.state.access_grants == {}


async def test_invalid_grants_and_deleted_group_pruning(household):
    engine, _, _, _ = household
    await grant(engine)
    for value in (None, [], {"delegate": None}, {"delegate": {"scope": []}}):
        data = engine.state.to_dict()
        data["access_grants"] = value
        with pytest.raises(FamilyError):
            State.from_dict(data)
    await command(engine, "delete_group", group_id="child", confirm=True)
    assert engine.state.access_grants["delegate"]["groups"] == []
    assert (await limited(engine, "access_status"))["groups"] == []


async def test_ha_grants_bind_active_nonadmin_identity_and_preserve_admin_routes(
    hass, entry, hass_admin_user, hass_read_only_user
):
    integration = entry

    async def call(action, user, **payload):
        return await hass.services.async_call(
            "family_network",
            action,
            {"entry_id": integration.entry_id, **payload},
            context=Context(user_id=user.id),
            blocking=True,
            return_response=True,
        )

    for uid in ("absent", hass_admin_user.id):
        with pytest.raises(ServiceValidationError):
            await call(
                "set_access_grant",
                hass_admin_user,
                user_id=uid,
                scope="watch_rules",
                groups=["demo-family"],
                confirm=True,
            )
    users = await call("access_users", hass_admin_user)
    assert hass_read_only_user.id in [u["id"] for u in users["users"]]
    await call(
        "set_access_grant",
        hass_admin_user,
        user_id=hass_read_only_user.id,
        scope="watch_rules",
        groups=["demo-family"],
        confirm=True,
    )
    result = await call("access_status", hass_read_only_user)
    assert result["scope"] == "watch_rules"
    assert "devices" not in result
    assert "coexistence" not in result
    await call("pause_internet", hass_read_only_user, group_id="demo-family", duration_minutes=30)
    for action in (
        "dashboard_data",
        "activity_history",
        "preview_recovery",
        "access_users",
        "list_access_grants",
    ):
        with pytest.raises(Unauthorized):
            await call(action, hass_read_only_user)
    with pytest.raises(ServiceValidationError):
        await call("upsert_group", hass_read_only_user, name="Not allowed")
    hass_read_only_user.is_active = False
    with pytest.raises(Unauthorized):
        await call("access_status", hass_read_only_user)
    await hass.async_block_till_done()


async def test_access_upgrade_backup_retains_old_state_once(hass, household):
    from custom_components.family_network.storage import HouseholdStorage

    engine, _, _, _ = household
    raw = deepcopy(engine.state.to_dict())
    raw.pop("access_grants")
    raw.pop("access_revision")
    storage = HouseholdStorage(hass, "access-test")
    await storage.store.async_save(raw)
    restored = await storage.load(engine.state)
    assert restored.access_grants == {}
    assert await storage.access_backup.async_load() == raw
    await storage.save(restored)
    await storage.load(engine.state)
    assert await storage.access_backup.async_load() == raw


async def test_watch_all_group_controls_and_whole_rule_switch(household):
    engine, _, _, _ = household
    engine.state.rules["own"] = Rule("own", "Own", "internet", ["child"])
    await grant(engine)
    for action in (
        "pause_internet",
        "extend_pause",
        "resume_internet",
        "allow_internet",
        "end_allowance",
    ):
        payload = {"group_id": "child"}
        if action in ("pause_internet", "extend_pause", "allow_internet"):
            payload["duration_minutes"] = 30
        await limited(engine, action, **payload)
    await limited(engine, "set_rule_enabled", rule_id="own", enabled=False)
    assert not engine.state.rules["own"].enabled


async def test_ha_rule_switch_honours_grant_scope_and_revocation(hass, entry):
    from homeassistant.auth.const import GROUP_ID_USER
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockUser

    delegate = MockUser(groups=[await hass.auth.async_get_group(GROUP_ID_USER)]).add_to_hass(hass)

    integration = entry
    engine = integration.runtime_data.engine
    await command(
        engine, "upsert_rule", rule_id="own", name="Own", kind="internet", groups=["demo-family"]
    )
    await command(
        engine,
        "set_access_grant",
        user_id=delegate.id,
        scope="watch_rules",
        groups=["demo-family"],
        confirm=True,
    )
    integration.runtime_data.async_set_updated_data(engine.state)
    await hass.async_block_till_done()
    entity = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), integration.entry_id)
        if e.domain == "switch"
    )
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": entity},
        context=Context(user_id=delegate.id),
        blocking=True,
    )
    assert not engine.state.rules["own"].enabled
    await command(engine, "revoke_access_grant", user_id=delegate.id, confirm=True)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": entity},
            context=Context(user_id=delegate.id),
            blocking=True,
        )
    assert not engine.state.rules["own"].enabled


async def test_revocation_is_checked_after_waiting_for_engine_lock(household):
    import asyncio

    engine, _, _, _ = household
    await grant(engine)
    async with engine.lock:
        task = asyncio.create_task(
            limited(engine, "pause_internet", group_id="child", duration_minutes=30)
        )
        await asyncio.sleep(0)
        engine.state.access_grants.clear()
    with pytest.raises(FamilyError):
        await task
    assert not engine.state.exceptions


def test_ha_action_metadata_remains_valid_yaml_and_includes_access_routes():
    from pathlib import Path

    import yaml

    from custom_components.family_network.actions import SCHEMAS

    metadata = yaml.safe_load(Path("custom_components/family_network/services.yaml").read_text())
    assert set(SCHEMAS) <= set(metadata)
    assert all("entry_id" in row["fields"] for row in metadata.values())
    assert metadata["set_access_grant"]["fields"]["scope"]["selector"]["select"]["options"] == [
        "read_only",
        "agent_controls",
        "watch_rules",
    ]
