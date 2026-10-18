from custom_components.family_network.models import Rule

from .conftest import command


async def test_allowance_only_captures_rules_currently_blocking(household):
    engine, _, _, _ = household
    engine.state.rules["blocked"] = Rule("blocked", "Blocked", "internet", ["child"])
    engine.state.rules["lifted"] = Rule("lifted", "Already lifted", "internet", ["child"])
    await command(engine, "suspend_rule", rule_id="lifted", duration_minutes=60)
    await command(engine, "allow_internet", group_id="child", duration_minutes=30)
    allowance = next(e for e in engine.state.exceptions.values() if e.kind == "internet_allow")
    assert allowance.captured == ["blocked"]
    await command(engine, "resume_rule", rule_id="lifted")
    assert engine.status("child")["state"] == "scheduled_block"


async def test_deadline_edit_preserves_capture_identity_and_new_rule_block(household):
    from copy import deepcopy
    from datetime import timedelta

    from custom_components.family_network.models import Rule
    from custom_components.family_network.planner import lifted

    engine, gateway, now, _ = household
    engine.state.rules["original"] = Rule("original", "Bedtime", "internet", ["child"])
    await command(engine, "allow_internet", group_id="child", duration_minutes=30)
    before = deepcopy(next(iter(engine.state.exceptions.values())))
    engine.state.rules["new"] = Rule("new", "Homework", "internet", ["child"])
    end = (now[0] + timedelta(hours=2)).isoformat()
    result = await command(
        engine,
        "edit_allowance",
        exception_id=before.id,
        expires_at=end,
        reason="Finish homework",
        request_id="edit",
    )
    after = engine.state.exceptions[before.id]
    assert after.expires_at == end
    after.expires_at = before.expires_at
    assert after == before
    after.expires_at = end
    assert lifted(engine.state, "original", "child", now[0])
    assert not lifted(engine.state, "new", "child", now[0])
    assert engine.status("child")["state"] == "scheduled_block"
    assert result["details"]["previous_deadline"] == before.expires_at
    assert result["details"]["captured_rules"] == ["original"]
    revision = engine.state.revision
    await command(
        engine,
        "edit_allowance",
        exception_id=before.id,
        expires_at=end,
        reason="Finish homework",
        request_id="edit",
    )
    assert engine.state.revision == revision


async def test_allowance_deadline_edit_rejects_expiry_invalid_scope_and_stale_form(household):
    from datetime import timedelta

    import pytest

    from custom_components.family_network.models import Conflict, FamilyError, Rule

    engine, _, now, _ = household
    engine.state.rules["r"] = Rule("r", "Video", "category", ["child"], [4])
    await command(engine, "allow_rule", rule_id="r", group_id="child", duration_minutes=30)
    exc = next(iter(engine.state.exceptions.values()))
    for end in [
        now[0].isoformat(),
        (now[0] + timedelta(days=8)).isoformat(),
        "2026-10-14T21:00:00",
        "bad",
    ]:
        with pytest.raises((FamilyError, ValueError)):
            await command(engine, "edit_allowance", exception_id=exc.id, expires_at=end)
    with pytest.raises(Conflict):
        await command(
            engine,
            "edit_allowance",
            exception_id=exc.id,
            expires_at=(now[0] + timedelta(hours=1)).isoformat(),
            expected_revision=0,
        )
    now[0] += timedelta(hours=1)
    with pytest.raises(FamilyError, match="ended"):
        await command(
            engine,
            "edit_allowance",
            exception_id=exc.id,
            expires_at=(now[0] + timedelta(hours=1)).isoformat(),
        )
    await command(engine, "pause_internet", group_id="child", duration_minutes=30)
    pause = next(e for e in engine.state.exceptions.values() if e.kind == "pause")
    with pytest.raises(FamilyError):
        await command(
            engine,
            "edit_allowance",
            exception_id=pause.id,
            expires_at=(now[0] + timedelta(hours=1)).isoformat(),
        )
