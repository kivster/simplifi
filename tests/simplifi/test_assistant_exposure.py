"""Use HA's real exposure policy, including automatic and explicit preferences."""

from copy import deepcopy

import pytest
from homeassistant.components.homeassistant import exposed_entities
from homeassistant.components.homeassistant.const import DATA_EXPOSED_ENTITIES
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component


async def rule_switch(hass, entry, user):
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.services.async_call(
        "simplifi",
        "upsert_rule",
        {
            "entry_id": entry.entry_id,
            "rule_id": "voice-default",
            "name": "Bedtime",
            "kind": "internet",
            "groups": ["demo-family"],
        },
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id(
        "switch", "simplifi", f"{entry.entry_id}:rule:voice-default"
    )
    assert entity_id and hass.states.get(entity_id) is not None
    return entity_id


@pytest.mark.parametrize("assistant", exposed_entities.KNOWN_ASSISTANTS)
async def test_new_rule_stays_unexposed_when_automatic_exposure_is_on(
    hass, entry, hass_admin_user, assistant
):
    entity_id = await rule_switch(hass, entry, hass_admin_user)
    hass.data[DATA_EXPOSED_ENTITIES].async_set_expose_new_entities(assistant, True)
    assert not exposed_entities.async_should_expose(hass, assistant, entity_id)
    assert hass.states.get(entity_id).state == "on"


@pytest.mark.parametrize("choice", [False, True])
async def test_explicit_assistant_choice_and_entity_identity_survive_reload(
    hass, entry, hass_admin_user, choice
):
    entity_id = await rule_switch(hass, entry, hass_admin_user)
    registry = er.async_get(hass)
    identity = registry.async_get(entity_id).unique_id
    for assistant in exposed_entities.KNOWN_ASSISTANTS:
        exposed_entities.async_expose_entity(hass, assistant, entity_id, choice)
    options = deepcopy(registry.async_get(entity_id).options)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(entity_id).unique_id == identity
    assert registry.async_get(entity_id).options == options
    for assistant in exposed_entities.KNOWN_ASSISTANTS:
        assert exposed_entities.async_should_expose(hass, assistant, entity_id) is choice


@pytest.mark.parametrize("assistant", exposed_entities.KNOWN_ASSISTANTS)
async def test_legacy_rule_without_a_saved_choice_gets_the_new_default(
    hass, entry, hass_admin_user, assistant
):
    entity_id = await rule_switch(hass, entry, hass_admin_user)
    registry = er.async_get(hass)
    registry.async_update_entity(entity_id, entity_category=None)
    assert assistant not in registry.async_get(entity_id).options
    hass.data[DATA_EXPOSED_ENTITIES].async_set_expose_new_entities(assistant, True)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert not exposed_entities.async_should_expose(hass, assistant, entity_id)


async def test_deliberate_exposure_does_not_authorize_an_anonymous_voice_control(
    hass, entry, hass_admin_user
):
    entity_id = await rule_switch(hass, entry, hass_admin_user)
    exposed_entities.async_expose_entity(hass, "conversation", entity_id, True)
    assert exposed_entities.async_should_expose(hass, "conversation", entity_id)
    before = entry.runtime_data.engine.state.to_dict()
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity_id}, blocking=True, context=Context()
        )
    assert entry.runtime_data.engine.state.to_dict() == before
