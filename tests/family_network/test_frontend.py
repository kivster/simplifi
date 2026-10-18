"""Bundled resource delivery and safe migration through real HA collections."""

from copy import deepcopy
from pathlib import Path

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceYAMLCollection
from homeassistant.helpers import entity_registry as er

from custom_components.family_network.const import CARD_RESOURCE, CARD_URL
from custom_components.family_network.frontend import LEGACY_CARD_URL, async_register_resource

CARD_SOURCE = Path("custom_components/family_network/frontend/family-network-card.js").read_text()


async def test_card_is_served_from_package_but_source_is_not(hass, entry, hass_client):
    client = await hass_client()
    response = await client.get(CARD_RESOURCE)
    assert response.status == 200
    assert await response.text() == CARD_SOURCE
    for path in (
        "/family_network_static/__init__.py",
        "/family_network_static/data/mac-registrants.json.gz",
    ):
        response = await client.get(path)
        assert response.status == 404


async def test_resource_migration_preserves_identity_and_unrelated_resources(hass, entry):
    resources = hass.data[LOVELACE_DATA].resources
    for item in list(resources.async_items()):
        await resources.async_delete_item(item["id"])
    old = await resources.async_create_item(
        {"url": LEGACY_CARD_URL + "?v=0.17.0", "res_type": "module"}
    )
    await resources.async_create_item({"url": CARD_URL + "?v=old", "res_type": "module"})
    unrelated = await resources.async_create_item(
        {"url": "/local/other/card.js", "res_type": "module"}
    )
    remote = await resources.async_create_item(
        {"url": "https://example.com" + LEGACY_CARD_URL, "res_type": "module"}
    )
    await async_register_resource(hass)
    await async_register_resource(hass)
    items = resources.async_items()
    assert len(items) == 3
    assert unrelated in items and remote in items
    assert {"id": old["id"], "url": CARD_RESOURCE, "type": "module"} in items


async def test_yaml_resources_remain_user_managed(hass, entry):
    rows = [{"url": LEGACY_CARD_URL, "type": "module"}]
    hass.data[LOVELACE_DATA].resources = ResourceYAMLCollection(deepcopy(rows))
    await async_register_resource(hass)
    assert hass.data[LOVELACE_DATA].resources.async_items() == rows


async def test_reload_keeps_entities_state_and_one_resource(hass, entry):
    registry = er.async_get(hass)
    identities = {
        (e.entity_id, e.unique_id)
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    state = entry.runtime_data.engine.state
    groups = deepcopy(state.groups)
    binding = (state.controller, state.site, list(state.networks))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert {
        (e.entity_id, e.unique_id)
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    } == identities
    restored = entry.runtime_data.engine.state
    assert restored.groups == groups
    assert (restored.controller, restored.site, restored.networks) == binding
    matches = [
        r for r in hass.data[LOVELACE_DATA].resources.async_items() if r["url"] == CARD_RESOURCE
    ]
    assert len(matches) == 1
