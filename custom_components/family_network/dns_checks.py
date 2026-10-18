"""Bounded DNS/DoH wire observations from HA; never device enforcement proof."""

import asyncio
from datetime import timedelta
from zoneinfo import ZoneInfo

import aiohttp
import dns.asyncquery
import dns.edns
import dns.exception
import dns.message
import dns.rcode
import dns.rdatatype

from .dns_catalog import CATEGORIES
from .dns_context import endpoint
from .models import FamilyError, domain_name, fingerprint, instant, utcnow
from .schedule import wall_instant


def validate_probe(data: dict) -> dict:
    domains = data.get("domains", [])
    if (
        not isinstance(data.get("name"), str)
        or not data["name"].strip()
        or len(data["name"]) > 100
        or not isinstance(domains, list)
        or len(domains) > 1000
    ):
        raise FamilyError("DNS list requires a name and at most 1,000 sample domains")
    resolver = endpoint(data.get("resolver", ""), optional=True)
    baseline = endpoint(data.get("baseline_resolver", ""), optional=True)
    if resolver and resolver == baseline:
        raise FamilyError("Use a separate reference resolver to compare filtering")
    category = data.get("category", "custom")
    if category not in (*CATEGORIES, "custom") or type(data.get("enabled", True)) is not bool:
        raise FamilyError("Invalid DNS category or enabled state")
    return {
        "name": data["name"].strip(),
        "domains": sorted({domain_name(d) for d in domains}),
        "resolver": resolver,
        "baseline_resolver": baseline,
        "group_id": data.get("group_id") or None,
        "vantage": "Home Assistant host network",
        "category": category,
        "enabled": data.get("enabled", True),
    }


def decode_answer(message, kind):
    codes = [
        int(option.code) for option in message.options if isinstance(option, dns.edns.EDEOption)
    ]
    rcode = message.rcode()
    addresses = [
        item.to_text()
        for rrset in message.answer
        if rrset.rdtype == dns.rdatatype.from_text(kind)
        for item in rrset
    ]
    status = "answer" if addresses else "no_answer"
    if rcode == dns.rcode.NXDOMAIN:
        status = "nxdomain"
    elif rcode != dns.rcode.NOERROR:
        status = "error"
    return {
        "status": status,
        "addresses": addresses,
        "ede": codes,
        "rcode": dns.rcode.to_text(rcode),
    }


async def query(address: str, domain: str, kind: str, session=None) -> dict:
    """EDNS is essential: filtering EDE may accompany a routable block-page IP."""
    request = dns.message.make_query(domain, kind, use_edns=0, payload=1232)
    try:
        address = endpoint(address)
        if address.startswith("https://"):
            request.id = 0
            if session is None:
                async with aiohttp.ClientSession() as owned_session:
                    return await query(address, domain, kind, owned_session)
            async with session.post(
                address,
                data=request.to_wire(),
                headers={
                    "Content-Type": "application/dns-message",
                    "Accept": "application/dns-message",
                },
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=6),
            ) as response:
                if response.status != 200 or response.content_type != "application/dns-message":
                    return {
                        "status": "error",
                        "addresses": [],
                        "ede": [],
                        "issue": "DoH returned an unexpected status or content type",
                    }
                wire = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    wire.extend(chunk)
                    if len(wire) > 65535:
                        return {
                            "status": "error",
                            "addresses": [],
                            "ede": [],
                            "issue": "DoH response exceeded the DNS message limit",
                        }
                message = dns.message.from_wire(bytes(wire))
                if not request.is_response(message):
                    return {
                        "status": "error",
                        "addresses": [],
                        "ede": [],
                        "issue": "DoH response did not match the query",
                    }
        else:
            message, _ = await dns.asyncquery.udp_with_fallback(request, address, timeout=4)
        return decode_answer(message, kind)
    except (
        dns.exception.DNSException,
        aiohttp.ClientError,
        OSError,
        TimeoutError,
        ValueError,
        FamilyError,
    ):
        return {
            "status": "error",
            "addresses": [],
            "ede": [],
            "issue": "DNS request failed or timed out",
        }


def answer_state(value):
    ede = set(value.get("ede", []))
    if ede & {15, 16, 17}:
        return "blocked"
    if value["status"] == "error" or ede & {
        3,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
    }:
        return "unknown"
    addresses = value.get("addresses", [])
    if addresses:
        return "open" if any(a not in {"0.0.0.0", "::"} for a in addresses) else "blocked"
    return "negative"


def verdict(reference: dict, observed: dict) -> str:
    obs = [answer_state(v) for v in observed.values()]
    if "unknown" in obs:
        return "unknown"
    if "open" in obs:
        # A usable answer in either address family prevents a blocked claim.
        return "open" if any(answer_state(v) == "open" for v in reference.values()) else "unknown"
    if "blocked" in obs:
        if any(set(v.get("ede", [])) & {15, 16, 17} for v in observed.values()):
            return "blocked"
        if any(answer_state(v) == "unknown" for v in reference.values()):
            return "unknown"
        if any(answer_state(v) == "open" for v in reference.values()) and all(
            v["status"] in ("answer", "no_answer") for v in observed.values()
        ):
            return "blocked"
    return "unknown"  # Bare NXDOMAIN/NODATA is not unambiguous filtering evidence.


def explanation(reference, observed):
    codes = sorted({code for value in observed.values() for code in value.get("ede", [])})
    if set(codes) & {15, 16, 17}:
        return (
            "Resolver reported filtering for one query, but another address family resolves"
            if verdict(reference, observed) == "open"
            else "Resolver explicitly reported filtering (extended DNS error)"
        )
    if 18 in codes:
        return "Resolver prohibited this client; category filtering cannot be inferred"
    if any(v["status"] == "error" for v in [*reference.values(), *observed.values()]):
        return "A resolver failed or did not answer; filtering cannot be confirmed"
    if any(v["status"] == "nxdomain" for v in observed.values()):
        return "Resolver reports no such name; this may be filtering or a DNS difference"
    if verdict(reference, observed) == "blocked":
        return "Sinkhole response; the reference resolver returned a usable address"
    if verdict(reference, observed) == "open":
        return "A sample name resolves; this does not test app traffic or client access"
    return "No usable comparison; filtering cannot be confirmed"


def aggregate(values):
    values = set(values)
    return (
        "unknown"
        if not values or "unknown" in values
        else "partial"
        if len(values) > 1 or "partial" in values
        else next(iter(values))
    )


async def run_probe(probe: dict, query_fn=None, now=None) -> dict:
    # Validate submitted fields but retain the full job identity for invalidation.
    normalized = validate_probe(probe)
    if not normalized["resolver"] or not normalized["baseline_resolver"]:
        raise FamilyError("Resolve the effective DNS context before checking")
    probe = {**probe, **normalized}
    query_fn = query_fn or query
    semaphore = asyncio.Semaphore(4)

    async def domain_check(domain):
        async with semaphore:
            values = await asyncio.gather(
                *(
                    query_fn(address, domain, kind)
                    for address in (probe["baseline_resolver"], probe["resolver"])
                    for kind in ("A", "AAAA")
                )
            )
            reference = dict(zip(("A", "AAAA"), values[:2], strict=True))
            observed = dict(zip(("A", "AAAA"), values[2:], strict=True))
            return {
                "domain": domain,
                "verdict": verdict(reference, observed),
                "reason": explanation(reference, observed),
                "reference": reference,
                "observed": observed,
            }

    controls = await asyncio.gather(
        query_fn(probe["resolver"], "example.com", "A"),
        query_fn(probe["baseline_resolver"], "example.com", "A"),
    )
    rows = await asyncio.gather(*(domain_check(d) for d in probe["domains"]))
    controls_ok = all(answer_state(c) == "open" for c in controls)
    issue = (
        None
        if controls_ok
        else "A known-resolving control failed; this check cannot establish filtering"
    )
    if not controls_ok:
        for row in rows:
            row["verdict"] = "unknown"
            row["reason"] = issue
    at = now or utcnow()
    return {
        "revision": probe.get("revision", 0),
        "configuration_hash": fingerprint(probe),
        "verdict": aggregate(row["verdict"] for row in rows),
        "timestamp": at.isoformat(),
        "expires_at": (at + timedelta(hours=probe.get("freshness_hours", 24))).isoformat(),
        "resolver": probe["resolver"],
        "vantage": "Home Assistant host network",
        "controls": controls,
        "domains": rows,
        "issue": issue,
    }


class QueryCache:
    """Deduplicate endpoint/domain/type requests across groups/lists in one sweep."""

    def __init__(self, session):
        self.session = session
        self.tasks = {}
        self.limit = asyncio.Semaphore(8)

    async def __call__(self, resolver, domain, kind):
        key = (resolver, domain, kind)
        if key not in self.tasks:

            async def run():
                async with self.limit:
                    return await query(resolver, domain, kind, self.session)

            self.tasks[key] = asyncio.create_task(run())
        return await self.tasks[key]

    async def close(self):
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)


async def simulated_probe(probe: dict, now=None) -> dict:
    async def fixture_query(address, domain, kind):
        if domain == "example.com" or address == probe["baseline_resolver"]:
            return {
                "status": "answer",
                "addresses": ["192.0.2.100" if kind == "A" else "2001:db8::100"],
                "ede": [],
            }
        return {"status": "answer", "addresses": ["0.0.0.0" if kind == "A" else "::"], "ede": [15]}

    result = await run_probe(probe, query_fn=fixture_query, now=now)
    result["vantage"] = "Offline simulator; no DNS queries sent"
    result["simulation"] = True
    return result


def due_claim(schedule: dict, now, timezone: str) -> str | None:
    if not schedule.get("enabled"):
        return None
    zone = ZoneInfo(timezone)
    today = now.astimezone(zone).date()
    # One bounded daily catch-up; no replay of a week's missed probes.
    for day in (today, today - timedelta(days=1)):
        if day.weekday() not in schedule["days"]:
            continue
        due = wall_instant(day, schedule["time"], zone, end=False)
        if due <= now < due + timedelta(days=1):
            key = due.isoformat()
            return (
                key
                if not schedule.get("last_claim") or instant(schedule["last_claim"]) < due
                else None
            )
    return None
