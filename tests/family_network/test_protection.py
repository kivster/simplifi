"""Readback must be scoped, read-only, bounded and distinguish stale from empty."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiounifi.models.api import ApiRequest, ApiRequestV2

from custom_components.family_network.models import FamilyError
from custom_components.family_network.protection import ProtectionReader, normalize_profiles

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)
PROFILE = {
    "_id": "profile",
    "name": "Family",
    "enabled": True,
    "network_ids": ["legacy-network"],
    "client_macs": [],
    "categories": ["ADULT"],
    "safe_search": ["GOOGLE"],
    "allow_list": ["example.com"],
    "block_list": ["blocked.example"],
    "schedule": {"mode": "ALWAYS"},
    "unexpected_secret": "do-not-expose",
}
NETWORKS = {"data": [{"_id": "legacy-network", "name": "Family VLAN", "x_password": "hidden"}]}


def reader(host="192.0.2.1", site="default", count=1, state="LOADED"):
    api = SimpleNamespace(request=AsyncMock(side_effect=[{"data": [PROFILE]}, NETWORKS]))
    hub = SimpleNamespace(config=SimpleNamespace(host=host, port=443, site=site), api=api)
    entry = SimpleNamespace(state=SimpleNamespace(name=state), runtime_data=hub)
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda _: [entry] * count))
    gateway = SimpleNamespace(
        simulation=False, controller="https://192.0.2.1", legacy_site="default", networks={}
    )
    return ProtectionReader(hass, gateway), api


async def test_matching_existing_session_reads_only_fixed_get_endpoints():
    source, api = reader()
    await source.refresh(NOW)
    assert api.request.call_args_list[0].args == (
        ApiRequestV2(method="get", path="/content-filtering"),
    )
    assert api.request.call_args_list[1].args == (
        ApiRequest(method="get", path="/rest/networkconf"),
    )
    result = source.snapshot(NOW)
    assert result["fresh"] and result["status"] == "available"
    assert result["profile_count"] == 1 and result["read_only"]
    assert result["profiles"][0]["networks"] == [
        {"id": "legacy-network", "name": "Family VLAN", "official_id": None}
    ]
    assert result["profiles"][0]["allow_list"] == ["example.com"]
    assert "do-not-expose" not in str(result) and "x_password" not in str(result)
    await source.refresh(NOW + timedelta(seconds=30))
    assert api.request.call_count == 2  # Poll at most once per minute.


@pytest.mark.parametrize(
    "kwargs",
    [
        {"host": "192.0.2.2"},
        {"site": "other"},
        {"count": 2},
        {"count": 0},
        {"state": "NOT_LOADED"},
    ],
)
async def test_no_read_on_wrong_ambiguous_or_unloaded_controller(kwargs):
    source, api = reader(**kwargs)
    await source.refresh(NOW)
    api.request.assert_not_called()
    assert source.snapshot(NOW)["status"] == "unavailable"


async def test_failure_keeps_last_read_but_never_claims_it_is_fresh_or_empty():
    source, api = reader()
    await source.refresh(NOW)
    api.request.side_effect = RuntimeError("credential or raw body must not escape")
    await source.refresh(NOW + timedelta(seconds=61))
    result = source.snapshot(NOW + timedelta(seconds=61))
    assert result["status"] == "stale" and not result["fresh"]
    assert result["profile_count"] == 1
    assert "credential" not in result["issue"]
    assert result["observed_at"] == NOW.isoformat()


async def test_successful_empty_collection_is_distinct_from_unavailable():
    source, api = reader()
    api.request.side_effect = [{"data": []}, NETWORKS]
    await source.refresh(NOW)
    result = source.snapshot(NOW)
    assert result["status"] == "available" and result["profile_count"] == 0
    assert source.snapshot(NOW + timedelta(seconds=121))["status"] == "stale"


@pytest.mark.parametrize(
    "field", ["enabled", "categories", "safe_search", "allow_list", "schedule"]
)
def test_missing_observation_is_not_defaulted_to_disabled_or_empty(field):
    row = deepcopy(PROFILE)
    del row[field]
    with pytest.raises(FamilyError):
        normalize_profiles({"data": [row]}, NETWORKS)


@pytest.mark.parametrize(
    "response", [{}, {"data": None}, {"data": [PROFILE, PROFILE]}, {"data": [PROFILE] * 1001}]
)
def test_malformed_duplicate_and_capped_responses_fail(response):
    with pytest.raises(FamilyError):
        normalize_profiles(response, NETWORKS)


async def test_simulation_never_reads_a_real_controller():
    source, api = reader()
    source.gateway.simulation = True
    await source.refresh(NOW)
    api.request.assert_not_called()
    assert source.snapshot(NOW)["fresh"]
    assert source.snapshot(NOW)["profiles"][0]["id"] == "demo-protection"


async def test_missing_site_reference_does_not_guess_default_site():
    source, api = reader()
    source.gateway.legacy_site = None
    await source.refresh(NOW)
    api.request.assert_not_called()
    assert source.snapshot(NOW)["status"] == "unavailable"
