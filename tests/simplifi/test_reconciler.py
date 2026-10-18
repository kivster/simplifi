"""Failure injection, ownership evidence, complete readback and latest-intent recovery."""

from copy import deepcopy
from datetime import timedelta

import pytest

from custom_components.simplifi.models import Conflict, SimpliFiError, State
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
    with pytest.raises(Conflict):
        await engine.refresh()
    assert gateway.policies == snapshot


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
