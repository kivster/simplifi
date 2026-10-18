"""Recovery binds a complete fresh read, durable operation evidence and authenticated review."""

from copy import deepcopy
from datetime import timedelta

import pytest

from custom_components.family_network.models import Conflict, FamilyError, Rule

from .conftest import command


async def lost_create(household, failure="create_after"):
    engine, gateway, now, saved = household
    engine.state.rules["r"] = Rule("r", "Restriction", "internet", ["child"])
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    gateway.failure = failure
    with pytest.raises(Conflict):
        await engine.refresh()
    return engine, gateway, now, saved


async def test_exact_lost_response_adopted_without_duplicate_create(household):
    engine, gateway, _, _ = await lost_create(household)
    preview = await command(engine, "preview_recovery")
    row = preview["operations"][0]
    assert row["candidate_id"] == "demo-policy-1"
    assert row["marked_candidates"] == row["exact_candidates"] == 1
    before = deepcopy(gateway.policies)
    await command(
        engine,
        "resolve_operation",
        operation_id=row["operation_id"],
        preview_hash=row["preview_hash"],
        decision="attach",
        confirm=True,
        reason="Exact request verified",
        request_id="resolve",
    )
    assert gateway.policies == before  # Resolution itself only records ownership.
    await engine.refresh()
    assert len(gateway.policies) == gateway.counter == 2  # Second device, no duplicate first.
    assert engine.state.sync_status == "applied"
    assert engine.state.journal[0]["resolved_by"] == "admin-id"


async def test_recovery_rejects_actor_revision_changed_policy_and_no_confirmation(household):
    engine, gateway, _, _ = await lost_create(household)
    row = (await command(engine, "preview_recovery"))["operations"][0]
    payload = dict(
        operation_id=row["operation_id"],
        preview_hash=row["preview_hash"],
        decision="attach",
        confirm=True,
    )
    with pytest.raises(Conflict):
        await engine.command("resolve_operation", payload, "other-admin", administrator=True)
    with pytest.raises(FamilyError):
        await command(engine, "resolve_operation", **{**payload, "confirm": False})
    gateway.policies["demo-policy-1"]["name"] = "changed outside HA"
    with pytest.raises(Conflict):
        await command(engine, "resolve_operation", **payload)
    updated = (await command(engine, "preview_recovery"))["operations"][0]
    assert updated["candidate_id"] is None and not updated["can_close_absent"]


async def test_name_alone_or_duplicate_marker_never_establishes_ownership(household):
    engine, gateway, _, _ = await lost_create(household)
    copy = deepcopy(gateway.policies["demo-policy-1"])
    gateway.policies["copy"] = {**copy, "id": "copy"}
    row = (await command(engine, "preview_recovery"))["operations"][0]
    assert row["candidate_id"] is None
    assert row["exact_candidates"] == 2
    gateway.policies.pop("copy")
    gateway.policies["demo-policy-1"].pop("description")
    row = (await command(engine, "preview_recovery"))["operations"][0]
    assert row["candidate_id"] is None


async def test_absence_requires_age_independent_finished_request_ack_and_reason(household):
    engine, gateway, now, _ = await lost_create(household, "create_before")
    row = (await command(engine, "preview_recovery"))["operations"][0]
    assert not row["can_close_absent"]
    now[0] += timedelta(minutes=3)
    row = (await command(engine, "preview_recovery"))["operations"][0]
    assert row["can_close_absent"]
    payload = dict(
        operation_id=row["operation_id"],
        preview_hash=row["preview_hash"],
        decision="confirm_absent",
        confirm=True,
    )
    for extra in [{}, {"request_finished": True}, {"reason": "Controller request checked"}]:
        with pytest.raises(FamilyError):
            await command(engine, "resolve_operation", **payload, **extra)
    await command(
        engine,
        "resolve_operation",
        **payload,
        request_finished=True,
        reason="Controller request finished without creation",
    )
    assert not gateway.policies
    await engine.refresh()
    assert len(gateway.policies) == 2


async def test_partial_recovery_reads_and_failed_persistence_cannot_adopt(household):
    engine, gateway, _, _ = await lost_create(household)
    gateway.failure = "list"
    with pytest.raises(FamilyError):
        await command(engine, "preview_recovery")
    row = (await command(engine, "preview_recovery"))["operations"][0]
    before = deepcopy(engine.state.to_dict())

    async def fail(state):
        raise OSError("disk full")

    engine.save = fail
    with pytest.raises(OSError):
        await command(
            engine,
            "resolve_operation",
            operation_id=row["operation_id"],
            preview_hash=row["preview_hash"],
            decision="attach",
            confirm=True,
        )
    assert engine.state.to_dict() == before


async def test_known_id_update_recovery_is_readback_only_and_external_drift_is_visible(household):
    engine, gateway, _, _ = household
    engine.state.rules["r"] = Rule("r", "Rule", "internet", ["child"])
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await engine.refresh()
    await command(engine, "set_rule_enabled", rule_id="r", enabled=False)
    gateway.failure = "update_after"
    with pytest.raises(Conflict):
        await engine.refresh()
    row = (await command(engine, "preview_recovery"))["operations"][0]
    assert row["action"] == "update" and not row["candidate_id"] and not row["can_close_absent"]
    await engine.refresh()
    assert not (await command(engine, "preview_recovery"))["operations"]
    key = next(iter(gateway.policies))
    gateway.policies[key]["name"] = "Externally changed"
    assert (await command(engine, "preview_recovery"))["drift"][0]["policy_id"] == key


async def test_recovery_replans_current_intent_and_rejects_prior_revision(household):
    engine, gateway, _, _ = await lost_create(household)
    row = (await command(engine, "preview_recovery"))["operations"][0]
    await command(engine, "set_rule_enabled", rule_id="r", enabled=False)
    with pytest.raises(Conflict):
        await command(
            engine,
            "resolve_operation",
            operation_id=row["operation_id"],
            preview_hash=row["preview_hash"],
            decision="attach",
            confirm=True,
        )
    row = (await command(engine, "preview_recovery"))["operations"][0]
    payload = dict(
        operation_id=row["operation_id"],
        preview_hash=row["preview_hash"],
        decision="attach",
        confirm=True,
        request_id="resolve-latest",
    )
    result = await command(engine, "resolve_operation", **payload)
    assert await command(engine, "resolve_operation", **payload) == result
    await engine.refresh()
    assert len(gateway.policies) == 2 and not any(p["enabled"] for p in gateway.policies.values())
    assert "demo-policy-1" in gateway.policies
