"""A later sync only explains the matching saved change, never an unrelated one."""

from copy import deepcopy
from datetime import timedelta

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized

from custom_components.family_network.history import RunHistory
from custom_components.family_network.models import Conflict

from .conftest import command


async def read(hass, entry, user, **data):
    return await hass.services.async_call(
        "family_network",
        "activity_history",
        {"entry_id": entry.entry_id, **data},
        context=Context(user_id=user.id),
        blocking=True,
        return_response=True,
    )


async def test_real_failed_change_links_its_later_sync_and_retains_original_result(
    hass, entry, hass_admin_user, monkeypatch
):
    coordinator = entry.runtime_data
    engine = coordinator.engine
    await command(engine, "set_management", enabled=True)
    await coordinator.async_refresh()
    change = await engine.command(
        "upsert_group",
        {"name": "Test group", "request_id": "private-request"},
        hass_admin_user.id,
        administrator=True,
    )
    engine.gateway.failure = "inventory"
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await command(engine, "upsert_group", name="Unrelated later change")
    await coordinator.async_refresh()
    before = deepcopy(engine.state.to_dict())

    async def forbidden():
        raise AssertionError("Reading history must not start a gateway sync")

    monkeypatch.setattr(engine, "refresh", forbidden)
    result = await read(hass, entry, hass_admin_user, kind="sync", change_id=change["id"])
    assert [r["outcome"] for r in result["items"]] == ["applied", "failed"]
    assert {r["revision"] for r in result["items"]} == {change["revision"]}
    assert result["change"]["outcome"] == "failed"
    assert result["change"]["actor"] == hass_admin_user.name
    assert "digest" not in result["change"] and "request_id" not in result["change"]
    assert result["latest"]["id"] == result["items"][0]["id"]
    assert engine.state.to_dict() == before


async def test_change_history_summary_ignores_filter_and_cursor_but_not_revision(hass, household):
    engine, _, now, _ = household
    history = RunHistory(hass, "linked-history")
    await history.load(engine.state)
    history.data["runs"] = [
        {
            "id": str(i),
            "revision": 4 if i < 4 else 5,
            "started_at": (now[0] + timedelta(seconds=i)).isoformat(),
            "outcome": "failed" if i < 2 else "applied",
        }
        for i in range(5)
    ]
    change = {"id": "c", "revision": 4, "requested_at": now[0].isoformat(), "outcome": "failed"}
    result = await history.for_change(change, limit=1, outcome="failed")
    assert result["items"][0]["id"] == "1" and result["next_cursor"] == "1"
    assert result["latest"]["id"] == "3" and result["retained"] == 4
    older = await history.for_change(change, limit=1, outcome="failed", before_id="1")
    assert older["items"][0]["id"] == "0" and older["next_cursor"] is None
    with pytest.raises(Conflict, match="cursor expired"):
        await history.for_change(change, before_id="4")
    assert change["outcome"] == "failed"


async def test_change_started_during_sync_is_matched_by_finished_revision(hass, household):
    engine, _, now, _ = household
    history = RunHistory(hass, "concurrent-history")
    await history.load(engine.state)
    history.data["runs"] = [
        {
            "id": "r",
            "started_revision": 1,
            "revision": 2,
            "outcome": "applied",
            "started_at": now[0].isoformat(),
            "finished_at": (now[0] + timedelta(seconds=2)).isoformat(),
        }
    ]
    change = {"id": "c", "revision": 2, "requested_at": (now[0] + timedelta(seconds=1)).isoformat()}
    assert (await history.for_change(change))["latest"]["id"] == "r"
    # An old run with a timestamp before the saved change cannot prove recovery.
    change["requested_at"] = (now[0] + timedelta(seconds=3)).isoformat()
    result = await history.for_change(change)
    assert result["latest"] is None and result["retained"] == 0 and result["items"] == []


@pytest.mark.parametrize(
    "action,payload",
    [
        ("check_dns", {}),
        (
            "set_access_grant",
            {
                "user_id": "delegate",
                "scope": "read_only",
                "groups": ["demo-family"],
                "confirm": True,
            },
        ),
    ],
)
async def test_dns_and_access_records_cannot_borrow_policy_sync_success(
    hass, entry, hass_admin_user, action, payload
):
    engine = entry.runtime_data.engine
    change = await command(engine, action, **payload)
    await entry.runtime_data.async_refresh()
    with pytest.raises(ServiceValidationError, match="does not have policy sync results"):
        await read(hass, entry, hass_admin_user, kind="sync", change_id=change["id"])


async def test_missing_change_and_wrong_history_kind_are_explicit(hass, entry, hass_admin_user):
    with pytest.raises(ServiceValidationError, match="no longer retained"):
        await read(hass, entry, hass_admin_user, kind="sync", change_id="missing")
    with pytest.raises(ServiceValidationError, match="Choose sync history"):
        await read(hass, entry, hass_admin_user, kind="changes", change_id="missing")


async def test_linked_change_still_requires_active_administrator(hass, entry, hass_read_only_user):
    with pytest.raises(Unauthorized):
        await read(hass, entry, hass_read_only_user, kind="sync", change_id="private-change")
