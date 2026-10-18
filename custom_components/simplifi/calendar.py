"""Read-only projections of schedules and exceptions, not enforcement observations."""

from datetime import timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent

from .entity import SimpliFiEntity
from .models import instant
from .schedule import occurrences


class SimpliFiCalendar(SimpliFiEntity, CalendarEntity):
    @property
    def event(self):
        now = self.coordinator.engine.clock()
        return next(iter(self.events(now, now + timedelta(days=8))), None)

    def events(self, start, end):
        state = self.state_model
        events = []
        for rule in state.rules.values():
            if not rule.enabled:
                continue
            names = ", ".join(
                state.groups[g].name for g in rule.groups if not state.groups[g].archived
            )
            if rule.networks:
                names = "Whole networks: " + ", ".join(
                    self.coordinator.engine.gateway.networks.get(n, {}).get("name", n)
                    for n in rule.networks
                )
            if not names:
                continue
            for window in rule.windows:
                for a, b in occurrences(window, start, end, state.timezone):
                    events.append(
                        CalendarEvent(
                            start=a,
                            end=b,
                            summary=f"{names}: {rule.name}",
                            description="Projected schedule. Exceptions may lift this rule; readback is separate.",
                        )
                    )
        for exc in state.exceptions.values():
            a = instant(exc.created_at)
            b = instant(exc.expires_at) if exc.expires_at else end
            if b > start and a < end:
                events.append(
                    CalendarEvent(
                        start=a,
                        end=b,
                        summary=f"{exc.kind}: {state.groups[exc.group].name if exc.group in state.groups else 'Rule'}",
                        description=exc.reason
                        or "Temporary managed exception; expiry depends on HA",
                    )
                )
        return sorted(events, key=lambda e: e.start)

    async def async_get_events(self, hass, start_date, end_date):
        return self.events(start_date, end_date)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [SimpliFiCalendar(entry.runtime_data, entry, "calendar", "Projected schedule")]
    )
