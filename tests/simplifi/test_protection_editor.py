"""Profile edits preserve scope, reject stale reviews and retain uncertain writes."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized

from custom_components.simplifi.models import SimpliFiError
from custom_components.simplifi.protection_editor import ProtectionEditor, editable

from .test_protection import NETWORKS, NOW, PROFILE, reader


def editor(hass):
    source, api = reader()
    engine = SimpleNamespace(
        gateway=source.gateway, state=SimpleNamespace(management=True), clock=lambda: NOW
    )
    obj = ProtectionEditor(hass, "test", source, engine)
    rows = [deepcopy(PROFILE)]
    calls = []

    async def request(req):
        calls.append(req)
        if req.method == "put":
            assert req.path == "/content-filtering/profile"
            rows[0] = deepcopy(req.data)
            return {"data": [rows[0]]}
        return deepcopy(NETWORKS if req.path == "/rest/networkconf" else {"data": rows})

    api.request.side_effect = request
    return obj, rows, calls


async def test_preview_never_writes_and_apply_preserves_unknown_fields_scope_and_schedule(hass):
    obj, rows, calls = editor(hass)
    changes = {
        **editable(rows[0]),
        "safe_search": ["GOOGLE", "YOUTUBE"],
        "block_list": ["new.example"],
    }
    preview = await obj.preview("profile", changes, "admin")
    assert all(r.method == "get" for r in calls)
    assert "do-not-expose" not in str(preview)
    result = await obj.apply(
        preview["preview_token"], "admin", True, (NOW + timedelta(minutes=1)).isoformat()
    )
    assert result["status"] == "confirmed"
    assert rows[0] == {**PROFILE, **changes}
    assert len([r for r in calls if r.method == "put"]) == 1
    journal = await obj.store.async_load()
    assert journal["status"] == "confirmed" and "do-not-expose" not in str(journal)
    with pytest.raises(SimpliFiError, match="expired"):
        await obj.apply(
            preview["preview_token"], "admin", True, (NOW + timedelta(minutes=1)).isoformat()
        )


async def test_stale_review_does_not_overwrite_external_changes(hass):
    obj, rows, calls = editor(hass)
    p = await obj.preview("profile", {**editable(rows[0]), "enabled": False}, "admin")
    rows[0]["network_ids"].append("another-network")
    with pytest.raises(SimpliFiError, match="changed in UniFi"):
        await obj.apply(p["preview_token"], "admin", True, (NOW + timedelta(minutes=1)).isoformat())
    assert all(r.method == "get" for r in calls)


@pytest.mark.parametrize(
    "actor,confirm,deadline",
    [("other", True, 60), ("admin", False, 60), ("admin", True, -1), ("admin", True, 400)],
)
async def test_review_is_actor_bound_confirmed_and_time_bounded(hass, actor, confirm, deadline):
    obj, rows, calls = editor(hass)
    p = await obj.preview("profile", {**editable(rows[0]), "enabled": False}, "admin")
    with pytest.raises(SimpliFiError):
        await obj.apply(
            p["preview_token"], actor, confirm, (NOW + timedelta(seconds=deadline)).isoformat()
        )
    assert all(r.method == "get" for r in calls)


async def test_timeout_is_persisted_and_restart_readback_prevents_blind_retry(hass):
    obj, rows, calls = editor(hass)
    p = await obj.preview("profile", {**editable(rows[0]), "enabled": False}, "admin")
    orig = obj.reader._source().request.side_effect

    async def timeout(req):
        if req.method == "put":
            await orig(req)
            raise TimeoutError("secret body")
        return await orig(req)

    obj.reader._source().request.side_effect = timeout
    with pytest.raises(SimpliFiError, match="could not be confirmed"):
        await obj.apply(p["preview_token"], "admin", True, (NOW + timedelta(minutes=1)).isoformat())
    assert (await obj.store.async_load())["status"] == "uncertain"
    reopened = ProtectionEditor(hass, "test", obj.reader, obj.engine)
    await reopened.preview("profile", editable(rows[0]), "admin")
    assert (await reopened.store.async_load())["status"] == "confirmed"
    assert len([r for r in calls if r.method == "put"]) == 1


async def test_invalid_domains_and_scope_injection_rejected(hass):
    obj, rows, calls = editor(hass)
    for changes in [
        {**editable(rows[0]), "network_ids": []},
        {**editable(rows[0]), "block_list": ["https://example.com/path"]},
        {**editable(rows[0]), "categories": ["INVENTED"]},
    ]:
        with pytest.raises(SimpliFiError):
            await obj.preview("profile", changes, "admin")
    assert all(r.method == "get" for r in calls)


async def test_profile_services_reject_non_admin_even_with_access_grant(
    hass, entry, hass_read_only_user
):
    for service, data in [
        ("preview_content_filter", {"profile_id": "profile", "changes": {}}),
        (
            "apply_content_filter",
            {"preview_token": "token", "confirm": True, "request_expires_at": NOW.isoformat()},
        ),
    ]:
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                "simplifi",
                service,
                {"entry_id": entry.entry_id, **data},
                context=Context(user_id=hass_read_only_user.id),
                blocking=True,
                return_response=True,
            )
