"""Rule intent switches reuse the same backend authenticated admission path."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import ServiceValidationError

from .entity import FamilyEntity, dynamic_setup
from .models import FamilyError
from .permissions import admitted_user


class FamilyRuleSwitch(FamilyEntity, SwitchEntity):
    @property
    def is_on(self):
        rule = self.state_model.rules.get(self.key.removeprefix("rule:"))
        return rule.enabled if rule else None

    async def _set(self, enabled):
        user = await admitted_user(self.hass, self._context.user_id, self.coordinator.engine)
        try:
            await self.coordinator.engine.command(
                "set_rule_enabled",
                {"rule_id": self.key.removeprefix("rule:"), "enabled": enabled},
                user.id,
                administrator=user.is_admin,
            )
            self.coordinator.schedule_deadline()
        except FamilyError as err:
            raise ServiceValidationError(str(err)) from None
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)


async def async_setup_entry(hass, entry, async_add_entities):
    def factory(state):
        for rule in state.rules.values():
            yield f"rule:{rule.id}", rule.name, FamilyRuleSwitch

    dynamic_setup(entry.runtime_data, entry, async_add_entities, factory)
