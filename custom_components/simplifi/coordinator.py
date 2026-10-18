"""Serialized policy discovery and independent, bounded observation jobs."""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .coexistence import CoexistenceReader
from .const import DOMAIN
from .dns_checks import QueryCache, due_claim, run_probe, simulated_probe
from .dns_context import jobs
from .gateway_health import GatewayHealth
from .models import SimpliFiError, fingerprint, instant
from .protection import ProtectionReader
from .storage import HouseholdStorage


class SimpliFiCoordinator(DataUpdateCoordinator):
    storage: HouseholdStorage

    def __init__(self, hass, entry, engine, logger):
        super().__init__(
            hass,
            logger,
            name="SimpliFi",
            config_entry=entry,
            update_interval=timedelta(seconds=30),
        )
        self.engine = engine
        self.closing = False
        self._active_operations = {}
        self._deadline_cancel = None
        self._deadline_at = None
        self._deadline_task = None
        self._deadline_again = False
        self.entry = entry
        self.issue_id = f"{entry.entry_id}_sync_failed"
        self.probe_lock = asyncio.Lock()
        self.probe_task = None
        self.dns_progress: dict[str, Any] = {
            "running": False,
            "completed": 0,
            "total": 0,
            "issue": None,
        }
        self.protection = ProtectionReader(hass, engine.gateway)
        self.coexistence = CoexistenceReader(hass, engine.gateway)
        self.gateway_health = GatewayHealth(engine.gateway, engine.clock, hass=hass)

    @callback
    def schedule_deadline(self, *, catch_up=False):
        """Wake for exception expiry separately from the ordinary inventory poll."""
        state = self.engine.state
        now = self.engine.clock()
        deadlines = [instant(e.expires_at) for e in state.exceptions.values() if e.expires_at]
        if state.quarantine and state.quarantine_until:
            deadlines.append(instant(state.quarantine_until))
        upcoming = [deadline for deadline in deadlines if deadline > now]
        # A slow successful read may have planned before a deadline that passed
        # during I/O. Queue a new read; failed reads retain normal bounded polling.
        if (
            catch_up
            and state.last_observed
            and any(instant(state.last_observed) < deadline <= now for deadline in deadlines)
        ):
            upcoming.append(now)
        point = min(upcoming) if upcoming and state.management and not self.closing else None
        if point == self._deadline_at:
            return
        if self._deadline_cancel:
            self._deadline_cancel()
            self._deadline_cancel = None
        self._deadline_at = point
        if point:
            self._deadline_cancel = async_track_point_in_utc_time(
                self.hass, self._deadline_due, point
            )

    @callback
    def _deadline_due(self, _now):
        self._deadline_cancel = None
        self._deadline_at = None
        if self.closing:
            return
        # Publish the now-unconfirmed intent before any potentially slow I/O.
        self.async_update_listeners()
        if self._deadline_task and not self._deadline_task.done():
            self._deadline_again = True
            return
        self._deadline_task = self.entry.async_create_background_task(
            self.hass, self._refresh_at_deadline(), "simplifi_deadline"
        )

    async def _refresh_at_deadline(self):
        if self.closing:
            return
        with self.operation():
            while not self.closing:
                self._deadline_again = False
                # Public HA refresh acquires the coordinator's existing lock,
                # bypassing its request debounce but never an in-flight write.
                await self.async_refresh()
                if not self._deadline_again:
                    break

    @contextmanager
    def operation(self):
        """Keep accepted work alive until unload has drained its durable writes."""
        if self.closing:
            raise SimpliFiError("SimpliFi is stopping; wait for the integration to reload")
        task = asyncio.current_task()
        self._active_operations[task] = self._active_operations.get(task, 0) + 1
        try:
            yield
        finally:
            self._active_operations[task] -= 1
            if not self._active_operations[task]:
                del self._active_operations[task]

    async def _async_update_data(self):
        with self.operation():
            return await self._update_data_running()

    async def _update_data_running(self):
        run_id = await self.storage.history.start(self.engine.state, self.engine.clock())
        started = monotonic()
        existing_operations = {j["id"] for j in self.engine.state.journal}
        success = False
        sync_state = None
        try:
            await self.engine.refresh()
            sync_state = deepcopy(self.engine.state)
            await self.protection.refresh(self.engine.clock())
            await self.coexistence.refresh(self.engine.clock())
            async with self.engine.lock:
                self.engine.ensure_available()
                schedule = self.engine.state.probe_schedule
                claim = (
                    due_claim(schedule, self.engine.clock(), self.engine.state.timezone)
                    if self.engine.state.dns_settings["enabled"]
                    else None
                )
                if self.probe_lock.locked() or (self.probe_task and not self.probe_task.done()):
                    claim = None
                if claim:
                    schedule["last_claim"] = claim
                    await self.engine.save(self.engine.state)
            if claim:
                self.start_dns()
            success = True
        except SimpliFiError, TimeoutError:
            if self.closing:
                raise UpdateFailed("SimpliFi is stopping") from None
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self.issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="sync_failed",
            )
            raise UpdateFailed(
                "SimpliFi sync failed; intent and ownership journal retained"
            ) from None
        finally:
            sync_state = sync_state or deepcopy(self.engine.state)
            try:
                await self.storage.history.finish(
                    run_id,
                    sync_state,
                    [j for j in sync_state.journal if j["id"] not in existing_operations],
                    success,
                    round((monotonic() - started) * 1000),
                    interrupted=self.closing and not success,
                )
            finally:
                self.schedule_deadline(catch_up=success)
        ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
        return self.engine.state

    def start_dns(self, probe_id=None, group_id=None):
        if self.closing:
            return False
        if self.probe_task and not self.probe_task.done():
            return False
        self.probe_task = self.entry.async_create_background_task(
            self.hass, self.check_dns(probe_id, group_id), "simplifi_dns"
        )
        return True

    async def check_dns(self, probe_id=None, group_id=None):
        with self.operation():
            await self._check_dns_running(probe_id, group_id)

    async def _check_dns_running(self, probe_id=None, group_id=None):
        async with self.probe_lock:
            cache = None
            self.dns_progress = {
                "running": True,
                "completed": 0,
                "total": 0,
                "issue": None,
                "started_at": self.engine.clock().isoformat(),
            }
            try:
                async with self.engine.lock:
                    self.engine.ensure_available()
                    planned = jobs(
                        self.engine.state, self.engine.gateway.networks, probe_id, group_id
                    )
                    for key, context in planned:
                        self.engine.state.probe_results.get(key, {}).get("contexts", {}).pop(
                            context, None
                        )
                    await self.engine.save(self.engine.state)
                self.dns_progress["total"] = len(planned)
                if not planned:
                    self.dns_progress["issue"] = (
                        "No resolver is available for the selected lists and devices"
                    )
                if not self.engine.gateway.simulation:
                    cache = QueryCache(async_get_clientsession(self.hass))
                # Sequential lists share an eight-query transport pool and cache.
                # Timeouts cancel all queued requests and leave incomplete checks unknown.
                async with asyncio.timeout(120):
                    for (key, context), spec in planned.items():
                        result = (
                            await simulated_probe(spec, now=self.engine.clock())
                            if self.engine.gateway.simulation
                            else await run_probe(spec, query_fn=cache, now=self.engine.clock())
                        )
                        async with self.engine.lock:
                            self.engine.ensure_available()
                            try:
                                current = jobs(
                                    self.engine.state, self.engine.gateway.networks, key, group_id
                                )
                            except SimpliFiError:
                                current = {}
                            if (key, context) in current and fingerprint(
                                current[(key, context)]
                            ) == result["configuration_hash"]:
                                bucket = self.engine.state.probe_results.setdefault(
                                    key, {"contexts": {}}
                                )
                                bucket.setdefault("contexts", {})[context] = result
                                await self.engine.save(self.engine.state)
                        self.dns_progress["completed"] += 1
                        self.async_set_updated_data(self.engine.state)
            except TimeoutError:
                self.dns_progress["issue"] = (
                    "The two-minute check limit was reached; incomplete checks remain unknown. Check a smaller list separately."
                )
            except SimpliFiError as error:
                self.dns_progress["issue"] = str(error)
            except Exception:
                self.dns_progress["issue"] = (
                    "DNS checks could not finish; incomplete checks remain unknown"
                )
                self.logger.warning(
                    "SimpliFi DNS job failed; incomplete observations were discarded"
                )
            finally:
                if cache:
                    await cache.close()
                self.dns_progress["running"] = False
                self.dns_progress["finished_at"] = self.engine.clock().isoformat()
                self.async_set_updated_data(self.engine.state)

    async def async_shutdown(self):
        self.closing = True
        self.engine.closing = True
        if self._deadline_cancel:
            self._deadline_cancel()
            self._deadline_cancel = None
        self._deadline_at = None
        await super().async_shutdown()
        current = asyncio.current_task()
        pending = [task for task in self._active_operations if task is not current]
        if pending:
            # Do not cancel a Store write or a gateway request whose receipt is
            # still being persisted. HTTP/probe deadlines bound ongoing I/O.
            await asyncio.gather(
                *(asyncio.shield(task) for task in pending), return_exceptions=True
            )
        # Native options/connection flows may already hold the engine lock.
        # Reject queued old commands and wait for their current write to finish.
        async with self.engine.lock:
            pass
        async with self.storage.history.lock:
            pass
