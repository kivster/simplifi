"""Continuous rule evidence keeps scope, exceptions, unknown labels and clock days honest."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from custom_components.simplifi.models import ExceptionRecord, Group, Rule, Window
from custom_components.simplifi.presentation import dashboard_data
from custom_components.simplifi.rule_summary import labels, summary, target_labels


def continuous(household, *, kind="application", targets=None, windows=None):
    engine, gateway, now, _ = household
    engine.state.management = True
    engine.state.rules["r"] = Rule(
        "r",
        "Chosen restriction",
        kind,
        ["child"],
        targets if targets is not None else [123],
        windows or [],
    )
    return engine.state, gateway, now


def test_application_and_category_labels_preserve_zero_and_partly_unknown_targets(household):
    state, gateway, now = continuous(household, targets=[123, 456, 999])
    original = deepcopy(state.to_dict())
    row = summary(state, "child", now[0], True, labels(gateway))["rule_rows"][0]
    assert [(t["id"], t["name"], t["known"]) for t in row["targets"]] == [
        (123, "Demo chat", True),
        (456, "Demo game", True),
        (999, "Unknown application (ID 999)", False),
    ]
    assert row["mode"] == "always_on" and row["state"] == "restricted"
    state.rules["r"].kind, state.rules["r"].targets = "category", [0, 999]
    row = summary(state, "child", now[0], True, labels(gateway))["rule_rows"][0]
    assert row["targets"][0] == {"id": 0, "name": "Messaging (demo)", "known": True}
    assert row["targets"][1]["name"] == "Unknown category (ID 999)"
    state.rules["r"].kind, state.rules["r"].targets = "application", [123, 456, 999]
    assert state.to_dict() == original


@pytest.mark.parametrize("name", [None, "", "   ", 0])
def test_unusable_catalogue_name_is_explicitly_unknown(name):
    rule = Rule("r", "Restriction", "application", ["child"], [0])
    assert target_labels(rule, {"application": {0: name}}) == [
        {"id": 0, "name": "Unknown application (ID 0)", "known": False}
    ]


def test_domains_and_internet_do_not_depend_on_dpi_names():
    assert (
        target_labels(Rule("r", "Sites", "domain", ["child"], ["example.com"]), {})[0]["name"]
        == "example.com"
    )
    assert target_labels(Rule("r", "Internet", "internet", ["child"]), {}) == [
        {"id": None, "name": "All internet", "known": True}
    ]


def test_network_scope_reports_partial_coverage_without_person_controls(household):
    state, gateway, now = continuous(household, kind="internet", targets=[])
    state.networks.append("other")
    list(state.devices.values())[1].network = "other"
    rule = state.rules["r"]
    rule.groups, rule.networks = [], ["demo-family"]
    row = summary(state, "child", now[0], True, labels(gateway))["rule_rows"][0]
    assert row["state"] == "partial" and row["label"] == "Some devices restricted"
    assert row["covered_devices"] == 1 and row["devices"] == 2
    assert row["network_scope"] and not row["person_control"]
    state.groups["other"] = Group("other", "Other")
    assert not summary(state, "other", now[0], True, labels(gateway))["rule_rows"]


@pytest.mark.parametrize("confirmed,expected", [(True, "allowed"), (False, "unknown")])
def test_suspension_is_current_intent_until_confirmed_and_expiry_returns_rule(
    household, confirmed, expected
):
    state, gateway, now = continuous(household)
    state.exceptions["e"] = ExceptionRecord(
        "e",
        "suspension",
        "child",
        "r",
        ["r"],
        now[0].isoformat(),
        (now[0] + timedelta(minutes=1)).isoformat(),
        "actor",
        "private reason",
    )
    row = summary(state, "child", now[0], confirmed, labels(gateway))["rule_rows"][0]
    assert row["state"] == expected and row["lifted"]
    assert row["label"] == ("Temporarily lifted" if confirmed else "Allowance unconfirmed")
    assert "private reason" not in str(row) and "actor" not in row
    row = summary(state, "child", now[0] + timedelta(minutes=2), True, labels(gateway))[
        "rule_rows"
    ][0]
    assert row["state"] == "restricted" and not row["lifted"]


@pytest.mark.parametrize(
    "condition,label",
    [
        ("disabled", "Disabled"),
        ("management_off", "Saved · management off"),
        ("archived", "Archived person"),
        ("no_devices", "No managed devices"),
        ("stale", "Rule unconfirmed"),
    ],
)
def test_disabled_unmanaged_archived_and_stale_are_not_claimed_active(household, condition, label):
    state, gateway, now = continuous(household, kind="internet", targets=[])
    confirmed = True
    if condition == "disabled":
        state.rules["r"].enabled = False
    elif condition == "management_off":
        state.management = False
    elif condition == "archived":
        state.groups["child"].archived = True
    elif condition == "no_devices":
        state.devices.clear()
    elif condition == "stale":
        confirmed = False
        state.last_observed = (now[0] - timedelta(minutes=3)).isoformat()
    result = summary(state, "child", now[0], confirmed, labels(gateway))
    assert result["rule_rows"][0]["label"] == label
    if condition in ("disabled", "archived", "no_devices"):
        assert not result["always_on_internet"]
    if condition == "stale":
        assert not result["rule_rows"][0]["coverage_fresh"]


@pytest.mark.parametrize(
    "stamp,hours", [("2026-03-29T12:00:00+00:00", 23), ("2026-10-25T12:00:00+00:00", 25)]
)
async def test_all_day_and_continuous_rules_leave_clock_timeline_but_keep_timed_windows(
    hass, entry, stamp, hours
):
    engine = entry.runtime_data.engine
    now = datetime.fromisoformat(stamp)
    engine.clock = lambda: now
    for device in engine.state.devices.values():
        device.group = "demo-family"
    all_day = Window("day", "Sunday all day", [6], all_day=True)
    night = Window("night", "Night", list(range(7)), "21:00", "07:00", overnight=True)
    engine.state.rules = {
        "always": Rule("always", "Continuous", "application", ["demo-family"], [123]),
        "day": Rule("day", "Day", "category", ["demo-family"], [0], [all_day]),
        "night": Rule("night", "Bedtime", "internet", ["demo-family"], windows=[night]),
    }
    before = deepcopy(engine.state.to_dict())
    data = await dashboard_data(hass, entry)
    group = data["groups"][0]
    assert {r["rule_id"] for r in group["rule_rows"]} == {"always", "day"}
    assert {r["rule_id"] for r in group["timeline"]} == {"night"}
    a, b = map(datetime.fromisoformat, (data["day_start"], data["day_end"]))
    assert (b - a).total_seconds() == hours * 3600
    assert engine.state.to_dict() == before


def test_mixed_rule_shows_all_day_today_once_and_selected_days_only(household):
    state, gateway, now = continuous(
        household,
        windows=[
            Window("d", "All day", [now_day := 1], all_day=True),
            Window("t", "Timed", [1], "09:00", "10:00"),
        ],
    )
    assert now[0].weekday() == now_day
    rows = summary(state, "child", now[0], True, labels(gateway))["rule_rows"]
    assert len(rows) == 1 and rows[0]["mode"] == "all_day_today"
    assert not summary(state, "child", now[0] + timedelta(days=1), True, labels(gateway))[
        "rule_rows"
    ]
    assert not summary(state, "child", now[0], True, labels(gateway), visible_rules=set())[
        "rule_rows"
    ]


async def test_scoped_watch_summary_preserves_labels_and_omits_other_people_and_inventory(
    household,
):
    engine, _, now, _ = household
    engine.state.groups["other"] = Group("other", "Private other person")
    engine.state.rules = {
        "own": Rule("own", "Own chat", "application", ["child"], [123]),
        "hidden": Rule("hidden", "Private other restriction", "application", ["other"], [456]),
    }
    await engine.command(
        "set_access_grant",
        {"user_id": "delegate", "scope": "watch_rules", "groups": ["child"], "confirm": True},
        "admin",
        administrator=True,
    )
    before = deepcopy(engine.state.to_dict())
    view = await engine.command("access_status", {}, "delegate")
    assert len(view["groups"]) == 1
    row = view["groups"][0]["rule_rows"][0]
    assert row["rule_id"] == "own" and row["targets"][0]["name"] == "Demo chat"
    assert view["rules"][0]["target_names"] == ["Demo chat"]
    assert "devices" not in view and "Private other" not in str(view)
    assert all(device.id not in str(row) for device in engine.state.devices.values())
    assert engine.state.to_dict() == before
