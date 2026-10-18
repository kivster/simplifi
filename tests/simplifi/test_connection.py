"""Native connection flows and interrupted two-store handoffs."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.simplifi.models import Group, SimpliFiError, State, uid
from custom_components.simplifi.storage import HouseholdStorage


@pytest.fixture
async def connection(hass):
    data = {
        "simulation": False,
        "controller": "https://old.local",
        "api_key": "private-old-key",
        "site": "old-site",
        "networks": ["old-network"],
        "timezone": "Europe/London",
        "verify_ssl": True,
        "external_zone": "external",
    }
    entry = MockConfigEntry(domain="simplifi", data=data, unique_id="https://old.local:old-site")
    entry.add_to_hass(hass)
    storage = HouseholdStorage(hass, entry.entry_id)
    state = State(data["controller"], data["site"], data["networks"])
    state.groups["child"] = Group("child", "Child")
    from custom_components.simplifi.dns_catalog import ensure_seeds

    ensure_seeds(state)
    await storage.save(state)
    return entry, storage, state


async def resources(gateway):
    gateway.networks = {
        "old-network": {"name": "Home", "zone": "internal"},
        "new-network": {"name": "Family", "zone": "internal"},
    }
    gateway.zones = [
        {"id": "external", "name": "External", "metadata": {"origin": "SYSTEM_DEFINED"}}
    ]


async def start(hass, entry, controller="https://old.local", key=""):
    result = await hass.config_entries.flow.async_init(
        "simplifi", context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    assert result["step_id"] == "reconfigure"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"controller": controller, "api_key": key, "verify_ssl": True}
    )


def mocks():
    return (
        patch("custom_components.simplifi.config_flow.request_actor", return_value="admin"),
        patch(
            "custom_components.simplifi.api.unifi.UniFiGateway.connect",
            return_value=[{"id": "old-site", "name": "Old"}, {"id": "new-site", "name": "New"}],
        ),
        patch(
            "custom_components.simplifi.api.unifi.UniFiGateway.refresh_resources",
            new=resources,
        ),
    )


async def test_native_key_rotation_preserves_owned_policies(hass, connection):
    entry, storage, state = connection
    state.management = True
    state.owned["policy"] = {"id": "owned"}
    await storage.save(state)
    actor, connect, read = mocks()
    with actor, connect, read, patch.object(hass.config_entries, "async_schedule_reload") as reload:
        result = await start(hass, entry, key="private-new-key")
        assert result["step_id"] == "connection_site"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"site": "old-site"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"networks": ["old-network"], "external_zone": "external", "timezone": "Europe/London"},
        )
        assert result["step_id"] == "connection_review"
        assert "private" not in str(result)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"confirm": True}
        )
        assert result["reason"] == "reconfigure_successful"
        assert entry.data["api_key"] == "private-new-key"
        assert await storage.store.async_load() == state.to_dict()
        assert await storage.binding_pending.async_load() is None
        reload.assert_called_once_with(entry.entry_id)


async def test_new_controller_needs_new_key_and_explicit_mapping(hass, connection):
    entry, storage, state = connection
    actor, connect, read = mocks()
    with actor, connect, read, patch.object(hass.config_entries, "async_schedule_reload"):
        result = await start(hass, entry, "https://new.local")
        assert result["errors"] == {"base": "setup_failed"}
        assert "new API key" in result["description_placeholders"]["error"]
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"controller": "https://new.local", "api_key": "new-key", "verify_ssl": True},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"site": "new-site"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "networks": ["new-network"],
                "external_zone": "external",
                "timezone": "America/New_York",
            },
        )
        assert result["step_id"] == "connection_mapping"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"network": "new-network"}
        )
        assert result["step_id"] == "connection_review"
        await hass.config_entries.flow.async_configure(result["flow_id"], {"confirm": True})
    assert entry.data["controller"] == "https://new.local"
    assert entry.unique_id == "https://new.local:new-site"
    assert (await storage.store.async_load())["controller"] == "https://old.local"
    assert "new-key" not in str(await storage.binding_pending.async_load())
    restored = await storage.load(
        State("https://new.local", "new-site", ["new-network"], "America/New_York"),
        entry.data["binding_token"],
    )
    assert restored.controller == "https://new.local" and restored.timezone == "America/New_York"
    assert restored.groups == state.groups
    assert not restored.management and not restored.owned
    assert restored.revision == state.revision + 1
    assert await storage.binding_backup.async_load() == state.to_dict()


async def test_binding_change_requires_cleanup_and_rechecks_concurrent_edits(hass, connection):
    entry, storage, state = connection
    state.management = True
    await storage.save(state)
    actor, connect, read = mocks()
    with actor, connect, read, patch.object(hass.config_entries, "async_schedule_reload") as reload:
        result = await start(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"site": "old-site"}
        )
        scope = {"networks": ["old-network"], "external_zone": "external", "timezone": "UTC"}
        result = await hass.config_entries.flow.async_configure(result["flow_id"], scope)
        assert result["step_id"] == "connection_scope" and result["errors"]
        state.management = False
        await storage.save(state)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], scope)
        assert result["step_id"] == "connection_review"
        state.dns_revision += 1
        await storage.save(state)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"confirm": True}
        )
        assert "Household settings changed" in result["description_placeholders"]["error"]
        reload.assert_not_called()
        assert entry.data["timezone"] == "Europe/London"


async def test_connection_review_cannot_change_admin(hass, connection):
    entry, _, _ = connection
    actor, connect, read = mocks()
    with actor, connect, read:
        result = await start(hass, entry)
        with patch(
            "custom_components.simplifi.config_flow.request_actor", return_value="other-admin"
        ):
            with pytest.raises(SimpliFiError, match="another administrator"):
                await hass.config_entries.flow.async_configure(
                    result["flow_id"], {"site": "old-site"}
                )


async def test_binding_handoff_is_once_only_and_cancelled_staging_is_ignored(hass, connection):
    entry, storage, state = connection
    proposed = deepcopy(state)
    proposed.networks = ["new-network"]
    proposed.revision += 1
    proposed.binding_token = uid()
    data = {**entry.data, "networks": proposed.networks, "binding_token": proposed.binding_token}
    await storage.stage_binding(state, proposed, data)
    # Crash/cancel before config-entry commit must leave the old household active.
    assert (await storage.load(state)).to_dict() == state.to_dict()
    # Crash after main-store activation but before transaction cleanup is replay safe.
    with patch.object(storage.binding_pending, "async_remove", side_effect=OSError("crash")):
        with pytest.raises(OSError):
            await storage.load(proposed, proposed.binding_token)
    edited = await storage.store.async_load()
    edited["groups"]["child"]["name"] = "Later edit"
    edited["revision"] += 1
    await storage.store.async_save(edited)
    with patch.object(
        storage.binding_pending, "async_remove", wraps=storage.binding_pending.async_remove
    ) as remove:
        recovered = await storage.load(proposed, proposed.binding_token)
        remove.assert_called_once()
    assert recovered.groups["child"].name == "Later edit"


async def test_binding_handoff_refuses_mismatched_token_or_late_changes(hass, connection):
    entry, storage, state = connection
    proposed = deepcopy(state)
    proposed.binding_token = uid()
    await storage.stage_binding(state, proposed, dict(entry.data))
    with pytest.raises(SimpliFiError, match="handoff"):
        await storage.load(state, uid())
    state.revision += 1
    await storage.save(state)
    with pytest.raises(SimpliFiError, match="handoff"):
        await storage.load(state, proposed.binding_token)
    assert (await storage.store.async_load())["binding_token"] is None
