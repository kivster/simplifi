"""Failure injection, ownership evidence, complete readback and latest-intent recovery."""

from copy import deepcopy
from datetime import timedelta

import pytest

from custom_components.simplifi.models import Conflict, Rule, SimpliFiError, State, Window
from custom_components.simplifi.planner import plan

from .conftest import command


async def enable_pause(engine):
    await command(engine, "pause_internet", group_id="child", duration_minutes=30)
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)


async def test_confirmed_pause_foreign_policies_untouched_and_stable_sync(household):
    engine, gateway, _, saved = household
    foreign = {"id": "foreign", "name": "SimpliFi pretending ownership", "enabled": True}
    gateway.policies["foreign"] = deepcopy(foreign)
    await enable_pause(engine)
    await engine.refresh()
    assert engine.state.confirmed_revision == engine.state.revision
    assert gateway.policies["foreign"] == foreign
    assert len(engine.state.owned) == 2
    journal_length = len(engine.state.journal)
    await engine.refresh()
    assert len(engine.state.journal) == journal_length
    # An external create is preceded by a persisted intent with no returned ID.
    assert any(
        j["action"] == "create" and j["status"] == "intent" and "returned_id" not in j
        for s in saved
        for j in s["journal"]
    )


@pytest.mark.parametrize("failure", ["create_before", "create_after"])
async def test_uncertain_create_never_duplicates_or_adopts_by_name(household, failure):
    engine, gateway, _, _ = household
    await enable_pause(engine)
    gateway.failure = failure
    with pytest.raises(Conflict):
        await engine.refresh()
    count = gateway.counter
    engine.state = State.from_dict(engine.state.to_dict())
    with pytest.raises(Conflict):
        await engine.refresh()
    assert gateway.counter == count
    assert engine.state.journal[0]["status"] == "uncertain"


async def test_external_edit_freezes_writer(household):
    engine, gateway, _, _ = household
    await enable_pause(engine)
    await engine.refresh()
    first = next(iter(engine.state.owned.values()))["id"]
    gateway.policies[first]["enabled"] = False
    snapshot = deepcopy(gateway.policies)
    with pytest.raises(Conflict, match=r"differing fields: enabled"):
        await engine.refresh()
    assert gateway.policies == snapshot
    assert "differing fields: enabled" in (engine.state.issue or "")


async def test_partial_read_never_mass_deletes(household):
    engine, gateway, _, _ = household
    await enable_pause(engine)
    await engine.refresh()
    snapshot = deepcopy(gateway.policies)
    gateway.failure = "list"
    await command(engine, "resume_internet", group_id="child")
    with pytest.raises(SimpliFiError):
        await engine.refresh()
    assert gateway.policies == snapshot
    failed = engine.state.changes[-1]
    assert failed["outcome"] == "failed"
    await command(engine, "sync_now")
    await engine.refresh()
    assert failed["outcome"] == "failed"  # Unrelated sync cannot relabel that request.


async def test_delete_timeout_resolves_by_readback(household):
    engine, gateway, _, _ = household
    await enable_pause(engine)
    await engine.refresh()
    await command(engine, "resume_internet", group_id="child")
    gateway.failure = "delete_after"
    with pytest.raises(Conflict):
        await engine.refresh()
    await engine.refresh()
    assert not engine.state.owned and not gateway.policies


async def test_deleted_owned_policy_is_recreated_from_latest_intent(household):
    engine, gateway, now, _ = household
    await enable_pause(engine)
    await engine.refresh()
    gateway.policies.clear()
    await engine.refresh()
    assert len(gateway.policies) == 2
    now[0] += timedelta(minutes=31)
    await engine.refresh()
    assert not gateway.policies


async def test_disable_keeps_then_explicit_cleanup_removes_only_owned(household):
    engine, gateway, _, _ = household
    await enable_pause(engine)
    await engine.refresh()
    gateway.policies["foreign"] = {"id": "foreign", "name": "Other policy"}
    await command(engine, "set_management", enabled=False)
    await engine.refresh()
    assert len(gateway.policies) == 3
    result = await command(engine, "cleanup_owned", confirm=True)
    assert result["remaining"] == 0 and set(gateway.policies) == {"foreign"}


async def test_policy_uses_network_and_mac_not_shared_zone_only(household):
    engine, gateway, now, _ = household
    await enable_pause(engine)
    desired = plan(
        engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0]
    )
    for body in desired.values():
        source = body["source"]["trafficFilter"]
        assert source["type"] == "NETWORK"
        assert source["networkFilter"]["networkIds"] == ["demo-family"]
        assert source["macAddressFilter"] in {d.mac for d in engine.state.devices.values()}
        assert body["destination"]["zoneId"] == gateway.external_zone
        assert body["ipProtocolScope"]["ipVersion"] == "IPV4_AND_IPV6"


def _set_action(policy):
    policy["action"] = {"type": "ALLOW"}


def _set_schedule(policy):
    policy["schedule"]["timeFilter"]["startTime"] = "21:00"


@pytest.mark.parametrize(
    "mutate,path,hidden",
    [
        (_set_action, "action.type", "ALLOW"),
        (_set_schedule, "schedule.timeFilter.startTime", "21:00"),
    ],
)
async def test_unifi_11_report_flow_is_not_drift_but_owned_edits_are(
    household, caplog, mutate, path, hidden
):
    engine, gateway, _, _ = household
    engine.state.rules["bedtime"] = Rule(
        "bedtime",
        "Weekend bedtime",
        "internet",
        groups=["child"],
        windows=[Window("weekend", "Weekend nights", [4, 5], "22:00", "08:00", overnight=True)],
    )
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await engine.refresh()
    assert engine.state.sync_status == "applied" and engine.state.owned
    owned = deepcopy(engine.state.owned)
    for value in (False, True):
        for policy in gateway.policies.values():
            policy["reportFlowEnabled"] = value
        live = deepcopy(gateway.policies)
        await engine.refresh()
        assert engine.state.sync_status == "applied" and engine.state.issue is None
        assert engine.state.owned == owned and gateway.policies == live
    policy_id = next(iter(gateway.policies))
    mutate(gateway.policies[policy_id])
    live = deepcopy(gateway.policies)
    caplog.set_level("WARNING")
    with pytest.raises(Conflict) as caught:
        await engine.refresh()
    assert f"differing fields: {path}" in str(caught.value)
    assert gateway.policies == live
    assert path in (engine.state.issue or "")
    assert hidden not in (engine.state.issue or "")
    assert "reportFlowEnabled" not in (engine.state.issue or "")
    assert path in caplog.text and hidden not in caplog.text
    drift = await command(engine, "preview_recovery")
    row = next(item for item in drift["drift"] if item["policy_id"] == policy_id)
    assert row["fields"] == [path]
    assert hidden not in row["message"] and "reportFlowEnabled" not in row["fields"]
    assert len(drift["drift"]) == 1


@pytest.mark.parametrize("report_flow", [False, True])
async def test_owned_update_preserves_report_flow_and_unknown_keys(household, caplog, report_flow):
    engine, gateway, _, _ = household
    engine.state.rules["bedtime"] = Rule(
        "bedtime",
        "Weekend bedtime",
        "internet",
        groups=["child"],
        windows=[Window("weekend", "Weekend nights", [4, 5], "22:00", "08:00", overnight=True)],
    )
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await engine.refresh()
    for policy in gateway.policies.values():
        policy["reportFlowEnabled"] = report_flow
        policy["futureFlag"] = "keep-me"
    sent = []
    update = gateway.update

    async def capture(policy_id, body):
        sent.append(deepcopy(body))
        return await update(policy_id, body)

    gateway.update = capture
    caplog.set_level("INFO")
    await engine.refresh()
    assert sent == [] and engine.state.sync_status == "applied" and engine.state.issue is None
    notes = [r for r in caplog.records if r.message.startswith("SimpliFi ignored non-owned")]
    warnings = [r for r in caplog.records if r.message.startswith("SimpliFi ignored unrecognized")]
    assert len(notes) == len(gateway.policies)
    assert len(warnings) == len(gateway.policies)
    assert all("futureFlag" in r.message and "keep-me" not in r.message for r in warnings)
    assert all("reportFlowEnabled" not in r.message for r in warnings)
    assert "keep-me" not in caplog.text
    assert engine.reconciler.unrecognized_policy_fields == ["futureFlag"]
    await command(engine, "set_rule_enabled", rule_id="bedtime", enabled=False)
    await engine.refresh()
    assert sent and engine.state.sync_status == "applied"
    for body in sent:
        assert body["reportFlowEnabled"] is report_flow and body["futureFlag"] == "keep-me"
        assert body["enabled"] is False
    for policy in gateway.policies.values():
        assert policy["reportFlowEnabled"] is report_flow and policy["futureFlag"] == "keep-me"
        assert policy["enabled"] is False
