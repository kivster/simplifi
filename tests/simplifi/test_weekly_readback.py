"""Controller weekday ordering must not turn a saved schedule into ownership drift."""

from copy import deepcopy

import pytest

from custom_components.simplifi.models import Conflict, Rule, State, Window
from custom_components.simplifi.planner import policy_fingerprint, policy_matches

from .conftest import command


async def weekend_rule(engine):
    engine.state.rules["bedtime"] = Rule(
        "bedtime",
        "Weekend bedtime",
        "internet",
        groups=["child"],
        windows=[Window("weekend", "Weekend nights", [4, 5], "22:00", "08:00", overnight=True)],
    )
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)


async def test_sunday_first_readback_confirms_and_never_rewrites(household, monkeypatch):
    engine, gateway, _, _ = household
    await weekend_rule(engine)
    create = gateway.create

    async def controller_create(body):
        identity = await create(body)
        days = gateway.policies[identity]["schedule"]["repeatOnDays"]
        if "SUNDAY" in days:
            days.remove("SUNDAY")
            days.insert(0, "SUNDAY")
        return identity

    monkeypatch.setattr(gateway, "create", controller_create)
    await engine.refresh()
    assert engine.state.sync_status == "applied" and engine.configuration_confirmed()
    assert len(gateway.policies) == 4
    policies = deepcopy(gateway.policies)
    receipt_count = len(engine.state.journal)
    # Reload the durable raw fingerprints and receipts without rewriting them.
    engine.state = State.from_dict(engine.state.to_dict())
    await engine.refresh()
    assert engine.configuration_confirmed()
    assert gateway.policies == policies and gateway.counter == 4
    assert len(engine.state.journal) == receipt_count


async def test_recorded_create_identity_recovers_without_duplicate(household):
    engine, gateway, _, _ = household
    await weekend_rule(engine)
    await engine.refresh()
    operation = engine.state.journal[-1]
    operation["status"] = "intent"
    engine.state.owned.pop(operation["key"])
    current = gateway.policies[operation["returned_id"]]
    current["schedule"]["repeatOnDays"].reverse()
    receipts = deepcopy(engine.state.journal)
    engine.state = State.from_dict(engine.state.to_dict())
    await engine.refresh()
    assert engine.configuration_confirmed() and gateway.counter == 4
    assert all(j["status"] == "verified" for j in engine.state.journal)
    assert [j["fingerprint"] for j in engine.state.journal] == [j["fingerprint"] for j in receipts]


async def test_lost_response_recovery_requires_complete_equivalent_body(household):
    engine, gateway, _, _ = household
    await weekend_rule(engine)
    gateway.failure = "create_after"
    with pytest.raises(Conflict):
        await engine.refresh()
    current = next(iter(gateway.policies.values()))
    current["schedule"]["repeatOnDays"].reverse()
    row = (await command(engine, "preview_recovery"))["operations"][0]
    assert row["candidate_id"] == current["id"] and row["exact_candidates"] == 1
    current["schedule"]["timeFilter"]["startTime"] = "21:00"
    changed = (await command(engine, "preview_recovery"))["operations"][0]
    assert changed["candidate_id"] is None and changed["exact_candidates"] == 0
    assert changed["marked_candidates"] == 1 and gateway.counter == 1


def requested_policy():
    return {
        "enabled": True,
        "source": {"zoneId": "home", "macAddressFilter": "02:00:00:00:00:01"},
        "destination": {"zoneId": "internet"},
        "schedule": {
            "mode": "EVERY_WEEK",
            "repeatOnDays": ["SATURDAY", "SUNDAY"],
            "timeFilter": {"startTime": "00:00", "stopTime": "08:00"},
        },
        "description": "simplifi operation recorded-id",
    }


def test_weekday_equivalence_does_not_change_raw_receipts_or_input():
    recorded = requested_policy()
    actual = deepcopy(recorded)
    actual["schedule"]["repeatOnDays"].reverse()
    assert policy_fingerprint(actual) != policy_fingerprint(recorded)
    assert policy_matches(actual, recorded, policy_fingerprint(recorded))
    assert recorded["schedule"]["repeatOnDays"] == ["SATURDAY", "SUNDAY"]
    assert actual["schedule"]["repeatOnDays"] == ["SUNDAY", "SATURDAY"]
    assert not policy_matches(actual, recorded, "wrong receipt")
    changed = deepcopy(recorded)
    changed["description"] = "other operation"
    assert not policy_matches(actual, changed, policy_fingerprint(recorded))


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", False),
        ("source", {"zoneId": "other", "macAddressFilter": "02:00:00:00:00:01"}),
        ("source", {"zoneId": "home", "macAddressFilter": "02:00:00:00:00:02"}),
        ("destination", {"zoneId": "other"}),
        ("description", "other operation"),
        ("unexpected", [2, 1]),
    ],
)
def test_other_policy_fields_remain_strict(field, value):
    recorded = requested_policy()
    actual = deepcopy(recorded)
    actual["schedule"]["repeatOnDays"].reverse()
    actual[field] = value
    assert not policy_matches(actual, recorded, policy_fingerprint(recorded))


@pytest.mark.parametrize(
    "field,value",
    [
        ("timeFilter", {"startTime": "00:00", "stopTime": "09:00"}),
        ("repeatOnDays", ["FRIDAY", "SATURDAY"]),
        ("repeatOnDays", ["SUNDAY", "SATURDAY", "SATURDAY"]),
        ("mode", "EVERY_DAY"),
        ("unexpected", True),
    ],
)
def test_other_schedule_changes_remain_strict(field, value):
    recorded = requested_policy()
    actual = deepcopy(recorded)
    actual["schedule"]["repeatOnDays"].reverse()
    actual["schedule"][field] = value
    assert not policy_matches(actual, recorded, policy_fingerprint(recorded))
