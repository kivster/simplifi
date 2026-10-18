"""Each retained run has an outcome; restart and cursor behavior never imply success."""

from datetime import timedelta

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
