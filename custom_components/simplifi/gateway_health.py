"""Explicit, bounded device-statistics reads, separate from policy reconciliation."""

import asyncio
import ipaddress
import math
from copy import deepcopy
from time import monotonic
from urllib.parse import quote, urlsplit
from uuid import UUID

from .models import SimpliFiError, instant, utcnow

MAX_DEVICES = 64
COOLDOWN = 60
FRESH_SECONDS = 120
_METRICS = {
    "cpu_pct": "cpuUtilizationPct",
    "memory_pct": "memoryUtilizationPct",
    "load_1": "loadAverage1Min",
    "load_5": "loadAverage5Min",
    "load_15": "loadAverage15Min",
    "uptime_seconds": "uptimeSec",
}


def statistics(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("interfaces"), dict):
        raise SimpliFiError("Incomplete device statistics")
    values = {}
    for field, source in _METRICS.items():
        value = raw.get(source)
        if value is not None and (
            type(value) not in (int, float)
            or value > 2**63 - 1
            or not math.isfinite(value)
            or value < 0
            or (field.endswith("_pct") and value > 100)
            or (field == "uptime_seconds" and type(value) is not int)
        ):
            raise SimpliFiError("Invalid device statistics")
        values[field] = value
    heartbeat = raw.get("lastHeartbeatAt")
    if heartbeat is not None:
        if not isinstance(heartbeat, str) or len(heartbeat) > 64:
            raise SimpliFiError("Invalid device sample timestamp")
        try:
            instant(heartbeat)
        except ValueError, TypeError, AttributeError, SimpliFiError:
            raise SimpliFiError("Invalid device sample timestamp") from None
    return {**values, "sampled_at": heartbeat}


def overview(raw, controller):
    if not isinstance(raw, dict):
        raise SimpliFiError("Invalid device inventory")
    try:
        identity = str(UUID(raw["id"]))
        ip = ipaddress.ip_address(raw["ipAddress"])
    except KeyError, ValueError, TypeError, AttributeError:
        raise SimpliFiError("Invalid device inventory identity") from None
    if (
        any(
            not isinstance(raw.get(k), str) or not raw[k] or len(raw[k]) > 200
            for k in ("name", "model", "state")
        )
        or not isinstance(raw.get("features"), list)
        or any(f not in ("gateway", "switching", "accessPoint") for f in raw["features"])
        or len(raw["features"]) != len(set(raw["features"]))
    ):
        raise SimpliFiError("Incomplete device inventory")
    return {
        "id": identity,
        "name": raw["name"],
        "model": raw["model"],
        "state": raw["state"],
        "gateway": "gateway" in raw["features"],
        "controller": str(ip) == urlsplit(controller).hostname,
    }


class GatewayHealth:
    def __init__(self, gateway, clock=utcnow, timer=monotonic):
        self.gateway, self.clock, self.timer = gateway, clock, timer
        self.lock = asyncio.Lock()
        self.last_attempt = None
        self.last_read = None
        self.observed_at = None
        self.error = None
        self.devices = []
        self.total = None
        self.capped = False

    async def read(self):
        async with self.lock:
            if self.last_attempt is not None and self.timer() - self.last_attempt < COOLDOWN:
                return self.snapshot()
            self.last_attempt, self.last_read = self.timer(), self.clock().isoformat()
            try:
                async with asyncio.timeout(30):
                    if self.gateway.simulation:
                        rows = [
                            {
                                "id": "demo-gateway",
                                "name": "Demo gateway",
                                "model": "Simulator",
                                "state": "ONLINE",
                                "gateway": True,
                                "controller": True,
                                "cpu_pct": 12.5,
                                "memory_pct": 40.0,
                                "load_1": 0.3,
                                "load_5": 0.2,
                                "load_15": 0.2,
                                "uptime_seconds": 86400,
                                "sampled_at": self.clock().isoformat(),
                                "issue": None,
                            }
                        ]
                        total, capped = 1, False
                    else:
                        inventory, total, capped = await self._inventory()
                        semaphore = asyncio.Semaphore(4)

                        async def sample(device):
                            empty = {k: None for k in (*_METRICS, "sampled_at")}
                            if device["state"] != "ONLINE":
                                return {
                                    **device,
                                    **empty,
                                    "issue": "Device is not online; current statistics are unknown",
                                }
                            async with semaphore:
                                try:
                                    raw = await self.gateway.request(
                                        "GET",
                                        self.gateway.site_path
                                        + "/devices/"
                                        + quote(device["id"], safe="")
                                        + "/statistics/latest",
                                    )
                                    return {**device, **statistics(raw), "issue": None}
                                except SimpliFiError, TimeoutError:
                                    return {
                                        **device,
                                        **empty,
                                        "issue": "Device statistics could not be confirmed",
                                    }

                        rows = await asyncio.gather(*(sample(d) for d in inventory))
                self.devices = sorted(
                    rows,
                    key=lambda d: (
                        not d["gateway"],
                        not d["controller"],
                        d["name"].casefold(),
                        d["id"],
                    ),
                )
                self.total, self.capped = total, capped
                self.observed_at, self.error = self.clock().isoformat(), None
            except SimpliFiError, TimeoutError:
                # Keep the previous sample for reference, explicitly stale. Never
                # propagate an optional health failure to the policy writer.
                self.error = (
                    "Device health read failed or timed out; previous samples are last known"
                )
            return self.snapshot()

    async def _inventory(self):
        rows: list[dict] = []
        total = None
        while len(rows) < MAX_DEVICES:
            raw = await self.gateway.request(
                "GET",
                self.gateway.site_path + "/devices",
                params={"offset": len(rows), "limit": min(100, MAX_DEVICES - len(rows))},
            )
            if (
                not isinstance(raw, dict)
                or any(type(raw.get(k)) is not int for k in ("offset", "count", "totalCount"))
                or not isinstance(raw.get("data"), list)
                or raw["offset"] != len(rows)
                or raw["count"] != len(raw["data"])
                or raw["count"] > MAX_DEVICES - len(rows)
                or raw["totalCount"] < len(rows) + raw["count"]
                or (total is not None and total != raw["totalCount"])
            ):
                raise SimpliFiError("Incomplete device inventory page")
            total = raw["totalCount"]
            rows.extend(overview(d, self.gateway.controller) for d in raw["data"])
            if len({d["id"] for d in rows}) != len(rows):
                raise SimpliFiError("Duplicate device inventory identity")
            if len(rows) == total:
                return rows, total, False
            if not raw["data"]:
                raise SimpliFiError("Unexpected empty device inventory page")
        return rows, total, True

    def snapshot(self):
        now = self.clock()
        read_fresh = bool(
            self.observed_at
            and not self.error
            and 0 <= (now - instant(self.observed_at)).total_seconds() < FRESH_SECONDS
        )
        rows = deepcopy(self.devices)
        for row in rows:
            age = (now - instant(row["sampled_at"])).total_seconds() if row["sampled_at"] else None
            row["fresh"] = bool(
                read_fresh and not row["issue"] and age is not None and -30 <= age < FRESH_SECONDS
            )
            row["sample_age_seconds"] = max(0, int(age)) if age is not None else None
            row["missing_metrics"] = [k for k in _METRICS if row[k] is None]
            row["status"] = (
                "partial"
                if row["fresh"] and row["missing_metrics"]
                else "available"
                if row["fresh"]
                else "stale"
                if row["sampled_at"]
                else "unavailable"
            )
        complete = bool(
            read_fresh
            and not self.capped
            and all(d["fresh"] and not d["missing_metrics"] for d in rows)
        )
        meter = getattr(self.gateway, "request_meter", None)
        return {
            "status": "available"
            if complete
            else "partial"
            if read_fresh
            else "stale"
            if self.observed_at
            else "unavailable"
            if self.last_read
            else "not_read",
            "simulation": self.gateway.simulation,
            "read_at": self.observed_at,
            "last_attempt_at": self.last_read,
            "issue": self.error,
            "devices": rows,
            "total_devices": self.total,
            "returned_devices": len(rows),
            "device_limit": MAX_DEVICES,
            "capped": self.capped,
            "cooldown_seconds": COOLDOWN,
            "refresh_after_seconds": max(
                0, math.ceil(COOLDOWN - (self.timer() - self.last_attempt))
            )
            if self.last_attempt is not None
            else 0,
            "requests": meter.snapshot() if meter else None,
            "scope": "Latest reported samples for adopted devices on this UniFi site. Read only on request, with a 60-second cooldown; not a live performance stream. Missing metrics remain unknown.",
        }
