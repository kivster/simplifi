"""Saved timing evidence must survive expiry, cancellation, retries and reload."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.simplifi.models import Rule, State, Window
from custom_components.simplifi.timing_audit import capture

from .conftest import command


def timing(change):
    return change["details"]["timing"]


def setup(engine, action):
    engine.state.rules["r"] = Rule("r", "Bedtime", "internet", ["child"])
    engine.state.quarantine = True
    return (
        {}
        if "quarantine" in action
        else {"rule_id": "r"}
        if "rule" in action
        else {"group_id": "child"}
    )


@pytest.mark.parametrize(
    "action",
    ["pause_internet", "allow_internet", "suspend_rule", "allow_rule", "suspend_quarantine"],
)
@pytest.mark.parametrize("mode", ["duration_minutes", "expires_at", "indefinite", "default"])
async def test_initial_control_retains_exact_request_and_resolved_deadline(household, action, mode):
    engine, _, now, saved = household
    target = setup(engine, action)
    end = (now[0] + timedelta(minutes=30)).isoformat()
    value = {"duration_minutes": 30, "expires_at": end, "indefinite": True}.get(mode)
    change = await command(
        engine, action, **target, **({mode: value} if value is not None else {}), reason="pilot"
    )
    audit = timing(change)
    assert audit["timezone"] == "Europe/London"
    assert audit["request"] == {"mode": mode, **({"value": value} if value is not None else {})}
    row = audit["changes"][0]
    assert row["before"] is None
    assert row["after"]["expires_at"] == (
        end if mode in ("expires_at", "duration_minutes") else None
    )
    assert change["actor"] == "admin-id" and change["reason"] == "pilot"
    assert change["requested_at"] == now[0].isoformat()
    assert saved[-1]["changes"][-1] == change


@pytest.mark.parametrize("explicit", [False, True])
async def test_default_and_next_window_keep_each_independent_deadline(household, explicit):
    engine, _, _, _ = household
    for key, end in (("r1", "22:00"), ("r2", "23:00")):
        engine.state.rules[key] = Rule(
            key,
            key,
            "internet",
            ["child"],
            windows=[Window(key, key, list(range(7)), "20:00", end)],
        )
    engine.state.rules["always"] = Rule("always", "Always", "internet", ["child"])
    change = await command(
        engine,
        "allow_internet",
        group_id="child",
        **({"next_window_end": True} if explicit else {}),
    )
    audit = timing(change)
    assert audit["request"]["mode"] == ("next_window_end" if explicit else "default")
    rows = {r["after"]["captured_rules"][0]["id"]: r["after"] for r in audit["changes"]}
    assert rows["r1"]["expires_at"] == "2026-10-13T21:00:00+00:00"
    assert rows["r2"]["expires_at"] == "2026-10-13T22:00:00+00:00"
    assert rows["always"]["expires_at"] is None


@pytest.mark.parametrize(
    "start,extend,end",
    [
        ("pause_internet", "extend_pause", "resume_internet"),
        ("suspend_rule", "extend_rule_suspension", "resume_rule"),
        ("suspend_quarantine", "extend_quarantine_suspension", "resume_quarantine"),
    ],
)
async def test_extensions_use_original_deadline_and_removal_is_not_indefinite(
    household, start, extend, end
):
    engine, _, now, _ = household
    target = setup(engine, start)
    first = await command(engine, start, **target, duration_minutes=30)
    original = deepcopy(first)
    now[0] += timedelta(minutes=10)
    change = await command(engine, extend, **target, duration_minutes=15)
    row = timing(change)["changes"][0]
    assert timing(change)["request"] == {"mode": "extend_minutes", "value": 15}
    assert row["before"] == timing(first)["changes"][0]["after"]
    assert row["after"]["expires_at"] == "2026-10-13T21:15:00+00:00"
    ended = await command(engine, end, **target)
    assert timing(ended)["changes"][0] == {"id": row["id"], "before": row["after"], "after": None}
    assert engine.state.changes[0] == original
    assert timing(await command(engine, end, **target))["changes"] == []


async def test_edit_allowance_keeps_legacy_details_and_new_audit(household):
    engine, _, now, _ = household
    setup(engine, "allow_internet")
    first = await command(engine, "allow_internet", group_id="child", duration_minutes=30)
    row = timing(first)["changes"][0]
    end = (now[0] + timedelta(hours=1)).isoformat()
    changed = await command(engine, "edit_allowance", exception_id=row["id"], expires_at=end)
    assert changed["details"]["previous_deadline"] == row["after"]["expires_at"]
    assert changed["details"]["captured_rules"] == ["r"]
    assert timing(changed)["changes"][0]["before"] == row["after"]
    assert timing(changed)["changes"][0]["after"]["created_at"] == row["after"]["created_at"]
    ended = await command(engine, "end_allowance", group_id="child")
    assert timing(ended)["changes"][0]["after"] is None


@pytest.mark.parametrize(
    "action,payload",
    [
        ("delete_group", {"group_id": "child", "confirm": True}),
        ("delete_rule", {"rule_id": "r"}),
        ("set_rule_enabled", {"rule_id": "r", "enabled": False}),
    ],
)
async def test_implicit_clearing_retains_deleted_names(household, action, payload):
    engine, _, _, _ = household
    setup(engine, "allow_internet")
    first = await command(engine, "allow_internet", group_id="child", duration_minutes=30)
    row = timing(first)["changes"][0]
    changed = await command(engine, action, **payload)
    assert timing(changed)["request"] == {"mode": "implicit"}
    assert timing(changed)["changes"] == [{"id": row["id"], "before": row["after"], "after": None}]
    assert row["after"]["group_name"] == "Test family"
    assert row["after"]["captured_rules"] == [{"id": "r", "name": "Bedtime"}]


async def test_capture_pruning_and_quarantine_disable_are_audited(household):
    engine, _, _, _ = household
    setup(engine, "allow_internet")
    engine.state.rules["other"] = Rule("other", "Other", "internet", ["child"])
    await command(engine, "allow_internet", group_id="child", duration_minutes=30)
    change = await command(engine, "delete_rule", rule_id="r")
    row = timing(change)["changes"][0]
    assert len(row["before"]["captured_rules"]) == 2
    assert row["after"]["captured_rules"] == [{"id": "other", "name": "Other"}]
    assert row["after"]["expires_at"] == row["before"]["expires_at"]
    await command(engine, "suspend_quarantine")
    change = await command(engine, "set_quarantine", enabled=False, excluded_devices=[])
    assert timing(change)["changes"][0]["before"]["expires_at"] is None
    assert timing(change)["changes"][0]["after"] is None


async def test_atomic_save_replay_reload_and_expiry_preserve_original_evidence(household):
    engine, _, now, saved = household
    payload = {"group_id": "child", "duration_minutes": 30, "request_id": "same"}
    first = await command(engine, "pause_internet", **payload)
    assert State.from_dict(saved[-1]).changes[-1] == first
    now[0] += timedelta(hours=2)
    engine.state.timezone = "Pacific/Auckland"
    engine.state.groups["child"].name = "Renamed"
    assert await command(engine, "pause_internet", **payload) == first
    assert len(saved) == 1
    before = engine.state.to_dict()
    engine.save = AsyncMock(side_effect=OSError("disk full"))
    with pytest.raises(OSError):
        await command(engine, "pause_internet", group_id="child", duration_minutes=10)
    assert engine.state.to_dict() == before


async def test_grant_expiry_and_revocation_are_recorded_without_policy_sync(household):
    engine, _, now, _ = household
    end = (now[0] + timedelta(days=1)).isoformat()
    change = await command(
        engine,
        "set_access_grant",
        user_id="delegate",
        scope="read_only",
        groups=["child"],
        expires_at=end,
        confirm=True,
    )
    assert change["outcome"] == "access_saved" and change["access_revision"] == 1
    row = timing(change)["changes"][0]
    assert row["after"]["expires_at"] == end
    change = await command(engine, "revoke_access_grant", user_id="delegate", confirm=True)
    assert timing(change)["changes"][0] == {"id": "delegate", "before": row["after"], "after": None}


async def test_import_clear_and_unrelated_payload_never_copy_secrets_or_old_unknowns(household):
    engine, _, _, _ = household
    await command(engine, "pause_internet", group_id="child", indefinite=True)
    before = engine.state
    after = deepcopy(before)
    after.exceptions.clear()
    audit = capture(before, after, "apply_import", {"configuration": {"api_key": "secret"}})
    assert audit["request"]["mode"] == "implicit"
    assert audit["changes"][0]["after"] is None
    assert "secret" not in str(audit) and "api_key" not in str(audit)
    after.changes[0].pop("details")
    assert "details" not in State.from_dict(after.to_dict()).changes[0]
    assert capture(before, before, "sync_now", {}) is None


async def test_authenticated_history_keeps_saved_timing_after_reload_and_cancel(
    hass, entry, hass_admin_user, hass_read_only_user
):
    from homeassistant.exceptions import Unauthorized

    from custom_components.simplifi.presentation import dashboard_data

    from .test_change_history import read

    engine = entry.runtime_data.engine
    change = await engine.command(
        "pause_internet",
        {"group_id": "demo-family", "duration_minutes": 30, "request_id": "private"},
        hass_admin_user.id,
        administrator=True,
    )
    await command(engine, "resume_internet", group_id="demo-family")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    result = await read(hass, entry, hass_admin_user, kind="changes")
    saved = next(c for c in result["items"] if c["id"] == change["id"])
    assert timing(saved) == timing(change)
    assert saved["actor"] == hass_admin_user.name
    assert "request_id" not in saved and "digest" not in saved
    dashboard = await dashboard_data(hass, entry)
    assert timing(next(c for c in dashboard["changes"] if c["id"] == change["id"])) == timing(
        change
    )
    with pytest.raises(Unauthorized):
        await read(hass, entry, hass_read_only_user, kind="changes")
