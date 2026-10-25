import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import jsonschema
import pytest

from custom_components.simplifi.actions import SCHEMAS
from custom_components.simplifi.api.unifi import UniFiGateway
from custom_components.simplifi.dashboard import build_native_dashboard as build_dashboard
from custom_components.simplifi.dns_checks import due_claim, run_probe, verdict
from custom_components.simplifi.models import Rule, SimpliFiError, domain_name
from custom_components.simplifi.planner import plan

from .conftest import command

OPENAPI_PATH = os.environ.get("SIMPLIFI_UNIFI_OPENAPI")
OPENAPI = json.loads(Path(OPENAPI_PATH).read_text()) if OPENAPI_PATH else None


@pytest.mark.parametrize(
    "domain",
    [
        "https://example.com",
        "*.example.com",
        "example.com/path",
        "127.0.0.1",
        "bad..com",
        "-bad.example",
        "localhost",
    ],
)
def test_domain_validation(domain):
    with pytest.raises(SimpliFiError):
        domain_name(domain)


def test_idna_domain():
    assert domain_name("MÜNCHEN.Example.") == "xn--mnchen-3ya.example"


async def test_pagination_requires_stable_complete_metadata():
    gateway = UniFiGateway(None, "https://example.local", "test")
    first = {"data": [{"id": "one"}], "offset": 0, "count": 1, "totalCount": 2}
    last = {"data": [{"id": "two"}], "offset": 1, "count": 1, "totalCount": 2}
    gateway.request = AsyncMock(side_effect=[first, last])
    assert len(await gateway.pages("/v1/sites")) == 2
    for bad in (
        {**last, "totalCount": 3},
        {**last, "offset": 0},
        {**last, "data": []},
        {"data": []},
        {**last, "data": [{"id": "one"}]},
    ):
        gateway.request = AsyncMock(side_effect=[first, bad])
        with pytest.raises(SimpliFiError):
            await gateway.pages("/v1/sites")


@pytest.mark.parametrize(
    "host",
    [
        "http://example.local",
        "https://key@example.local",
        "https://example.local/path",
        "https://example.local?key=secret",
    ],
)
def test_controller_origin_validation(host):
    with pytest.raises(SimpliFiError):
        UniFiGateway(None, host, "secret")


@pytest.mark.skipif(
    OPENAPI is None, reason="Set SIMPLIFI_UNIFI_OPENAPI to an official schema acquired separately"
)
@pytest.mark.parametrize("network_scope", [False, True])
async def test_real_documented_payload_schema_including_category_zero(household, network_scope):
    engine, gateway, now, _ = household
    schema = OPENAPI
    for kind, targets in (
        ("internet", []),
        ("category", [0]),
        ("application", [123]),
        ("domain", ["example.com"]),
    ):
        engine.state.rules = {
            kind: Rule(
                kind,
                kind,
                kind,
                [] if network_scope else ["child"],
                targets,
                networks=["demo-family"] if network_scope else [],
            )
        }
        for body in plan(
            engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0]
        ).values():
            validator = jsonschema.Draft202012Validator(
                {
                    "$ref": "#/components/schemas/Create or update firewall policy",
                    "components": schema["components"],
                }
            )
            validator.validate(body)
            # OpenAPI discriminators are not JSON Schema constraints; also validate the selected variants.
            for value, variant in (
                (
                    body["source"]["trafficFilter"],
                    "IntegrationFirewallPolicySourceNetworkFilterDto",
                ),
                (body["ipProtocolScope"], "IntegrationFirewallPolicyIpv4AndIpv6ProtocolScopeDto"),
            ):
                jsonschema.Draft202012Validator(
                    {"$ref": f"#/components/schemas/{variant}", "components": schema["components"]}
                ).validate(value)
    await command(
        engine, "upsert_rule", name="Zero", kind="category", groups=["child"], targets=[0]
    )


def response(status="answer", addresses=None):
    return {"status": status, "addresses": addresses or []}


@pytest.mark.parametrize(
    "observed,expected",
    [
        ({"A": response(addresses=["0.0.0.0"]), "AAAA": response("no_answer")}, "blocked"),
        (
            {"A": response(addresses=["0.0.0.0"]), "AAAA": response(addresses=["2001:db8::1"])},
            "open",
        ),
        ({"A": response("nxdomain"), "AAAA": response("nxdomain")}, "unknown"),
        ({"A": response("error"), "AAAA": response("no_answer")}, "unknown"),
    ],
)
def test_dns_never_turns_failures_or_ipv6_bypass_into_protection(observed, expected):
    baseline = {"A": response(addresses=["192.0.2.1"]), "AAAA": response("no_answer")}
    assert verdict(baseline, observed) == expected


async def test_dns_results_and_duplicate_schedule_claims():
    probe = {
        "name": "Test",
        "domains": ["test.example"],
        "resolver": "192.0.2.53",
        "baseline_resolver": "192.0.2.54",
        "revision": 1,
    }

    async def query(address, domain, kind):
        if kind == "AAAA":
            return response("no_answer")
        return response(
            addresses=[
                "0.0.0.0" if address.endswith("53") and domain != "example.com" else "192.0.2.2"
            ]
        )

    result = await run_probe(probe, query)
    assert result["verdict"] == "blocked"
    assert "Home Assistant" in result["vantage"]
    schedule = {"enabled": True, "days": list(range(7)), "time": "08:00", "last_claim": None}
    now = datetime(2026, 10, 13, 8, tzinfo=UTC)
    claim = due_claim(schedule, now, "Europe/London")
    assert claim
    schedule["last_claim"] = claim
    assert due_claim(schedule, now, "Europe/London") is None
    assert due_claim(schedule, now + timedelta(days=1), "Europe/London")


def test_five_native_dashboard_views_and_every_action_has_valid_schema(household):
    engine, _, _, _ = household
    bindings = {
        key: f"sensor.test_{i}"
        for i, key in enumerate(
            [
                "connected",
                "sync",
                "unassigned",
                "expiry_dependency",
                "activity",
                "protection",
                "calendar",
                *[f"group:child:{k}" for k in ["internet", "enforcement", "next", "devices"]],
            ]
        )
    }
    dashboard = build_dashboard("entry", engine.state, bindings)
    assert [v["path"] for v in dashboard["views"]] == [
        "family",
        "devices",
        "rules",
        "filtering",
        "activity",
    ]

    def walk(value):
        if isinstance(value, dict):
            assert not str(value.get("type", "")).startswith("custom:")
            assert value.get("type") != "iframe"
            if "perform_action" in value:
                service = value["perform_action"].split(".")[1]
                payload = {k: v for k, v in value["data"].items() if k != "entry_id"}
                assert "{{" not in json.dumps(payload)
                SCHEMAS[service](payload)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(dashboard)


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "rejected the API key (HTTP 401)"),
        (403, "denied access (HTTP 403)"),
        (404, "Gateway HTTP 404"),
    ],
)
async def test_gateway_http_errors_are_specific_and_do_not_echo_credentials(status, expected):
    from unittest.mock import MagicMock

    response = MagicMock(status=status)
    response.json = AsyncMock(return_value={"echo": "private-response-content"})
    request = MagicMock()
    request.__aenter__ = AsyncMock(return_value=response)
    request.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.request.return_value = request
    gateway = UniFiGateway(session, "https://example.local", "  private-test-key\n")
    with pytest.raises(
        SimpliFiError, match=expected.replace("(", r"\(").replace(")", r"\)")
    ) as exc:
        await gateway.connect()
    assert "private" not in str(exc.value)
    assert session.request.call_args.kwargs["headers"]["X-API-Key"] == "private-test-key"
    response.json.assert_not_called()


@pytest.mark.parametrize("key", ["", " \n", "abc def", "abc\ndef"])
def test_gateway_rejects_missing_or_malformed_key_without_echo(key):
    with pytest.raises(SimpliFiError, match="complete API key") as exc:
        UniFiGateway(None, "https://example.local", key)
    assert "abc" not in str(exc.value)


async def test_gateway_transport_failure_messages_are_safe():
    from unittest.mock import MagicMock

    import aiohttp

    for error, expected in (
        (aiohttp.ClientConnectionError("private-transport-detail"), "could not connect"),
        (TimeoutError("private-timeout-detail"), "20 seconds"),
        (aiohttp.ServerTimeoutError("private-timeout-detail"), "20 seconds"),
        (aiohttp.ClientSSLError(MagicMock(), OSError("private-tls-detail")), "TLS handshake"),
        (
            aiohttp.ClientConnectorCertificateError(MagicMock(), ValueError("private-cert")),
            "certificate could not be verified",
        ),
    ):
        session = MagicMock()
        session.request.side_effect = error
        with pytest.raises(SimpliFiError, match=expected) as exc:
            await UniFiGateway(session, "https://example.local", "private-key").connect()
        assert "private" not in str(exc.value)


async def test_connect_reports_empty_site_permissions():
    gateway = UniFiGateway(None, "https://example.local", "test")
    gateway.request = AsyncMock(return_value={"applicationVersion": "10.6.106"})
    gateway.pages = AsyncMock(return_value=[])
    with pytest.raises(SimpliFiError, match="no accessible sites"):
        await gateway.connect()


@pytest.mark.parametrize("version", ["10.6.106", "10.6.109"])
async def test_connect_accepts_validated_versions_and_resolves_selected_site(version):
    gateway = UniFiGateway(None, "https://example.local", "test", site="site")
    gateway.request = AsyncMock(return_value={"applicationVersion": version})
    sites = [{"id": "site", "name": "Home", "internalReference": "default"}]
    gateway.pages = AsyncMock(return_value=sites)
    assert await gateway.connect() == sites
    assert gateway.version == version and gateway.legacy_site == "default"
    gateway.pages.assert_awaited_once_with("/v1/sites", cap=100)


@pytest.mark.parametrize("version", ["10.6.110", "11.0.0", None, {}, "private-response-content"])
async def test_connect_rejects_unvalidated_versions_before_site_access_with_safe_reason(version):
    gateway = UniFiGateway(None, "https://example.local", "private-key")
    gateway.request = AsyncMock(return_value={"applicationVersion": version})
    gateway.pages = AsyncMock()
    with pytest.raises(SimpliFiError, match="Supported versions: 10.6.106, 10.6.109") as exc:
        await gateway.connect()
    assert "private" not in str(exc.value)
    assert "HACS" in str(exc.value)
    if version in ("10.6.110", "11.0.0"):
        assert version in str(exc.value)
    gateway.pages.assert_not_awaited()
