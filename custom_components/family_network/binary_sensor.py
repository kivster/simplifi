"""Freshness and exception dependency are separate from policy confirmation."""

from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import STALE_SECONDS
from .entity import FamilyEntity
from .models import instant


class FamilyBinarySensor(FamilyEntity, BinarySensorEntity):
    @property
    def is_on(self):
        state = self.state_model
        now = self.coordinator.engine.clock()
        if self.key == "connected":
            return bool(
                state.inventory_complete
                and state.last_observed
                and now - instant(state.last_observed) < timedelta(seconds=STALE_SECONDS)
            )
        return bool(state.quarantine_paused(now) and state.quarantine_until) or any(
            e.kind in ("pause", "internet_allow", "suspension", "rule_allow")
            and e.active(now)
            and e.expires_at
            for e in state.exceptions.values()
        )


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            FamilyBinarySensor(entry.runtime_data, entry, "connected", "Connected"),
            FamilyBinarySensor(
                entry.runtime_data, entry, "expiry_dependency", "Exception expiry requires HA"
            ),
        ]
    )
