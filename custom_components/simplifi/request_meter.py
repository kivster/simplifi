"""Bounded transport accounting; identifiers, URLs, bodies and errors never persist."""

import logging
import re
from contextlib import asynccontextmanager, contextmanager
from time import monotonic

_LOGGER = logging.getLogger(__name__)
WINDOW = 300
# Each label is a constant. Unknown paths share one bucket, never a user-supplied label.
_ROUTES = (
    (r"/v1/info", "/v1/info"),
    (r"/v1/sites", "/v1/sites"),
    (r"/v1/dpi/categories", "/v1/dpi/categories"),
    (r"/v1/dpi/applications", "/v1/dpi/applications"),
    *(
        (rf"/v1/sites/[^/]+/{collection}", f"/v1/sites/{{site}}/{collection}")
        for collection in ("clients", "devices", "networks", "firewall/zones", "firewall/policies")
    ),
    (r"/v1/sites/[^/]+/firewall/policies/ordering", "/v1/sites/{site}/firewall/policies/ordering"),
    *(
        (rf"/v1/sites/[^/]+/{collection}/[^/]+", f"/v1/sites/{{site}}/{collection}/{{id}}")
        for collection in ("clients", "networks", "firewall/policies")
    ),
    (
        r"/v1/sites/[^/]+/devices/[^/]+/statistics/latest",
        "/v1/sites/{site}/devices/{id}/statistics/latest",
    ),
    (r"(?:/proxy/network)?/api/s/[^/]+/rest/networkconf", "HA UniFi /rest/networkconf"),
    (r"(?:/proxy/network)?/api/s/[^/]+/stat/sta", "HA UniFi /stat/sta"),
    (r"(?:/proxy/network)?/v2/api/site/[^/]+/content-filtering", "HA UniFi /content-filtering"),
    (r"/api/(?:auth/)?login", "HA UniFi session login"),
)
_FIELDS = (
    "requests",
    "completed",
    "failures",
    "retries",
    "rate_limited",
    "cancelled",
    "duration_ms",
    "timed_requests",
)


def endpoint(path):
    # A URL is reduced to its path before this function is called by the session view.
    path = path.removeprefix("/proxy/network/integration")
    for pattern, label in _ROUTES:
        if re.fullmatch(pattern, path):
            return label
    return "Other controller endpoint"


class RequestMeter:
    """Five-minute, one-second buckets with a fixed, finite endpoint vocabulary."""

    def __init__(self, clock=monotonic):
        self.clock = clock
        self.started = clock()
        self.next_log = self.started + WINDOW
        self.buckets = {}
        self.in_flight = 0

    def _prune(self, now):
        cutoff = int(now) - WINDOW + 1
        for key in list(self.buckets):
            if key[0] < cutoff:
                del self.buckets[key]

    @contextmanager
    def attempt(self, method, path, *, retry=False):
        started = self.clock()
        self._prune(started)
        method = method.upper() if method.upper() in {"GET", "POST", "PUT", "DELETE"} else "OTHER"
        key = (int(started), method, endpoint(path))
        row = self.buckets.setdefault(key, dict.fromkeys((*_FIELDS, "max_ms", "peak"), 0))
        row["requests"] += 1
        row["retries"] += bool(retry)
        self.in_flight += 1
        row["peak"] = max(row["peak"], self.in_flight)
        result = {"status": None}
        failed = False
        try:
            yield result
        except BaseException as err:
            failed = True
            # Never retain or log the exception, which may contain secrets or response bodies.
            from asyncio import CancelledError

            row["cancelled"] += isinstance(err, CancelledError)
            raise
        finally:
            elapsed = max(0, (self.clock() - started) * 1000)
            status = result["status"]
            row["completed"] += 1
            row["timed_requests"] += 1
            row["failures"] += failed or status is None or not 200 <= status < 400
            row["rate_limited"] += status == 429
            row["duration_ms"] += elapsed
            row["max_ms"] = max(row["max_ms"], elapsed)
            self.in_flight -= 1
            if self.clock() >= self.next_log:
                self.next_log = self.clock() + WINDOW
                view = self.snapshot()
                _LOGGER.info(
                    "Controller traffic in last 5 minutes: %s requests, %s failures, %s retries; endpoints: %s",
                    view["requests"],
                    view["failures"],
                    view["retries"],
                    [(r["method"], r["endpoint"], r["requests"]) for r in view["endpoints"]],
                )

    def snapshot(self):
        now = self.clock()
        self._prune(now)
        rows: dict[tuple[str, str], dict[str, float]] = {}
        for (_, method, label), bucket in self.buckets.items():
            row = rows.setdefault((method, label), dict.fromkeys((*_FIELDS, "max_ms", "peak"), 0))
            for name in _FIELDS:
                row[name] += bucket[name]
            for name in ("max_ms", "peak"):
                row[name] = max(row[name], bucket[name])

        def display(row):
            return {
                **{k: row[k] for k in _FIELDS if k != "duration_ms"},
                "mean_ms": round(row["duration_ms"] / row["timed_requests"], 1)
                if row["timed_requests"]
                else None,
                "max_ms": round(row["max_ms"], 1) if row["timed_requests"] else None,
            }

        totals = {name: sum(r[name] for r in rows.values()) for name in _FIELDS}
        totals["max_ms"] = max((r["max_ms"] for r in rows.values()), default=0)
        return {
            **display(totals),
            "window_seconds": WINDOW,
            "observed_seconds": min(WINDOW, max(0, int(now - self.started))),
            "in_flight": self.in_flight,
            "peak_in_flight": max((r["peak"] for r in rows.values()), default=self.in_flight),
            "endpoints": [
                {"method": method, "endpoint": label, **display(row)}
                for (method, label), row in sorted(rows.items())
            ],
            "scope": "Requests made by this SimpliFi instance, including retries and its borrowed UniFi session reads. Other integrations and controller traffic are excluded. Resets when the integration reloads.",
        }

    def redirect(self, method, status):
        """Account for a sequential redirect without inventing concurrent I/O or timing."""
        now = self.clock()
        self._prune(now)
        method = method.upper() if method.upper() in {"GET", "POST", "PUT", "DELETE"} else "OTHER"
        row = self.buckets.setdefault(
            (int(now), method, "Redirect exchange"),
            dict.fromkeys((*_FIELDS, "max_ms", "peak"), 0),
        )
        row["requests"] += 1
        row["completed"] += 1
        row["failures"] += not 200 <= status < 400
        row["rate_limited"] += status == 429


class MeteredSession:
    """Per-consumer view of a borrowed aiohttp session; never patch or close it."""

    def __init__(self, session, meter):
        self.session, self.meter = session, meter
        self.seen = set()

    def __getattr__(self, name):
        return getattr(self.session, name)

    @asynccontextmanager
    async def request(self, method, url, **kwargs):
        from urllib.parse import urlsplit

        path = urlsplit(str(url)).path
        label = (method.upper(), endpoint(path))
        with self.meter.attempt(method, path, retry=label in self.seen) as attempt:
            self.seen.add(label)
            async with self.session.request(method, url, **kwargs) as response:
                attempt["status"] = response.status
                # aiohttp may follow redirects in the borrowed session. Count each
                # additional HTTP exchange without retaining destinations or headers.
                for prior in getattr(response, "history", ()):
                    self.meter.redirect(prior.method, prior.status)
                yield response
