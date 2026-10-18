"""On-demand health never changes intent, polls silently or conceals missing evidence."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from custom_components.simplifi.diagnostics import async_get_config_entry_diagnostics
from custom_components.simplifi.gateway_health import GatewayHealth, statistics
from custom_components.simplifi.models import SimpliFiError
from custom_components.simplifi.presentation import dashboard_data
from custom_components.simplifi.request_meter import RequestMeter

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
STATS = {
    "interfaces": {},
    "lastHeartbeatAt": NOW.isoformat(),
    "cpuUtilizationPct": 0,
    "memoryUtilizationPct": 25,
    "loadAverage1Min": 0,
    "loadAverage5Min": 0.1,
    "loadAverage15Min": 0.2,
    "uptimeSec": 0,
}


def device(n=1, **values):
    return {
        "id": str(UUID(int=n)),
        "ipAddress": "192.0.2.1" if n == 1 else f"192.0.2.{n}",
        "name": f"Device {n}",
        "model": "Test",
        "state": "ONLINE",
        "features": ["switching"],
        **values,
    }


def page(devices, offset=0, total=None):
    return {
        "offset": offset,
        "count": len(devices),
        "totalCount": total if total is not None else len(devices),
        "data": devices,
    }


def health(responses):
    now, tick = [NOW], [100.0]
    gateway = SimpleNamespace(
        simulation=False,
        controller="https://192.0.2.1",
        site_path="/v1/sites/private-site",
        request=AsyncMock(side_effect=responses),
        request_meter=RequestMeter(clock=lambda: tick[0]),
    )
    return GatewayHealth(gateway, clock=lambda: now[0], timer=lambda: tick[0]), now, tick


async def test_current_zero_metrics_cooldown_cached_reads_and_expiry():
    reader, now, tick = health([page([device()]), STATS])
    assert reader.snapshot()["status"] == "not_read"
    assert reader.gateway.request.call_count == 0
    result = await reader.read()
    assert result["status"] == "available"
    row = result["devices"][0]
    assert row["cpu_pct"] == row["uptime_seconds"] == 0 and row["fresh"]
    assert row["controller"] and not row["gateway"]
    for _ in range(5):
        assert (await reader.read())["read_at"] == result["read_at"]
        reader.snapshot()
    assert reader.gateway.request.call_count == 2
    now[0] += timedelta(seconds=121)
    assert reader.snapshot()["status"] == "stale"
    assert not reader.snapshot()["devices"][0]["fresh"]
    tick[0] += 61
    reader.gateway.request.side_effect = SimpliFiError("private URL and secret must not escape")
    failed = await reader.read()
    assert failed["status"] == "stale" and failed["devices"][0]["cpu_pct"] == 0
    assert "secret" not in str(failed) and not failed["devices"][0]["fresh"]


async def test_concurrent_readers_share_one_bounded_read_and_sort_reported_gateway_first():
    reader, _, _ = health([page([device(), device(2, features=["gateway"])]), STATS, STATS])
    views = await asyncio.gather(*(reader.read() for _ in range(10)))
    assert reader.gateway.request.call_count == 3
    assert all(v["devices"][0]["gateway"] for v in views)


@pytest.mark.parametrize(
    "matching,roles,expected",
    [
        (True, ["udm"], True),
        (True, ["ugw"], True),
        (True, ["uxg"], True),
        (True, ["ucg"], True),
        (True, ["usw"], False),
        (True, ["udm", "usw"], False),
        (False, ["udm"], False),
    ],
)
async def test_gateway_role_uses_unique_cached_mac_on_exact_controller_and_site(
    matching, roles, expected
):
    mac = "02:00:00:00:00:11"
    reader, _, _ = health(
        [
            page([device(), device(2, name="Gateway", macAddress=mac, ipAddress="100.64.0.2")]),
            STATS,
            STATS,
        ]
    )
    reader.gateway.legacy_site = "default"
    native = SimpleNamespace(
        devices=SimpleNamespace(
            values=lambda: [SimpleNamespace(mac=mac, type=role) for role in roles]
        ),
        request=AsyncMock(side_effect=AssertionError("cached inventory must not fetch")),
    )
    entry = SimpleNamespace(
        state=SimpleNamespace(name="LOADED"),
        runtime_data=SimpleNamespace(
            config=SimpleNamespace(
                host="192.0.2.1", port=443, site="default" if matching else "other-site"
            ),
            api=native,
        ),
    )
    reader.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_entries=lambda domain: [entry])
    )
    view = await reader.read()
    row = next(d for d in view["devices"] if d["name"] == "Gateway")
    assert row["gateway"] is expected and not row["controller"]
    assert row["gateway_source"] == ("ha_unifi_inventory" if expected else None)
    if expected:
        assert view["devices"][0]["name"] == "Gateway"
    native.request.assert_not_awaited()
    assert mac not in str(view)


@pytest.mark.parametrize("value", [True, -1, 101, float("nan"), float("inf"), "50", 10**1000])
def test_bad_cpu_samples_are_rejected(value):
    with pytest.raises(SimpliFiError):
        statistics({**STATS, "cpuUtilizationPct": value})


@pytest.mark.parametrize("value", [True, -1, 1.5])
def test_bad_uptime_is_rejected(value):
    with pytest.raises(SimpliFiError):
        statistics({**STATS, "uptimeSec": value})


@pytest.mark.parametrize("value", ["2026-10-18T12:00:00", "not-a-date", 123, {}])
def test_missing_timezone_or_invalid_timestamps_are_rejected(value):
    with pytest.raises(SimpliFiError):
        statistics({**STATS, "lastHeartbeatAt": value})


async def test_missing_stale_future_offline_and_failed_samples_stay_explicit():
    old = (NOW - timedelta(minutes=10)).isoformat()
    future = (NOW + timedelta(minutes=10)).isoformat()
    reader, _, _ = health(
        [
            page([device(n) for n in range(1, 6)] + [device(6, state="OFFLINE")]),
            {"interfaces": {}, "lastHeartbeatAt": NOW.isoformat()},
            {**STATS, "lastHeartbeatAt": old},
            {**STATS, "lastHeartbeatAt": future},
            SimpliFiError("secret"),
            STATS,
        ]
    )
    view = await reader.read()
    assert view["status"] == "partial"
    assert [d["status"] for d in view["devices"]] == [
        "partial",
        "stale",
        "stale",
        "unavailable",
        "available",
        "unavailable",
    ]
    assert view["devices"][0]["cpu_pct"] is None
    assert len(view["devices"][0]["missing_metrics"]) == 6
    assert "secret" not in str(view)
    assert reader.gateway.request.call_count == 6  # Offline devices are not probed.


@pytest.mark.parametrize(
    "bad",
    [
        {},
        page([device(), device()]),
        page([device()], offset=1),
        page([], total=1),
        page([device()], total=-1),
        page([device(id="not-a-uuid")]),
    ],
)
async def test_incomplete_inventory_does_not_look_like_no_devices(bad):
    reader, _, _ = health([bad])
    view = await reader.read()
    assert view["status"] == "unavailable" and view["total_devices"] is None


async def test_capped_inventory_and_pagination_are_explicit():
    devices = [device(n, state="OFFLINE") for n in range(1, 65)]
    reader, _, _ = health([page(devices[:20], total=70), page(devices[20:], offset=20, total=70)])
    view = await reader.read()
    assert view["capped"] and view["status"] == "partial"
    assert view["total_devices"] == 70 and view["returned_devices"] == 64
    assert reader.gateway.request.call_count == 2


async def test_sample_concurrency_is_bounded_and_cancellation_releases_lock():
    reader, _, _ = health([])
    active, peak = 0, 0
    entered, release = asyncio.Event(), asyncio.Event()

    async def request(method, path, **kwargs):
        nonlocal active, peak
        if path.endswith("/devices"):
            return page([device(n) for n in range(1, 10)])
        active += 1
        peak = max(peak, active)
        if active == 4:
            entered.set()
        try:
            await release.wait()
            return STATS
        finally:
            active -= 1

    reader.gateway.request.side_effect = request
    task = asyncio.create_task(reader.read())
    await entered.wait()
    assert peak == 4
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert active == 0 and not reader.lock.locked()


async def test_simulator_and_routine_ha_projections_never_fetch_health(hass, entry, monkeypatch):
    coordinator = entry.runtime_data
    gateway = coordinator.engine.gateway
    before = deepcopy(coordinator.engine.state.to_dict())
    monkeypatch.setattr(
        gateway,
        "request",
        AsyncMock(side_effect=AssertionError("no physical requests")),
        raising=False,
    )
    cached_read = AsyncMock(wraps=coordinator.gateway_health.read)
    monkeypatch.setattr(coordinator.gateway_health, "read", cached_read)
    for _ in range(3):
        await dashboard_data(hass, entry)
        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["controller_requests"]["requests"] == 0
        assert diag["device_health"]["status"] == "not_read"
    cached_read.assert_not_awaited()
    demo = await coordinator.gateway_health.read()
    assert demo["simulation"] and demo["devices"][0]["model"] == "Simulator"
    assert demo["requests"]["requests"] == 0
    gateway.request.assert_not_awaited()
    assert coordinator.engine.state.to_dict() == before
