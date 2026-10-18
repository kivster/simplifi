"""Resolver inheritance and current observation identities, independent of policy state."""

import ipaddress
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .const import STALE_SECONDS
from .models import FamilyError, fingerprint, instant

DEFAULT_SETTINGS = {
    "enabled": True,
    "household_resolver": "",
    "group_resolvers": {},
    "baseline_resolver": "1.1.1.1",
    "freshness_hours": 24,
}


def endpoint(value, *, optional=False):
    if optional and value in (None, ""):
        return ""
    if not isinstance(value, str) or len(value) > 2048:
        raise FamilyError("Use a resolver IP address or HTTPS DNS endpoint")
    value = value.strip()
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.port not in (None, 443, 853)
            ):
                raise ValueError
            host = parsed.hostname.encode("idna").decode("ascii").lower()
            try:
                address = ipaddress.ip_address(host)
                if (
                    address.is_loopback
                    or address.is_link_local
                    or address.is_multicast
                    or address.is_unspecified
                ):
                    raise ValueError
            except ValueError:
                if (
                    ":" in host
                    or host in ("localhost", "metadata.google.internal")
                    or "." not in host
                ):
                    raise ValueError from None
                # Reject forbidden IP literals rather than treating them as DNS names.
                if all(c in "0123456789." for c in host):
                    raise ValueError from None
            authority = f"[{host}]" if ":" in host else host
            if parsed.port not in (None, 443):
                authority += f":{parsed.port}"
            if not parsed.path.startswith("/") or any(c.isspace() for c in value):
                raise ValueError
            return urlunsplit(("https", authority, parsed.path, "", ""))
        except ValueError, UnicodeError:
            raise FamilyError(
                "DoH needs an HTTPS endpoint without credentials, query parameters or redirects"
            ) from None
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        raise FamilyError("Use a reachable unicast DNS server address")
    return str(address)


def settings(data, groups):
    value = {**DEFAULT_SETTINGS, **data}
    if (
        set(value) != set(DEFAULT_SETTINGS)
        or type(value["enabled"]) is not bool
        or type(value["freshness_hours"]) is not int
        or not 1 <= value["freshness_hours"] <= 168
    ):
        raise FamilyError("Invalid DNS settings")
    overrides = value["group_resolvers"]
    if not isinstance(overrides, dict) or not set(overrides) <= set(groups):
        raise FamilyError("Resolver override refers to an unknown person or shared group")
    value["household_resolver"] = endpoint(value["household_resolver"], optional=True)
    value["baseline_resolver"] = endpoint(value["baseline_resolver"])
    value["group_resolvers"] = {k: endpoint(v) for k, v in overrides.items() if v}
    if value["baseline_resolver"] in [
        value["household_resolver"],
        *value["group_resolvers"].values(),
    ]:
        raise FamilyError("Use a reference resolver different from household and person overrides")
    return value


def network_dns(detail):
    """Only an explicit DHCP SERVER has known DNS inheritance; never guess relay."""
    ipv4 = detail.get("ipv4Configuration") or {}
    dhcp = ipv4.get("dhcpConfiguration") or {}
    if dhcp.get("mode") != "SERVER":
        return {
            "resolvers": [],
            "issue": "DHCP DNS is unavailable or supplied by another server",
            "source": "unavailable",
        }
    values = dhcp.get("dnsServerIpAddressesOverride")
    source = "DHCP DNS servers"
    if values is None:
        values = [ipv4.get("hostIpAddress")]
        source = "UniFi automatic DNS (network gateway)"
    if not isinstance(values, list) or not values or len(values) > 4:
        return {
            "resolvers": [],
            "issue": "DHCP DNS response is incomplete",
            "source": "unavailable",
        }
    try:
        addresses = sorted({str(ipaddress.ip_address(v)) for v in values})
        for value in addresses:
            endpoint(value)
    except ValueError, TypeError, FamilyError:
        return {
            "resolvers": [],
            "issue": "DHCP returned an invalid DNS address",
            "source": "unavailable",
        }
    return {"resolvers": addresses, "source": source, "issue": None}


def contexts(state, networks, probe, group_id=None, now=None):
    cfg = settings(state.dns_settings, state.groups)
    override = (
        probe.get("resolver") or cfg["group_resolvers"].get(group_id) or cfg["household_resolver"]
    )
    source = (
        "List override"
        if probe.get("resolver")
        else "Person override"
        if cfg["group_resolvers"].get(group_id)
        else "Household default"
    )
    if override:
        return {
            "contexts": [{"resolver": override, "source": source, "networks": []}],
            "issues": [],
        }
    selected = sorted(
        {
            d.network
            for d in state.devices.values()
            if d.network in state.networks and (group_id is None or d.group == group_id)
        }
    )
    issues = []
    if not selected:
        issues.append(
            "No assigned device network is available"
            if group_id
            else "No discovered device network is available"
        )
    if not state.inventory_complete or (
        now is not None
        and (
            not state.last_observed
            or now - instant(state.last_observed) >= timedelta(seconds=STALE_SECONDS)
        )
    ):
        issues.append("Device network discovery is not current")
    if group_id and any(
        d.group == group_id and d.network not in state.networks for d in state.devices.values()
    ):
        issues.append("Some assigned devices have no current managed-network identity")
    by_endpoint: dict[str, dict[str, Any]] = {}
    for key in selected:
        network = networks.get(key, {})
        dns = network.get("dns", {})
        if dns.get("issue") or not dns.get("resolvers"):
            issues.append(
                f"{network.get('name', 'Unknown network')}: {dns.get('issue') or 'DNS servers not discovered'}"
            )
            continue
        for resolver in dns["resolvers"]:
            row = by_endpoint.setdefault(
                resolver, {"resolver": resolver, "source": dns["source"], "networks": []}
            )
            row["networks"].append(network.get("name", key))
    return {"contexts": list(by_endpoint.values()), "issues": issues}


def job_spec(state, probe, resolver):
    from .dns_checks import validate_probe

    probe = {**probe, **validate_probe(probe)}
    return {
        **probe,
        "resolver": resolver,
        "baseline_resolver": probe.get("baseline_resolver")
        or state.dns_settings["baseline_resolver"],
        "freshness_hours": state.dns_settings["freshness_hours"],
        "dns_revision": state.dns_revision,
    }


def context_key(resolver):
    return fingerprint(resolver)[:24]


def observation(state, networks, probe_id, group_id, now):
    """Recompute context/signature every read; old results cannot regain validity."""
    probe = state.probes[probe_id]
    ctx = contexts(state, networks, probe, group_id, now)
    rows = []
    disabled = not state.dns_settings["enabled"] or not probe.get("enabled", True)
    stored = state.probe_results.get(probe_id, {}).get("contexts", {})
    for context in ctx["contexts"]:
        result = stored.get(context_key(context["resolver"]))
        spec = job_spec(state, probe, context["resolver"])
        fresh = bool(
            not disabled
            and result
            and result.get("configuration_hash") == fingerprint(spec)
            and instant(result["expires_at"]) > now
            and instant(result["timestamp"]) <= now + timedelta(seconds=5)
        )
        row = {
            **context,
            "fresh": fresh,
            "verdict": result["verdict"] if fresh else "unknown",
            "issue": "DNS checks are disabled"
            if disabled
            else (
                result.get("issue")
                or (
                    "; ".join(
                        dict.fromkeys(
                            row.get("reason", "Inconclusive sample")
                            for row in result.get("domains", [])
                            if row["verdict"] == "unknown"
                        )
                    )
                    if result["verdict"] == "unknown"
                    else None
                )
            )
            if fresh
            else "Observation is stale or settings changed"
            if result
            else "Not checked yet",
        }
        rows.append(row)
    values = {r["verdict"] for r in rows}
    verdict = (
        "unknown"
        if disabled or ctx["issues"] or not values or "unknown" in values
        else "partial"
        if len(values) > 1 or "partial" in values
        else next(iter(values))
    )
    return {
        "verdict": verdict,
        "contexts": rows,
        "issues": ["DNS checks are disabled"] if disabled else ctx["issues"],
        "enabled": not disabled,
    }


def jobs(state, networks, probe_id=None, group_id=None):
    if not state.dns_settings["enabled"]:
        raise FamilyError("Enable DNS observations in Resolver settings first")
    if probe_id and probe_id not in state.probes:
        raise FamilyError("Unknown DNS list")
    if group_id and group_id not in state.groups:
        raise FamilyError("Unknown person or shared group")
    result = {}
    for key, probe in state.probes.items():
        if probe_id and key != probe_id or not probe.get("enabled", True):
            continue
        targets = (
            [group_id]
            if group_id
            else [probe.get("group_id")]
            if probe.get("group_id")
            else [None, *[g.id for g in state.groups.values() if not g.archived]]
        )
        for group in targets:
            if probe.get("group_id") and group != probe["group_id"]:
                continue
            for row in contexts(state, networks, probe, group)["contexts"]:
                spec = job_spec(state, probe, row["resolver"])
                result[(key, context_key(row["resolver"]))] = spec
    if len(result) > 128:
        raise FamilyError("Too many resolver/list combinations; check one list or person at a time")
    return result
