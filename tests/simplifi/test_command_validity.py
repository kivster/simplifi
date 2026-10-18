"""Command delivery deadlines are separate from control expiry and durable retries."""

import asyncio
from copy import deepcopy
from datetime import timedelta

import pytest

from custom_components.simplifi.engine import Engine
from custom_components.simplifi.models import Conflict, SimpliFiError, State

from .conftest import command


@pytest.mark.parametrize("offset", [0, -1, -3600])
async def test_expired_new_request_changes_neither_intent_nor_policies(household, offset):
    engine, gateway, now, saved = household
    before = deepcopy(engine.state.to_dict())
    policies = deepcopy(gateway.policies)
    with pytest.raises(Conflict, match="command expired"):
        await command(
            engine,
            "pause_internet",
            group_id="child",
            duration_minutes=30,
            request_id="undelivered",
            request_expires_at=(now[0] + timedelta(seconds=offset)).isoformat(),
        )
    assert engine.state.to_dict() == before and gateway.policies == policies and not saved


@pytest.mark.parametrize("deadline", ["", "private://controller/key", "2026-10-13T20:31:00"])
async def test_bad_validity_is_redacted_and_timezone_is_required(household, deadline):
    engine, _, _, saved = household
    with pytest.raises(SimpliFiError, match="ISO timestamp with a timezone") as error:
        await command(engine, "resume_internet", group_id="child", request_expires_at=deadline)
    assert "private" not in str(error.value) and not saved


async def test_five_minute_bound_and_control_expiry_are_independent(household):
    engine, _, now, _ = household
    with pytest.raises(SimpliFiError, match="five minutes"):
        await command(
            engine,
            "pause_internet",
            group_id="child",
            duration_minutes=30,
            request_expires_at=(now[0] + timedelta(minutes=5, microseconds=1)).isoformat(),
        )
    deadline = (now[0] + timedelta(minutes=5)).isoformat()
    change = await command(
        engine, "pause_internet", group_id="child", duration_minutes=30, request_expires_at=deadline
    )
    assert change["request_expires_at"] == deadline
    pause = next(iter(engine.state.exceptions.values()))
    assert pause.expires_at == (now[0] + timedelta(minutes=30)).isoformat()
    now[0] += timedelta(minutes=6)
    await engine.refresh()
    assert next(iter(engine.state.exceptions.values())).active(now[0])


async def test_expiry_is_checked_after_waiting_for_the_engine_lock(household):
    engine, _, now, saved = household
    async with engine.lock:
        task = asyncio.create_task(
            command(
                engine,
                "pause_internet",
                group_id="child",
                duration_minutes=30,
                request_expires_at=(now[0] + timedelta(seconds=1)).isoformat(),
            )
        )
        await asyncio.sleep(0)
        now[0] += timedelta(seconds=2)
    with pytest.raises(Conflict, match="command expired"):
        await task
    assert not engine.state.exceptions and not saved


async def test_exact_saved_retry_after_reload_does_not_extend_or_reapply(household):
    engine, gateway, now, saved = household
    payload = {
        "group_id": "child",
        "duration_minutes": 30,
        "request_id": "original",
        "request_expires_at": (now[0] + timedelta(seconds=60)).isoformat(),
    }
    first = await command(engine, "pause_internet", **payload)
    now[0] += timedelta(hours=1)
    restored = Engine(State.from_dict(saved[-1]), gateway, engine.save, clock=engine.clock)
    before = deepcopy(restored.state.to_dict())
    assert await command(restored, "pause_internet", **payload) == first
    assert restored.state.to_dict() == before and len(saved) == 1
    with pytest.raises(Conflict, match="different change"):
        await command(
            restored,
            "pause_internet",
            **{**payload, "request_expires_at": (now[0] + timedelta(seconds=60)).isoformat()},
        )
    # Once a retained result is gone, the original deadline still prevents replay.
    restored.state.changes.clear()
    with pytest.raises(Conflict, match="command expired"):
        await command(restored, "pause_internet", **payload)
    assert len(saved) == 1


async def test_deadline_envelope_does_not_authenticate_or_bypass_revocation(household):
    from .test_access import grant

    engine, _, now, _ = household
    deadline = (now[0] + timedelta(seconds=60)).isoformat()
    data = {
        "group_id": "child",
        "duration_minutes": 30,
        "request_expires_at": deadline,
        "request_id": "delegate-request",
    }
    with pytest.raises(SimpliFiError, match="authenticated"):
        await engine.command("pause_internet", data, None)
    await grant(engine)
    await engine.command("pause_internet", data, "delegate")
    await command(engine, "revoke_access_grant", user_id="delegate", confirm=True)
    before = deepcopy(engine.state.to_dict())
    with pytest.raises(SimpliFiError, match="No active"):
        await engine.command("pause_internet", data, "delegate")
    assert engine.state.to_dict() == before
