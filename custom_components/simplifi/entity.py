"""Stable entity identities and discovery-driven entity additions."""

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class SimpliFiEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key, name):
        super().__init__(coordinator)
        self.entry = entry
        self.key = key
        self._attr_unique_id = f"{entry.entry_id}:{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="SimpliFi simulator" if entry.data["simulation"] else "SimpliFi",
            manufacturer="SimpliFi",
            model="Native HA integration",
        )

    @property
    def state_model(self):
        return self.coordinator.engine.state

    @property
    def name(self):
        if self.key.startswith("group:"):
            _, group_id, field = self.key.split(":")
            group = self.state_model.groups.get(group_id)
            if group:
                return f"{group.name} {field.replace('_', ' ')}"
        if self.key.startswith("rule:"):
            rule = self.state_model.rules.get(self.key.removeprefix("rule:"))
            if rule:
                return rule.name
        return self._attr_name


def dynamic_setup(coordinator, entry, async_add_entities, factory):
    known = set()

    def update():
        entities = []
        for key, name, entity_type in factory(coordinator.engine.state):
            if key not in known:
                known.add(key)
                entities.append(entity_type(coordinator, entry, key, name))
        if entities:
            async_add_entities(entities)

    update()
    entry.async_on_unload(coordinator.async_add_listener(update))
