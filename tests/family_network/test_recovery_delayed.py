"""A timed-out request can still complete after a later read sees the pre-image."""

from copy import deepcopy
from datetime import timedelta

import pytest

from custom_components.family_network.engine import Engine
from custom_components.family_network.models import Conflict, FamilyError, Rule, State

from .conftest import command


@pytest.mark.parametrize("action", ["update", "delete"])
async def test_old_readback_does_not_resolve_a_request_that_can_still_finish(
    household, monkeypatch, action
):
    engine, gateway, _, saved = household
    engine.state.rules["r"] = Rule("r", "Original restriction", "internet", ["child"])
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await engine.refresh()
    pending = []
    original = getattr(gateway, action)

    async def delayed(*args):
        pending.append(deepcopy(args))
        raise TimeoutError

    monkeypatch.setattr(gateway, action, delayed)
    if action == "update":
        await command(engine, "set_rule_enabled", rule_id="r", enabled=False)
    else:
        await command(engine, "delete_rule", rule_id="r")
    with pytest.raises(Conflict):
        await engine.refresh()
    before = deepcopy(gateway.policies)
    engine = Engine(State.from_dict(saved[-1]), gateway, engine.save, clock=engine.clock)
    # A newer request now wants the original restriction. The old server request
    # is still queued: a GET returning the pre-image is not a completion receipt.
    await command(
        engine,
        "upsert_rule",
        rule_id="r",
        name="Original restriction",
        kind="internet",
        groups=["child"],
    )
    with pytest.raises(Conflict):
        await engine.refresh()
    assert gateway.policies == before and len(pending) == 1
    assert engine.state.confirmed_revision != engine.state.revision
    assert any(j["status"] != "verified" for j in engine.state.journal)
    monkeypatch.setattr(gateway, action, original)
    await original(*pending[0])  # Original request finally completes.
    await engine.refresh()
    assert engine.state.sync_status == "applied"
    assert len(gateway.policies) == 2 and all(p["enabled"] for p in gateway.policies.values())


async def unfinished_request(household, monkeypatch, action):
    engine, gateway, now, saved = household
    engine.state.rules["r"] = Rule("r", "Restriction", "internet", ["child"])
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await engine.refresh()
    original = getattr(gateway, action)

    async def fail(*args):
        raise TimeoutError

    monkeypatch.setattr(gateway, action, fail)
    if action == "update":
        await command(engine, "set_rule_enabled", rule_id="r", enabled=False)
    else:
        await command(engine, "delete_rule", rule_id="r")
    with pytest.raises(Conflict):
        await engine.refresh()
    monkeypatch.setattr(gateway, action, original)
    engine = Engine(State.from_dict(saved[-1]), gateway, engine.save, clock=engine.clock)
    return engine, gateway, now, saved


@pytest.mark.parametrize("action", ["update", "delete"])
async def test_unapplied_recovery_requires_age_finished_ack_and_evidence(
    household, monkeypatch, action
):
    engine, gateway, now, _ = await unfinished_request(household, monkeypatch, action)
    row = (await command(engine, "preview_recovery"))["operations"][0]
    assert not row["can_close_not_applied"]
    now[0] += timedelta(minutes=3)
    row = (await command(engine, "preview_recovery"))["operations"][0]
    assert row["can_close_not_applied"] and not row["can_close_absent"]
    assert row["policy_id"] in gateway.policies
    payload = dict(
        operation_id=row["operation_id"],
        preview_hash=row["preview_hash"],
        decision="confirm_not_applied",
        confirm=True,
    )
    before = deepcopy(engine.state.to_dict())
    policies = deepcopy(gateway.policies)
    for extra in [{}, {"request_finished": True}, {"reason": "Checked request completion"}]:
        with pytest.raises(FamilyError):
            await command(engine, "resolve_operation", **payload, **extra)
        assert engine.state.to_dict() == before and gateway.policies == policies
    await command(
        engine,
        "resolve_operation",
        **payload,
        request_finished=True,
        reason="Controller request completion independently verified",
        request_id="resolve-known",
    )
    assert engine.state.revision == before["revision"] and gateway.policies == policies
    resolved = engine.state.journal[-1]
    assert resolved["outcome"] == "administrator_confirm_not_applied"
    assert resolved["resolved_by"] == "admin-id"
    await engine.refresh()
    assert engine.state.sync_status == "applied"
    if action == "update":
        assert len(gateway.policies) == 2 and not any(
            p["enabled"] for p in gateway.policies.values()
        )
    else:
        assert not gateway.policies


@pytest.mark.parametrize("action", ["update", "delete"])
async def test_unapplied_recovery_rejects_changed_actor_revision_or_controller(
    household, monkeypatch, action
):
    engine, gateway, now, _ = await unfinished_request(household, monkeypatch, action)
    now[0] += timedelta(minutes=3)
    row = (await command(engine, "preview_recovery"))["operations"][0]
    payload = dict(
        operation_id=row["operation_id"],
        preview_hash=row["preview_hash"],
        decision="confirm_not_applied",
        confirm=True,
        request_finished=True,
        reason="Checked original request",
    )
    with pytest.raises(Conflict):
        await engine.command("resolve_operation", payload, "other-admin", administrator=True)
    await command(engine, "upsert_group", group_id="child", name="Changed household")
    with pytest.raises(Conflict):
        await command(engine, "resolve_operation", **payload)
    row = (await command(engine, "preview_recovery"))["operations"][0]
    payload["preview_hash"] = row["preview_hash"]
    gateway.policies[row["policy_id"]]["name"] = "Edited outside Home Assistant"
    with pytest.raises(Conflict):
        await command(engine, "resolve_operation", **payload)
    row = (await command(engine, "preview_recovery"))["operations"][0]
    assert not row["can_close_not_applied"]
    with pytest.raises(FamilyError):
        await command(
            engine, "resolve_operation", **{**payload, "preview_hash": row["preview_hash"]}
        )


@pytest.mark.parametrize("action", ["update", "delete"])
async def test_unapplied_recovery_failed_save_keeps_request_unresolved(
    household, monkeypatch, action
):
    engine, gateway, now, _ = await unfinished_request(household, monkeypatch, action)
    now[0] += timedelta(minutes=3)
    row = (await command(engine, "preview_recovery"))["operations"][0]
    before = deepcopy(engine.state.to_dict())
    policies = deepcopy(gateway.policies)

    async def disk_full(state):
        raise OSError("disk full")

    engine.save = disk_full
    with pytest.raises(OSError):
        await command(
            engine,
            "resolve_operation",
            operation_id=row["operation_id"],
            preview_hash=row["preview_hash"],
            decision="confirm_not_applied",
            confirm=True,
            request_finished=True,
            reason="Checked request completion",
        )
    assert engine.state.to_dict() == before and gateway.policies == policies
