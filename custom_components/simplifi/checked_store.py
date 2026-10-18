"""Strict recovery reads and atomic HA Store writes for gateway receipts."""

import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util.file import WriteError
from homeassistant.util.json import SerializationError

from .models import SimpliFiError


class CheckedStore[T: Mapping[str, Any]](Store[T]):
    def __init__(self, hass: HomeAssistant, version: int, key: str) -> None:
        # Enable HA's fsync-capable AtomicWriter. Its default writer also renames
        # a temporary file, but does not sync its contents before replacement.
        super().__init__(hass, version, key, atomic_writes=True)

    def _ensure_writable(self) -> None:
        if self._read_only or self._load_empty:
            raise SimpliFiError(
                "SimpliFi storage is read-only; preserve stored data and review recovery"
            )

    def _read_record(self) -> dict[str, Any] | None:
        path = Path(self.path)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            # A previous HA Store version may have moved a damaged file aside.
            # Its absence must not turn that prior failure into a new household.
            if any(path.parent.glob(path.name + ".corrupt.*")):
                raise ValueError("Previous corrupt record") from None
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Invalid record")
        return data

    async def _async_load_data(self) -> T | None:
        self._ensure_writable()
        try:
            # Keep Store's public load serialization and pending-data semantics,
            # but bypass its corrupt-JSON rename/empty fallback and startup cache.
            data = (
                deepcopy(self._data)
                if self._data is not None
                else await self.hass.async_add_executor_job(self._read_record)
            )
            if data is None:
                return None
            if (
                type(data.get("version")) is not int
                or data["version"] != self.version
                or type(data.get("minor_version", 1)) is not int
                or data.get("minor_version", 1) != self.minor_version
                or data.get("key", self.key) != self.key
                or not isinstance(data.get("data"), dict)
            ):
                raise ValueError("Unsupported record")
            return cast(T, data["data"])
        except OSError, ValueError:
            self.make_read_only()
            raise SimpliFiError(
                "Stored SimpliFi data could not be read; preserve it and review a matching HA backup"
            ) from None

    async def _async_write_data(self, data: dict[str, Any]) -> None:
        try:
            await super()._async_write_data(data)
        except WriteError, SerializationError:
            raise SimpliFiError(
                "Unable to persist SimpliFi state; the operation cannot continue"
            ) from None

    async def async_save(self, data: T) -> None:
        self._ensure_writable()
        await super().async_save(data)
        if self.hass.state is CoreState.stopping:
            # Store normally defers stopping-state writes until the final-write
            # event. A gateway operation needs the receipt before that event.
            await self._async_handle_write_data()
        # HA can switch a store to read-only while a write waits for its lock.
        # Its skipped write must not be acknowledged as a persisted receipt.
        self._ensure_writable()
