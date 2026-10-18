"""Read-only update handoff; HACS owns release discovery and installation."""

from homeassistant.helpers.storage import Store

from .const import DOMAIN, VERSION


class UpdateInformation:
    """Expose installed version without claiming remote release availability."""

    def __init__(self, hass, legacy_attention=None):
        self.hass = hass
        self.legacy_attention = legacy_attention

    def status(self):
        return {
            "provider": "hacs",
            "installed": VERSION,
            "hacs_loaded": "hacs" in self.hass.config.components,
            "legacy_attention": self.legacy_attention,
            # Cached older cards must never offer a host-wide installation.
            "configured": False,
            "active": False,
            "ready": False,
            "check": {"status": "managed_by_hacs", "available": None},
            "schedule": {"enabled": False, "days": [], "time": "00:00"},
            "run": None,
            "next_run": None,
            "revision": 0,
        }


async def setup_updates(hass, entry):
    """Preserve old recovery evidence, remove obsolete credentials, start no jobs."""
    attention = None
    store: Store[dict[str, object]] = Store(hass, 1, f"{DOMAIN}.updates.{entry.entry_id}")
    try:
        stored = await store.async_load()
        if stored is not None:
            if not isinstance(stored, dict):
                raise ValueError("Invalid legacy update record")
            run = stored.get("run")
            if run is not None and not isinstance(run, dict):
                raise ValueError("Invalid legacy installation record")
            if run and (run.get("status") == "requested" or run.get("stage") == "attention"):
                attention = (
                    "An earlier installer has an unresolved attempt. Its recovery record "
                    "has been preserved. Review the previous installer and restore its "
                    "settings before updating again; SimpliFi will not resume that attempt."
                )
    except Exception:
        attention = (
            "The earlier installer record could not be read. Preserve it and review "
            "the previous installation before updating again."
        )
    entry.runtime_data.updates = UpdateInformation(hass, attention)
    if "update_github_token" in entry.data:
        data = dict(entry.data)
        data.pop("update_github_token")
        hass.config_entries.async_update_entry(entry, data=data)
