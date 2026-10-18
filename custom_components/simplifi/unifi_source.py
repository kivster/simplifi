"""Select one existing HA UniFi session for the exact controller and site."""

from urllib.parse import urlsplit

from .models import SimpliFiError


def matching_unifi_entry(hass, gateway):
    origin = urlsplit(gateway.controller)
    site = getattr(gateway, "legacy_site", None)
    if not site:
        raise SimpliFiError("The official API has not supplied a matching site reference")
    matches = []
    for entry in hass.config_entries.async_entries("unifi"):
        if entry.state.name != "LOADED":
            continue
        hub = getattr(entry, "runtime_data", None)
        config = getattr(hub, "config", None)
        if (
            hub is not None
            and config is not None
            and str(config.host).casefold() == (origin.hostname or "").casefold()
            and config.port == (origin.port or 443)
            and config.site == site
        ):
            matches.append(entry)
    if len(matches) != 1:
        raise SimpliFiError(
            "Connect one Home Assistant UniFi Network integration for this controller and site"
        )
    return matches[0]


def matching_unifi_api(hass, gateway):
    return matching_unifi_entry(hass, gateway).runtime_data.api
