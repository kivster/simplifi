"""HACS handoff, credential migration and rejection of the retired installer."""

from copy import deepcopy

import pytest
from homeassistant.components import http
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers.storage import Store

from custom_components.simplifi.const import VERSION
from custom_components.simplifi.update_runtime import setup_updates

OLD_WRITES = [
    ("preview_update", {}),
    (
        "install_update",
        {
            "expected_update_revision": 0,
            "preview_hash": "old",
            "request_id": "old",
            "confirm": True,
        },
    ),
    (
        "set_update_schedule",
        {
            "expected_update_revision": 0,
            "enabled": True,
            "days": [6],
            "time": "00:00",
            "confirm": True,
        },
    ),
    ("recover_update", {"expected_update_revision": 0, "confirm": True}),
]


@pytest.mark.parametrize("action,payload", OLD_WRITES)
async def test_retired_installer_refuses_even_administrators(
    hass, entry, hass_admin_user, action, payload
):
    state = deepcopy(entry.runtime_data.engine.state.to_dict())
    with pytest.raises(ServiceValidationError, match="managed through HACS"):
        await hass.services.async_call(
            "simplifi",
            action,
            {"entry_id": entry.entry_id, **payload},
            context=Context(user_id=hass_admin_user.id),
            blocking=True,
            return_response=True,
        )
    assert entry.runtime_data.engine.state.to_dict() == state
    assert not entry.runtime_data.engine.gateway.policies
    assert not hasattr(entry.runtime_data, "poll_updates")


@pytest.mark.parametrize(
    "action,payload", OLD_WRITES + [("update_status", {}), ("check_updates", {})]
)
async def test_update_actions_still_require_admin(
    hass, entry, hass_read_only_user, action, payload
):
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "simplifi",
            action,
            {"entry_id": entry.entry_id, **payload},
            context=Context(user_id=hass_read_only_user.id),
            blocking=True,
            return_response=True,
        )


async def test_status_reports_handoff_without_inventing_release_availability(
    hass, entry, hass_admin_user
):
    before = deepcopy(entry.runtime_data.engine.state.to_dict())
    for action in ("update_status", "check_updates"):
        result = await hass.services.async_call(
            "simplifi",
            action,
            {"entry_id": entry.entry_id},
            context=Context(user_id=hass_admin_user.id),
            blocking=True,
            return_response=True,
        )
        assert result["installed"] == VERSION and result["provider"] == "hacs"
        assert result["check"]["available"] is None
        assert not result["hacs_loaded"] and not result["schedule"]["enabled"]
    assert entry.runtime_data.engine.state.to_dict() == before
    hass.config.components.add("hacs")
    assert entry.runtime_data.updates.status()["hacs_loaded"]


@pytest.mark.parametrize(
    "run",
    [{"status": "requested", "stage": "pull_wait"}, {"status": "failed", "stage": "attention"}],
)
async def test_migration_preserves_interrupted_record_without_resuming_it(hass, entry, run):
    record = {"run": run, "schedule": {"enabled": True}, "revision": 11}
    store = Store(hass, 1, f"simplifi.updates.{entry.entry_id}")
    await store.async_save(record)
    data = dict(entry.data)
    hass.config_entries.async_update_entry(
        entry,
        data={**data, "update_github_token": "old-test-credential", "api_key": "local-test-key"},
    )
    await setup_updates(hass, entry)
    assert entry.data == {**data, "api_key": "local-test-key"}
    assert await store.async_load() == record
    status = entry.runtime_data.updates.status()
    assert status["legacy_attention"] and not status["schedule"]["enabled"]
    assert "old-test-credential" not in str(status)
    assert "local-test-key" not in str(status)
    assert not hasattr(entry.runtime_data, "poll_updates")


async def test_invalid_previous_record_does_not_prevent_gateway_setup(hass, entry):
    store = Store(hass, 1, f"simplifi.updates.{entry.entry_id}")
    await store.async_save(["invalid"])
    await setup_updates(hass, entry)
    assert "could not be read" in entry.runtime_data.updates.status()["legacy_attention"]
    assert await store.async_load() == ["invalid"]
    assert entry.runtime_data.engine.state.last_observed


async def test_native_options_hands_off_without_a_credential_form(hass, entry, hass_admin_user):
    token = http.current_request.set({http.KEY_HASS_USER: hass_admin_user})
    try:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "updates"}
        )
        assert result["type"] == "abort" and result["reason"] == "updates_managed_by_hacs"
        assert "data_schema" not in result
    finally:
        http.current_request.reset(token)
