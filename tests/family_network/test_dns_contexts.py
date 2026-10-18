"""Observation identity, inheritance and wire evidence must never imply client proof."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import dns.edns
import dns.message
import dns.rrset
import pytest

from custom_components.family_network import dns_checks
from custom_components.family_network.dns_catalog import CATEGORIES, ensure_seeds
from custom_components.family_network.dns_checks import (
    QueryCache,
    aggregate,
    query,
    run_probe,
    verdict,
)
from custom_components.family_network.dns_context import (
    contexts,
    endpoint,
    jobs,
    network_dns,
    observation,
)
from custom_components.family_network.filter_status import category_marks
from custom_components.family_network.models import Conflict, FamilyError, Group, State
from custom_components.family_network.protection import normalize_profiles

from .conftest import command


def answer(address="192.0.2.5", ede=(), status="answer"):
    return {"status": status, "addresses": [address] if address else [], "ede": list(ede)}


def profile():
    return {
        "_id": "family",
        "name": "Family",
        "enabled": True,
        "network_ids": ["legacy"],
        "client_macs": [],
        "categories": ["ADULT", "ANONYMIZERS"],
        "safe_search": ["GOOGLE"],
        "allow_list": ["example.com"],
        "block_list": [],
        "schedule": {"mode": "ALWAYS"},
    }


@pytest.mark.parametrize(
    "value",
    [
        "http://dns.example/query",
        "https://u:p@dns.example/query",
        "https://dns.example/query?secret=bad",
        "https://127.0.0.1/query",
        "https://[::1]/query",
        "169.254.169.254",
        "::",
        "https://localhost/query",
    ],
)
def test_resolver_validation_rejects_unsupported_endpoints(value):
    with pytest.raises(FamilyError):
        endpoint(value)


def test_resolver_canonicalization():
    assert endpoint("https://DNS.EXAMPLE:443/dns-query") == "https://dns.example/dns-query"
    assert endpoint("2001:db8:0::53") == "2001:db8::53"
    assert endpoint("", optional=True) == ""


def test_dhcp_discovery_uses_override_or_network_gateway_without_guessing_relay():
    detail = {
        "ipv4Configuration": {"hostIpAddress": "192.0.2.1", "dhcpConfiguration": {"mode": "SERVER"}}
    }
    assert network_dns(detail)["resolvers"] == ["192.0.2.1"]
    detail["ipv4Configuration"]["dhcpConfiguration"]["dnsServerIpAddressesOverride"] = [
        "192.0.2.54",
        "192.0.2.53",
    ]
    assert network_dns(detail)["resolvers"] == ["192.0.2.53", "192.0.2.54"]
    detail["ipv4Configuration"]["dhcpConfiguration"]["mode"] = "RELAY"
    assert not network_dns(detail)["resolvers"]
    assert not network_dns({})["resolvers"]


async def test_inheritance_jobs_share_endpoints_and_keep_unknown_networks_visible(household):
    engine, gateway, _, _ = household
    ensure_seeds(engine.state)
    probe = engine.state.probes["builtin:video"]
    engine.state.groups["other"] = Group("other", "Other")
    assert len(jobs(engine.state, gateway.networks)) == len(CATEGORIES)
    assert (
        contexts(engine.state, gateway.networks, probe, "child")["contexts"][0]["resolver"]
        == "192.0.2.53"
    )
    engine.state.dns_settings["household_resolver"] = "https://dns.example/dns-query"
    assert (
        contexts(engine.state, gateway.networks, probe, "child")["contexts"][0]["source"]
        == "Household default"
    )
    engine.state.dns_settings["group_resolvers"]["child"] = "192.0.2.54"
    assert (
        contexts(engine.state, gateway.networks, probe, "child")["contexts"][0]["source"]
        == "Person override"
    )
    probe["resolver"] = "192.0.2.55"
    assert (
        contexts(engine.state, gateway.networks, probe, "child")["contexts"][0]["resolver"]
        == "192.0.2.55"
    )
    probe["resolver"] = ""
    engine.state.dns_settings["household_resolver"] = ""
    engine.state.dns_settings["group_resolvers"] = {}
    unknown = contexts(engine.state, {}, probe, "child")
    assert unknown["issues"] and not unknown["contexts"]


async def test_dns_changes_never_change_enforcement_revision_or_confirmation(household):
    engine, gateway, _, _ = household
    await command(engine, "set_management", enabled=True)
    await engine.refresh()
    before = (
        engine.state.revision,
        engine.state.confirmed_revision,
        engine.state.sync_status,
        deepcopy(gateway.policies),
    )
    ensure_seeds(engine.state)
    await command(
        engine, "upsert_probe", probe_id="builtin:video", name="Video", domains=["youtube.com"]
    )
    assert (
        engine.state.revision,
        engine.state.confirmed_revision,
        engine.state.sync_status,
        gateway.policies,
    ) == before
    assert engine.state.dns_revision == 1
    await command(engine, "check_dns", probe_id="builtin:video")
    assert engine.state.dns_revision == 1 and engine.state.revision == before[0]
    with pytest.raises(Conflict, match="DNS settings changed"):
        await command(engine, "delete_probe", probe_id="builtin:video", expected_dns_revision=0)


async def test_seeds_retain_removals_disable_restore_and_restart(household):
    engine, _, _, _ = household
    ensure_seeds(engine.state)
    await command(
        engine,
        "upsert_probe",
        probe_id="builtin:video",
        name="Video",
        domains=["youtube.com", "custom.example"],
    )
    assert "netflix.com" in engine.state.probes["builtin:video"]["removed_seed_domains"]
    engine.state = State.from_dict(engine.state.to_dict())
    ensure_seeds(engine.state)
    assert engine.state.probes["builtin:video"]["domains"] == ["custom.example", "youtube.com"]
    await command(engine, "delete_probe", probe_id="builtin:video")
    ensure_seeds(engine.state)
    assert not engine.state.probes["builtin:video"]["enabled"]
    await command(engine, "restore_probe", probe_id="builtin:video")
    assert set(engine.state.probes["builtin:video"]["domains"]) == {
        *CATEGORIES["video"]["domains"],
        "custom.example",
    }
    assert engine.state.probes["builtin:video"]["enabled"]


def test_seed_collision_preserves_custom_domains(household):
    engine, _, _, _ = household
    engine.state.probes["builtin:video"] = {
        "name": "Mine",
        "domains": ["my.example"],
        "revision": 1,
    }
    ensure_seeds(engine.state)
    assert engine.state.probes["builtin:video:custom"]["domains"] == ["my.example"]
    assert engine.state.probes["builtin:video"]["seed"] == "video"


async def test_result_identity_expires_and_invalidates_on_inheritance_or_disable(household):
    engine, gateway, now, _ = household
    ensure_seeds(engine.state)
    key, context = next(iter(jobs(engine.state, gateway.networks, "builtin:video")))
    spec = jobs(engine.state, gateway.networks, key)[key, context]
    result = await dns_checks.simulated_probe(spec, now[0])
    engine.state.probe_results[key] = {"contexts": {context: result}}
    assert observation(engine.state, gateway.networks, key, "child", now[0])["verdict"] == "blocked"
    assert (
        observation(engine.state, gateway.networks, key, "child", now[0] + timedelta(hours=25))[
            "verdict"
        ]
        == "unknown"
    )
    engine.state.dns_settings["group_resolvers"]["child"] = "192.0.2.54"
    assert observation(engine.state, gateway.networks, key, "child", now[0])["verdict"] == "unknown"
    engine.state.dns_settings["group_resolvers"] = {}
    engine.state.dns_settings["enabled"] = False
    assert observation(engine.state, gateway.networks, key, "child", now[0])["verdict"] == "unknown"


def test_legacy_network_identity_and_category_configuration_are_not_traffic_proof(household):
    engine, gateway, now, _ = household
    legacy = {
        "data": [{"_id": "legacy", "name": "Duplicate-friendly-name", "ip_subnet": "192.0.2.1/24"}]
    }
    profiles = normalize_profiles({"data": [profile()]}, legacy, gateway.networks)
    assert profiles[0]["networks"][0]["official_id"] == "demo-family"
    protection = {"fresh": True, "profiles": profiles}
    marks, inherited = category_marks(
        engine.state,
        gateway.networks,
        "child",
        protection,
        False,
        gateway.catalogues["category"],
        now[0],
    )
    vpn = next(c for c in marks if c["slug"] == "vpn")
    assert vpn["label"] == "Filter configured" and vpn["dns"]["verdict"] == "unknown"
    assert inherited["profiles"][0]["safe_search"] == ["GOOGLE"]
    assert any("exceptions" in reason for reason in vpn["reasons"])
    legacy["data"].append({"_id": "duplicate", "name": "Other", "ip_subnet": "192.0.2.0/24"})
    profiles = normalize_profiles({"data": [profile()]}, legacy, gateway.networks)
    assert profiles[0]["networks"][0]["official_id"] is None
    protection = {"fresh": False, "profiles": profiles}
    marks, inherited = category_marks(
        engine.state,
        gateway.networks,
        "child",
        protection,
        True,
        gateway.catalogues["category"],
        now[0],
    )
    assert all(m["label"] != "Filter configured" for m in marks)
    assert not inherited["complete"]


@pytest.mark.parametrize(
    "code,expected",
    [
        (15, "blocked"),
        (16, "blocked"),
        (17, "blocked"),
        (18, "unknown"),
        (6, "unknown"),
        (23, "unknown"),
    ],
)
def test_extended_errors_distinguish_filtering_block_pages_from_prohibited_or_failed(
    code, expected
):
    reference = {"A": answer(), "AAAA": answer(None, status="no_answer")}
    observed = {"A": answer("192.0.2.99", [code]), "AAAA": answer(None, status="no_answer")}
    assert verdict(reference, observed) == expected


def test_ipv6_bypass_and_empty_results_never_claim_blocked():
    reference = {"A": answer(), "AAAA": answer(None, status="no_answer")}
    observed = {"A": answer("0.0.0.0", [15]), "AAAA": answer("2001:db8::1")}
    assert verdict(reference, observed) == "open"
    assert aggregate([]) == "unknown"
    assert aggregate(["blocked", "open"]) == "partial"
    assert aggregate(["blocked", "unknown"]) == "unknown"


async def test_shared_query_cache_sends_one_request_per_endpoint_name_type(monkeypatch):
    fetch = AsyncMock(return_value=answer())
    monkeypatch.setattr(dns_checks, "query", fetch)
    cache = QueryCache(None)
    await asyncio.gather(*(cache("192.0.2.53", "example.com", "A") for _ in range(10)))
    assert fetch.call_count == 1
    await cache.close()


class Content:
    def __init__(self, wire):
        self.wire = wire

    async def iter_chunked(self, size):
        # Deliberately split a DNS packet across reads.
        for pos in range(0, len(self.wire), 7):
            yield self.wire[pos : pos + 7]


class Response:
    status = 200
    content_type = "application/dns-message"

    def __init__(self, wire):
        self.content = Content(wire)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("valid", "answer"),
        ("wrong_question", "error"),
        ("oversize", "error"),
        ("redirect", "error"),
        ("wrong_type", "error"),
    ],
)
async def test_doh_wire_protocol_validates_body_identity_and_limits(mode, expected):
    captured = {}

    def post(url, **kwargs):
        captured.update(kwargs)
        request = dns.message.from_wire(kwargs["data"])
        assert request.edns == 0 and request.id == 0
        response = dns.message.make_response(request)
        response.answer.append(dns.rrset.from_text("example.org.", 30, "IN", "A", "192.0.2.99"))
        response.use_edns(options=[dns.edns.EDEOption(15)])
        if mode == "wrong_question":
            response.question = dns.message.make_query("other.example", "A").question
        result = Response(b"x" * 65536 if mode == "oversize" else response.to_wire())
        if mode == "redirect":
            result.status = 302
        if mode == "wrong_type":
            result.content_type = "text/html"
        return result

    result = await query(
        "https://dns.example/dns-query", "example.org", "A", SimpleNamespace(post=post)
    )
    assert result["status"] == expected
    assert captured["allow_redirects"] is False
    assert captured["headers"]["Content-Type"] == "application/dns-message"
    if mode == "valid":
        assert result["ede"] == [15]


async def test_plain_dns_requests_edns_and_uses_tcp_fallback(monkeypatch):
    async def udp(request, address, **kwargs):
        assert request.edns == 0 and address == "192.0.2.53"
        response = dns.message.make_response(request)
        response.answer.append(dns.rrset.from_text("example.org.", 30, "IN", "A", "192.0.2.9"))
        return response, True

    monkeypatch.setattr(dns_checks.dns.asyncquery, "udp_with_fallback", udp)
    assert (await query("192.0.2.53", "example.org", "A"))["addresses"] == ["192.0.2.9"]
    monkeypatch.setattr(
        dns_checks.dns.asyncquery, "udp_with_fallback", AsyncMock(side_effect=TimeoutError)
    )
    assert (await query("192.0.2.53", "example.org", "A"))["status"] == "error"


async def test_failed_control_cannot_become_category_success():
    async def fetch(address, domain, kind):
        return answer(None, status="error") if domain == "example.com" else answer("0.0.0.0", [15])

    result = await run_probe(
        {
            "name": "Example",
            "domains": ["example.org"],
            "resolver": "192.0.2.53",
            "baseline_resolver": "192.0.2.54",
        },
        fetch,
    )
    assert result["verdict"] == "unknown"
    assert result["issue"] and result["domains"][0]["verdict"] == "unknown"
