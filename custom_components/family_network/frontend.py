"""Serve the bundled card and register its versioned Lovelace resource."""

import logging
from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection

from .const import CARD_RESOURCE, CARD_URL

LOGGER = logging.getLogger(__name__)
LEGACY_CARD_URL = "/local/family-network/family-network-card.js"


async def async_setup_frontend(hass):
    """Expose only the public JavaScript file, never integration source or state."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CARD_URL, str(Path(__file__).parent / "frontend" / "family-network-card.js"), False
            )
        ]
    )
    await async_register_resource(hass)


async def async_register_resource(hass):
    """Use HA's resource collection API; YAML resources remain user-managed."""
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or not isinstance(lovelace.resources, ResourceStorageCollection):
        LOGGER.info("Add the SimpliFi JavaScript module to YAML resources: %s", CARD_RESOURCE)
        return
    resources = lovelace.resources
    try:
        await resources.async_get_info()
        matches = []
        for item in resources.async_items():
            url = urlsplit(item["url"])
            if not url.scheme and not url.netloc and url.path in {CARD_URL, LEGACY_CARD_URL}:
                matches.append(item)
        values = {"url": CARD_RESOURCE, "res_type": "module"}
        if not matches:
            await resources.async_create_item(values)
            return
        await resources.async_update_item(matches[0]["id"], values)
        # Only exact local resources for this card are consolidated. The domain,
        # custom element, entry IDs and dashboard configuration remain stable.
        for duplicate in matches[1:]:
            await resources.async_delete_item(duplicate["id"])
    except Exception:
        LOGGER.warning(
            "SimpliFi could not register its card; add the JavaScript module manually: %s",
            CARD_RESOURCE,
        )
