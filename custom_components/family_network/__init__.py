"""SimpliFi: native HA controls with disabled-by-default live management."""

import logging
from typing import Any

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.simulator import FakeGateway
from .api.unifi import UniFiGateway
from .const import DOMAIN, PLATFORMS
from .coordinator import FamilyCoordinator
from .engine import Engine
from .models import FamilyError, Group, State
from .services import register_services
from .storage import HouseholdStorage

LOGGER = logging.getLogger(__name__)


async def async_setup(hass, config):
    from .frontend import async_setup_frontend

    await async_setup_frontend(hass)
    return True


async def async_setup_entry(hass, entry):
    data = entry.data
    gateway: Any = (
        FakeGateway()
        if data["simulation"]
        else UniFiGateway(
            async_get_clientsession(hass),
            data["controller"],
            data["api_key"],
            data["site"],
            list(data["networks"]),
            data["external_zone"],
            data.get("verify_ssl", True),
        )
    )
    if not data["simulation"]:
        try:
            sites = await gateway.connect()
            if data["site"] not in {s["id"] for s in sites}:
                raise FamilyError("Selected site disappeared")
        except FamilyError, TimeoutError:
            raise ConfigEntryNotReady("Gateway API unavailable or unsupported") from None
    if not data["simulation"]:
        from .current_network import CurrentNetworkReader

        gateway.current_network_reader = CurrentNetworkReader(hass, gateway)
    initial = State(gateway.controller, gateway.site, list(data["networks"]), data["timezone"])
    if data["simulation"]:
        initial.groups["demo-family"] = Group("demo-family", "Demo family")
        initial.gateway_timezone_confirmed = True
    storage = HouseholdStorage(hass, entry.entry_id)
    state = await storage.load(initial, data.get("binding_token"))
    await storage.history.load(state)
    if (state.controller, state.site, state.networks) != (
        initial.controller,
        initial.site,
        initial.networks,
    ):
        raise ConfigEntryNotReady(
            "Stored controller/site/scope mismatch; preserve storage and review binding"
        )
    # Prior successful reads are never startup freshness/confirmation evidence.
    state.inventory_complete = False
    engine = Engine(state, gateway, storage.save)
    engine.import_backup = storage.backup.async_save
    coordinator = FamilyCoordinator(hass, entry, engine, LOGGER)
    coordinator.storage = storage
    entry.runtime_data = coordinator
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        # Keep supported recovery actions reachable after a restart with a
        # retained journal. Entities remain unavailable and the writer frozen.
        if not engine.state.journal and not engine.state.owned:
            raise
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    register_services(hass)
    from .update_runtime import setup_updates

    await setup_updates(hass, entry)
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown()
        await entry.runtime_data.engine.gateway.close()
        # Keep policies and journal. Removal never automatically opens the network.
        if not any(
            e.state.name == "LOADED"
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ):
            from .actions import SCHEMAS

            for action in SCHEMAS:
                hass.services.async_remove(DOMAIN, action)
        return True
    return False
