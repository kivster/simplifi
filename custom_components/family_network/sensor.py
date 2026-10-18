"""Compact intent/confirmation entities; no raw probe lists in recorder attributes."""

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity

from .const import STALE_SECONDS
from .entity import FamilyEntity, dynamic_setup
from .models import instant
from .planner import next_change


class FamilySensor(FamilyEntity, SensorEntity):
    @property
    def native_value(self):
        state = self.state_model
        now = self.coordinator.engine.clock()
        if self.key == "sync":
            return (
                "pending"
                if (
                    self.fresh
                    and state.management
                    and state.sync_status == "applied"
                    and not self.coordinator.engine.configuration_confirmed(now)
                )
                else state.sync_status
            )
        if self.key == "unassigned":
            return (
                sum(d.group is None and d.network in state.networks for d in state.devices.values())
                if self.fresh
                else None
            )
        if self.key == "protection":
            return self.coordinator.protection.snapshot(now)["status"]
        if self.key == "activity":
            return state.changes[-1]["outcome"] if state.changes else "no_changes"
        if self.key.startswith("group:"):
            _, group, field = self.key.split(":")
            if group not in state.groups:
                return None
            if field == "enforcement":
                confirmed = self.coordinator.engine.configuration_confirmed(now)
                return (
                    "unconfirmed"
                    if not confirmed
                    else "simulation"
                    if self.entry.data["simulation"]
                    else "configuration_confirmed"
                )
            if field == "next":
                value = next_change(state, group, now)
                return value.isoformat() if value else "none"
            status = self.coordinator.engine.status(group)
            if field == "internet":
                return (
                    status["state"]
                    if (
                        status["state"] == "unmanaged"
                        or self.coordinator.engine.configuration_confirmed(now)
                    )
                    else "unknown"
                )
            return status["devices"]
        if self.key.startswith("device:"):
            device = state.devices.get(self.key.removeprefix("device:"))
            return (
                "connected"
                if device and device.connected and self.fresh
                else "last_known"
                if device
                else None
            )
        if self.key.startswith("probe:"):
            probe_id = self.key.removeprefix("probe:")
            probe = state.probes.get(probe_id)
            from .dns_context import observation

            return (
                observation(
                    state,
                    self.coordinator.engine.gateway.networks,
                    probe_id,
                    probe.get("group_id"),
                    now,
                )["verdict"]
                if probe
                else "not_checked"
            )
        return None

    @property
    def fresh(self):
        state = self.state_model
        return (
            state.inventory_complete
            and state.last_observed is not None
            and self.coordinator.engine.clock() - instant(state.last_observed)
            < timedelta(seconds=STALE_SECONDS)
        )

    @property
    def extra_state_attributes(self):
        state = self.state_model
        if self.key == "protection":
            protection = self.coordinator.protection.snapshot(self.coordinator.engine.clock())
            return {
                k: protection[k]
                for k in ("observed_at", "fresh", "profile_count", "source", "issue")
            }
        if self.key == "sync":
            return {
                "desired_revision": state.revision,
                "confirmed_revision": state.confirmed_revision,
                "last_observed": state.last_observed,
                "management_enabled": state.management,
                "simulation": self.entry.data["simulation"],
                "issue": state.issue,
            }
        if self.key.startswith("group:"):
            _, group, _ = self.key.split(":")
            if group in state.groups:
                status = self.coordinator.engine.status(group)
                confirmed = self.coordinator.engine.configuration_confirmed()
                return {
                    **status,
                    "control_state": status["state"],
                    "state": status["state"]
                    if confirmed or status["state"] == "unmanaged"
                    else "unknown",
                    "confirmed": confirmed,
                }
        if self.key.startswith("device:"):
            device = state.devices.get(self.key.removeprefix("device:"))
            if device:
                return {
                    "owner_group": device.group,
                    "last_seen": device.last_seen,
                    "network": device.network,
                    "connection_type": device.kind,
                }
        if self.key.startswith("probe:"):
            result = state.probe_results.get(self.key.removeprefix("probe:"), {})
            return {k: result.get(k) for k in ("timestamp", "resolver", "vantage", "expires_at")}
        if self.key == "activity" and state.changes:
            return {
                k: state.changes[-1].get(k)
                for k in ("id", "actor", "action", "requested_at", "revision", "outcome")
            }
        return {}


async def async_setup_entry(hass, entry, async_add_entities):
    def factory(state):
        for key, name in (
            ("sync", "Sync status"),
            ("unassigned", "Unassigned devices"),
            ("protection", "External network protection"),
            ("activity", "Last change"),
        ):
            yield key, name, FamilySensor
        for group in state.groups.values():
            for field, label in (
                ("internet", "Managed internet"),
                ("enforcement", "Confirmation"),
                ("next", "Next change"),
                ("devices", "Devices"),
            ):
                yield f"group:{group.id}:{field}", f"{group.name} {label}", FamilySensor
        for device in state.devices.values():
            yield f"device:{device.id}", device.name, FamilySensor
        for key, probe in state.probes.items():
            yield f"probe:{key}", probe["name"], FamilySensor

    dynamic_setup(entry.runtime_data, entry, async_add_entities, factory)
