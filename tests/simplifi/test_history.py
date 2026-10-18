"""Each retained run has an outcome; restart and cursor behavior never imply success."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.simplifi.history import RunHistory, page
from custom_components.simplifi.models import Conflict


def test_history_cursor_ignores_newer_insertions_and_purged_cursor_is_explicit():
    rows = [{"id": str(i), "outcome": "applied"} for i in range(5)]
    first = page(rows, limit=2)
    assert [r["id"] for r in first["items"]] == ["4", "3"]
    rows.append({"id": "new", "outcome": "failed"})
    assert [r["id"] for r in page(rows, before_id=first["next_cursor"], limit=2)["items"]] == [
        "2",
        "1",
    ]
    assert page(rows, outcome="failed")["items"][0]["id"] == "new"
    with pytest.raises(Conflict):
        page(rows, before_id="expired")


async def test_run_survives_restart_as_interrupted_and_retention_is_bounded(
    hass, household, monkeypatch
):
    engine, _, now, _ = household
    history = RunHistory(hass, "history-test")
    await history.load(engine.state)
    first = await history.start(engine.state, now[0])
    restored = RunHistory(hass, "history-test")
    await restored.load(engine.state)
    row = (await restored.read())["items"][0]
    assert row["id"] == first and row["outcome"] == "interrupted"
    monkeypatch.setattr("custom_components.simplifi.history.MAX_RUNS", 2)
    for i in range(3):
        key = await restored.start(engine.state, now[0] + timedelta(seconds=i))
        await restored.finish(key, engine.state, [{"action": "update"}], False, 42)
    rows = (await restored.read())["items"]
    assert len(rows) == 2 and all(r["outcome"] == "failed" for r in rows)
    assert rows[0]["writes"] == {"create": 0, "update": 1, "delete": 0}
    await restored.start(engine.state, now[0] + timedelta(days=31))
    assert (await restored.read())["retained"] == 1


async def test_logbook_attribution_deduplicates_outcomes_without_household_details(
    hass, household, monkeypatch
):
    engine, _, _, _ = household
    events = []
    monkeypatch.setattr(
        "custom_components.simplifi.history.async_log_entry",
        lambda *a, **kw: events.append((a, kw)),
    )
    history = RunHistory(hass, "logbook-test")
    await history.load(engine.state)
    change = {
        "id": "change",
        "action": "pause_internet",
        "outcome": "pending",
        "revision": 1,
        "actor": "user-id",
        "reason": "Private reason",
        "targets": {"mac": "private-mac"},
    }
    await history.observe_changes([change])
    await history.observe_changes([change])
    restored = RunHistory(hass, "logbook-test")
    await restored.load(engine.state)
    await restored.observe_changes([change])
    change["outcome"] = "applied"
    await restored.observe_changes([change])
    assert len(events) == 2
    assert all(e[1]["context"].user_id == "user-id" for e in events)
    assert "Private reason" not in str(events) and "private-mac" not in str(events)


async def test_cached_summary_links_exact_revision_without_rewriting_failed_attempt(
    hass, household, monkeypatch
):
    engine, _, now, _ = household
    history = RunHistory(hass, "summary-test")
    t = now[0]
    change = {
        "id": "c",
        "revision": 2,
        "outcome": "failed",
        "action": "pause_internet",
        "requested_at": t.isoformat(),
    }
    original = deepcopy(change)
    run = {
        "id": "good",
        "revision": 2,
        "confirmed_revision": 2,
        "unresolved": 0,
        "outcome": "applied",
        "started_at": (t + timedelta(minutes=2)).isoformat(),
        "finished_at": (t + timedelta(minutes=3)).isoformat(),
    }
    history.data["runs"] = [
        {**run, "id": "earlier", "finished_at": (t - timedelta(minutes=1)).isoformat()},
        run,
        {**run, "id": "other", "revision": 3, "confirmed_revision": 3},
    ]
    before = deepcopy(history.data)
    save = AsyncMock(side_effect=AssertionError("a read must not save"))
    monkeypatch.setattr(history.store, "async_save", save)
    result = (await history.summaries([change]))["c"]
    assert result["latest_confirmed"] and result["last_confirmed_at"] == run["finished_at"]
    assert result["latest"]["outcome"] == "applied" and result["revision"] == 2
    assert change == original and history.data == before
    save.assert_not_awaited()
    history.data["runs"].append({**run, "id": "new-failure", "outcome": "failed"})
    result = (await history.summaries([change]))["c"]
    assert not result["latest_confirmed"] and result["latest"]["outcome"] == "failed"
    assert result["last_confirmed_at"] == run["finished_at"]


@pytest.mark.parametrize(
    "extra",
    [
        {"confirmed_revision": 1},
        {"unresolved": 1},
        {"unresolved": None},
        {"outcome": "running", "finished_at": None},
        {"outcome": "interrupted"},
    ],
)
async def test_summary_requires_complete_matching_readback_metadata(hass, household, extra):
    _, _, now, _ = household
    history = RunHistory(hass, "summary-incomplete")
    change = {"id": "c", "revision": 2, "outcome": "failed", "requested_at": now[0].isoformat()}
    history.data["runs"] = [
        {
            "id": "run",
            "revision": 2,
            "confirmed_revision": 2,
            "unresolved": 0,
            "outcome": "applied",
            "started_at": now[0].isoformat(),
            "finished_at": now[0].isoformat(),
            **extra,
        }
    ]
    result = (await history.summaries([change]))["c"]
    assert not result["latest_confirmed"] and result["last_confirmed_at"] is None


async def test_summary_never_attaches_policy_runs_to_dns_grants_or_missing_history(hass, household):
    _, _, now, _ = household
    history = RunHistory(hass, "summary-separate")
    change = {
        "id": "policy",
        "revision": 1,
        "outcome": "failed",
        "requested_at": now[0].isoformat(),
    }
    result = await history.summaries(
        [
            change,
            {**change, "id": "dns", "dns_revision": 1},
            {**change, "id": "grant", "access_revision": 1},
            {**change, "id": "recovery", "outcome": "recovery_recorded"},
        ]
    )
    assert set(result) == {"policy"}
    assert result["policy"]["latest"] is None and not result["policy"]["latest_confirmed"]
