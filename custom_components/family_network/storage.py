"""HA Store-backed persistence with atomic immediate writes."""

from .checked_store import CheckedStore as Store
from .const import DOMAIN
from .history import RunHistory
from .models import State


class HouseholdStorage:
    def __init__(self, hass, entry_id):
        self.history = RunHistory(hass, entry_id)
        self.store: Store[dict] = Store(hass, 1, f"{DOMAIN}.{entry_id}")
        self.access_backup: Store[dict] = Store(hass, 1, f"{DOMAIN}.{entry_id}.pre_access_upgrade")
        self.dns_backup: Store[dict] = Store(hass, 1, f"{DOMAIN}.{entry_id}.pre_dns_upgrade")
        self.inventory_backup: Store[dict] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.pre_inventory_upgrade"
        )
        self.backup: Store[dict] = Store(hass, 1, f"{DOMAIN}.{entry_id}.pre_import")
        self.rule_pause_backup: Store[dict] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.pre_rule_pause_upgrade"
        )
        self.binding_upgrade: Store[dict] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.pre_binding_upgrade"
        )
        self.binding_backup: Store[dict] = Store(hass, 1, f"{DOMAIN}.{entry_id}.pre_reconfigure")
        self.binding_pending: Store[dict] = Store(hass, 1, f"{DOMAIN}.{entry_id}.pending_binding")
        self.network_rules_backup: Store[dict] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.pre_network_rules_upgrade"
        )

    async def stage_binding(self, previous, proposed, data):
        from .binding import binding, review_state

        await self.store.async_save(previous.to_dict())
        await self.binding_backup.async_save(previous.to_dict())
        await self.binding_pending.async_save(
            {
                "token": proposed.binding_token,
                "previous_token": previous.binding_token,
                "source_hash": review_state(previous),
                "binding": binding(data),
                "state": proposed.to_dict(),
            }
        )

    async def load(self, initial, binding_token=None):
        raw = await self.store.async_load()
        from .dns_catalog import ensure_seeds
        from .dns_checks import validate_probe

        if raw is not None and "quarantine_suspended" not in raw:
            if await self.rule_pause_backup.async_load() is None:
                await self.rule_pause_backup.async_save(raw)
        if raw is not None and "binding_token" not in raw:
            if await self.binding_upgrade.async_load() is None:
                await self.binding_upgrade.async_save(raw)
        if binding_token is not None and (raw or {}).get("binding_token") != binding_token:
            from .binding import review_state
            from .models import FamilyError

            pending = await self.binding_pending.async_load()
            if (
                raw is None
                or not pending
                or pending["token"] != binding_token
                or raw.get("binding_token") != pending["previous_token"]
                or review_state(State.from_dict(raw)) != pending["source_hash"]
                or any(
                    pending["binding"][k] != getattr(initial, k)
                    for k in ("controller", "site", "networks", "timezone")
                )
            ):
                raise FamilyError(
                    "Connection handoff could not be verified; preserve the reconfiguration backup"
                )
            proposed = State.from_dict(pending["state"])
            await self.store.async_save(proposed.to_dict())
            raw = proposed.to_dict()
        # The token in main storage is the durable receipt. A crash before removing
        # the pending record cannot replay it over later household edits.
        if binding_token is not None and (raw or {}).get("binding_token") == binding_token:
            await self.binding_pending.async_remove()

        if raw is not None and "dns_settings" not in raw:
            await self.dns_backup.async_save(raw)
        if raw is not None and any(
            "network_source" not in d for d in raw.get("devices", {}).values()
        ):
            if await self.inventory_backup.async_load() is None:
                await self.inventory_backup.async_save(raw)
        if raw is not None and "access_grants" not in raw:
            if await self.access_backup.async_load() is None:
                await self.access_backup.async_save(raw)
        state = State.from_dict(raw) if raw is not None else initial
        if raw is not None and any("networks" not in r for r in raw.get("rules", {}).values()):
            if await self.network_rules_backup.async_load() is None:
                await self.network_rules_backup.async_save(raw)
        for key, probe in state.probes.items():
            state.probes[key] = {**probe, **validate_probe(probe)}
        ensure_seeds(state)
        state.validate()
        return state

    async def save(self, state):
        await self.store.async_save(state.to_dict())
