from unittest.mock import AsyncMock

import pytest

from custom_components.simplifi.api.unifi import UniFiGateway, external_zone_id
from custom_components.simplifi.models import CapabilityError


@pytest.mark.parametrize(
    "zone",
    [
        {
            "id": "zone",
            "name": "Home",
            "metadata": {"origin": "SYSTEM_DEFINED"},
            "networkIds": ["network"],
        },
        {
            "id": "zone",
            "name": "External",
            "metadata": {"origin": "USER_DEFINED"},
            "networkIds": [],
        },
        {
            "id": "zone",
            "name": "Gateway",
            "metadata": {"origin": "SYSTEM_DEFINED"},
            "networkIds": [],
        },
    ],
)
async def test_live_adapter_refuses_non_internet_destination(zone):
    gateway = UniFiGateway(None, "https://controller.example", "test", "site", ["network"], "zone")
    gateway.pages = AsyncMock(
        side_effect=[
            [{"id": "network", "name": "Family", "zoneId": "home"}],
            [zone, {"id": "home", "name": "Internal"}],
            [],
            [],
        ]
    )
    gateway.request = AsyncMock(
        return_value={
            "id": "network",
            "ipv4Configuration": {"hostIpAddress": "192.0.2.1", "prefixLength": 24},
        }
    )
    with pytest.raises(CapabilityError):
        await gateway.refresh_resources()


@pytest.mark.parametrize(
    "membership", [{}, {"networkIds": None}, {"networkIds": []}, {"networkIds": ["wan"]}]
)
async def test_builtin_external_identity_does_not_require_empty_membership(membership):
    zone = {
        "id": "external",
        "name": "External",
        "metadata": {"origin": "SYSTEM_DEFINED"},
        **membership,
    }
    gateway = UniFiGateway(
        None, "https://controller.example", "test", "site", ["network"], "external"
    )
    gateway.pages = AsyncMock(
        side_effect=[
            [{"id": "network", "name": "Family", "zoneId": "home"}],
            [zone, {"id": "home", "name": "Internal"}],
            [],
            [],
        ]
    )
    gateway.request = AsyncMock(return_value={"id": "network"})
    await gateway.refresh_resources()
    assert external_zone_id(gateway.zones) == "external"
    assert gateway.request.call_args.args[0] == "GET"


@pytest.mark.parametrize(
    "zones",
    [
        [],
        [{"id": "custom", "name": "External", "metadata": {"origin": "USER_DEFINED"}}],
        [{"id": "unknown", "name": "External"}],
        [{"id": "unknown", "name": "External", "metadata": None}],
        [{"id": "internal", "name": "Internal", "metadata": {"origin": "SYSTEM_DEFINED"}}],
        [
            {"id": "a", "name": "External", "metadata": {"origin": "SYSTEM_DEFINED"}},
            {"id": "b", "name": "External", "metadata": {"origin": "SYSTEM_DEFINED"}},
        ],
    ],
)
def test_missing_custom_unknown_or_ambiguous_external_is_rejected(zones):
    with pytest.raises(CapabilityError, match="built-in External"):
        external_zone_id(zones)


async def test_runtime_rejects_non_external_id_even_when_external_exists():
    zones = [
        {"id": "external", "name": "External", "metadata": {"origin": "SYSTEM_DEFINED"}},
        {"id": "internal", "name": "Internal", "metadata": {"origin": "SYSTEM_DEFINED"}},
    ]
    gateway = UniFiGateway(None, "https://controller.example", "test", "site", [], "internal")
    gateway.pages = AsyncMock(side_effect=[[], zones, [], []])
    with pytest.raises(CapabilityError, match="writer frozen"):
        await gateway.refresh_resources()
