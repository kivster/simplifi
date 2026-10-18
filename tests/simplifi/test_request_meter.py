"""Count real transport attempts without retaining identifiers or patching HA's client."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiounifi.interfaces.connectivity import Connectivity
from aiounifi.models.api import ApiRequest
from aiounifi.models.configuration import Configuration

from custom_components.simplifi.api.unifi import UniFiGateway
from custom_components.simplifi.metered_unifi import read
from custom_components.simplifi.models import SimpliFiError
from custom_components.simplifi.request_meter import MeteredSession, RequestMeter, endpoint


class Session:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    @asynccontextmanager
    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        reply = next(self.replies)
        if isinstance(reply, BaseException):
            raise reply
        status, data = reply
        yield SimpleNamespace(
            status=status,
            content_type="application/json",
            headers={"x-csrf-token": "hidden-csrf"},
            history=(),
            read=AsyncMock(return_value=json.dumps(data).encode()),
            json=AsyncMock(return_value=data),
        )


def test_window_counts_failures_concurrency_and_privacy_with_bounded_buckets():
    tick = [0.0]
    meter = RequestMeter(clock=lambda: tick[0])
    secret_path = "/v1/sites/household-secret/devices/child-secret/statistics/latest"
    with meter.attempt("GET", secret_path) as first:
        with meter.attempt("GET", "/unknown/private-key") as second:
            assert meter.snapshot()["in_flight"] == 2
            second["status"] = 429
        tick[0] = 0.02
        first["status"] = 200
    view = meter.snapshot()
    assert view["requests"] == view["completed"] == 2
    assert view["failures"] == view["rate_limited"] == 1
    assert view["peak_in_flight"] == 2 and view["in_flight"] == 0
    assert view["max_ms"] == 20
    assert all(
        secret not in str(view) for secret in ("household-secret", "child-secret", "private-key")
    )
    for n in range(1000):
        tick[0] = float(n)
        with meter.attempt("GET", f"/unknown/unique-secret-{n}") as attempt:
            attempt["status"] = 200
    assert len(meter.buckets) <= 300
    assert meter.snapshot()["requests"] == 300
    tick[0] = 1300
    assert meter.snapshot()["requests"] == 0


def test_known_routes_are_distinct_and_unknown_methods_cannot_become_labels():
    assert (
        endpoint("/v1/sites/private/networks/private/references")
        == "/v1/sites/{site}/networks/{id}/references"
    )
    assert (
        endpoint("/proxy/network/integration/v1/sites/secret/firewall/policies/ordering")
        == "/v1/sites/{site}/firewall/policies/ordering"
    )
    assert (
        endpoint("/v1/sites/secret/firewall/policies/secret-id")
        == "/v1/sites/{site}/firewall/policies/{id}"
    )
    assert endpoint("/proxy/network/api/s/private-site/stat/sta") == "HA UniFi /stat/sta"
    meter = RequestMeter()
    with meter.attempt("PRIVATE-KEY", "/private-key") as attempt:
        attempt["status"] = 200
    assert "PRIVATE-KEY" not in str(meter.snapshot())


def test_cancellation_is_counted_and_propagates_without_error_contents():
    meter = RequestMeter()
    with pytest.raises(asyncio.CancelledError):
        with meter.attempt("GET", "/v1/info"):
            raise asyncio.CancelledError("hidden response and credentials")
    view = meter.snapshot()
    assert view["cancelled"] == view["failures"] == view["requests"] == 1
    assert view["in_flight"] == 0 and "hidden" not in str(view)


async def test_official_retries_are_separate_requests_and_writes_are_never_retried(monkeypatch):
    session = Session([(429, {}), (503, {}), (200, {"applicationVersion": "test"}), (503, {})])
    gateway = UniFiGateway(session, "https://private-controller", "hidden-key")
    sleep = AsyncMock()
    monkeypatch.setattr("custom_components.simplifi.api.unifi.asyncio.sleep", sleep)
    assert await gateway.request("GET", "/v1/info") == {"applicationVersion": "test"}
    with pytest.raises(SimpliFiError):
        await gateway.request(
            "POST", "/v1/sites/private/firewall/policies", {"private-body": "hidden"}
        )
    view = gateway.request_meter.snapshot()
    assert view["requests"] == 4 and view["retries"] == 2
    assert view["failures"] == 3 and view["rate_limited"] == 1
    assert sleep.await_count == 2
    assert all(s not in str(view) for s in ("private-controller", "hidden-key", "private-body"))


async def test_native_session_auth_retry_is_counted_and_updates_shared_state_without_patching():
    session = Session([(401, {}), (200, {}), (200, {"data": []}), (200, {"data": []})])
    config = Configuration(
        session,
        "private-controller",
        username="hidden-user",
        password="hidden-password",
        port=443,
        site="private-site",
    )
    original = Connectivity(config)
    original.is_unifi_os, original.can_retry_login = True, True
    api = SimpleNamespace(connectivity=original, request=original.request)
    gateway = SimpleNamespace(request_meter=RequestMeter())
    method = original.request
    assert await read(api, ApiRequest(method="get", path="/stat/sta"), gateway) == {"data": []}
    view = gateway.request_meter.snapshot()
    assert view["requests"] == 3 and view["retries"] == view["failures"] == 1
    assert {r["endpoint"] for r in view["endpoints"]} == {
        "HA UniFi /stat/sta",
        "HA UniFi session login",
    }
    assert original.config is config and original.config.session is session
    assert original.request == method and original.can_retry_login
    assert original.headers["x-csrf-token"] == "hidden-csrf"
    assert all(
        s not in str(view)
        for s in (
            "private-controller",
            "private-site",
            "hidden-user",
            "hidden-password",
            "hidden-csrf",
        )
    )
    # A call by the native integration uses its original transport and is excluded.
    await api.request(ApiRequest(method="get", path="/stat/sta"))
    assert gateway.request_meter.snapshot()["requests"] == 3 and len(session.calls) == 4


def test_five_minute_log_contains_aggregate_fixed_labels_only(caplog):
    tick = [0.0]
    meter = RequestMeter(clock=lambda: tick[0])
    tick[0] = 301
    with caplog.at_level("INFO"):
        with meter.attempt("GET", "/v1/sites/household-secret/clients") as result:
            result["status"] = 200
    assert "Controller traffic in last 5 minutes: 1 requests" in caplog.text
    assert "household-secret" not in caplog.text


async def test_redirect_exchanges_count_without_inventing_parallelism_or_per_hop_latency():
    meter = RequestMeter()

    class RedirectSession:
        @asynccontextmanager
        async def request(self, method, url, **kwargs):
            yield SimpleNamespace(status=200, history=[SimpleNamespace(method="GET", status=302)])

    async with MeteredSession(RedirectSession(), meter).request(
        "GET", "https://private-controller/api/auth/login"
    ):
        pass
    view = meter.snapshot()
    assert view["requests"] == view["completed"] == 2
    assert view["peak_in_flight"] == 1 and view["timed_requests"] == 1
    redirect = next(r for r in view["endpoints"] if r["endpoint"] == "Redirect exchange")
    assert redirect["mean_ms"] is None and redirect["max_ms"] is None
