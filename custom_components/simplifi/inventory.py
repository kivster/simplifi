"""Official network mapping and optional local IEEE registrant observations."""

import gzip
import ipaddress
import json
from functools import lru_cache
from pathlib import Path

from .models import CapabilityError, SimpliFiError


def network_subnets(detail: dict) -> list[str]:
    """Use explicit configured subnets only; never infer a delegated IPv6 prefix."""
    result = []
    try:
        for version in (4, 6):
            config = detail.get(f"ipv{version}Configuration") or {}
            values = list(config.get("additionalHostIpSubnets") or [])
            if config.get("hostIpAddress") is not None and config.get("prefixLength") is not None:
                values.insert(0, f"{config['hostIpAddress']}/{config['prefixLength']}")
            for value in values:
                subnet = ipaddress.ip_network(value, strict=False)
                if subnet.version != version:
                    raise ValueError
                if str(subnet) not in result:
                    result.append(str(subnet))
    except TypeError, ValueError:
        raise SimpliFiError("Invalid network subnet metadata; discovery incomplete") from None
    return result


def client_references(payload: dict) -> set[str]:
    """The references endpoint is unpaginated; enforce its advertised counts."""
    if not isinstance(payload, dict) or not isinstance(payload.get("referenceResources"), list):
        raise SimpliFiError("Invalid network references; discovery incomplete")
    result: set[str] = set()
    for resource in payload["referenceResources"]:
        if not isinstance(resource, dict):
            raise SimpliFiError("Invalid network references; discovery incomplete")
        if resource.get("resourceType") != "CLIENT":
            continue
        rows = resource.get("references")
        count = resource.get("referenceCount")
        if not isinstance(rows, list) or type(count) is not int or count != len(rows):
            raise SimpliFiError("Truncated client references; discovery incomplete")
        ids = [r.get("referenceId") if isinstance(r, dict) else None for r in rows]
        if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
            raise SimpliFiError("Invalid client reference identities")
        result.update(key for key in ids if isinstance(key, str))
    return result


def client_network(
    client_id: str, address, networks: dict, references: dict, current: str | None = None
) -> tuple[str, str]:
    direct = [key for key, ids in references.items() if client_id in ids]
    # CLIENT references include fixed-IP configuration, even when the device is
    # currently connected to a different VLAN. They cannot prove current scope.
    matches = [
        key
        for key, network in networks.items()
        if address
        and not address.is_link_local
        and any(address in ipaddress.ip_network(subnet) for subnet in network["subnets"])
    ]
    if current is not None:
        if current not in networks or (matches and current not in matches):
            raise CapabilityError(
                "Current connection and IP subnet disagree; scoped discovery is incomplete"
            )
        # An explicit current connection resolves absent or overlapping subnets.
        source = "subnet_and_current_network_id" if len(matches) == 1 else "current_network_id"
        if direct and direct != [current]:
            source += "_reference_differs"
        return current, source
    if len(matches) != 1:
        raise CapabilityError(
            "Unmapped or ambiguous client network; scoped discovery is incomplete"
        )
    network = matches[0]
    source = (
        "subnet_and_reference"
        if direct == [network]
        else "subnet_observation_reference_differs"
        if direct
        else "subnet_observation"
    )
    return network, source


@lru_cache(maxsize=1)
def registrant_database() -> dict:
    """Read once in an executor, with no runtime network lookup."""
    with gzip.open(Path(__file__).with_name("data") / "mac-registrants.json.gz", "rt") as source:
        return json.load(source)["assignments"]


def mac_registrant(mac: str, assignments: dict) -> tuple[str | None, str]:
    if int(mac[:2], 16) & 2:
        return None, "private"
    digits = mac.replace(":", "").upper()
    for length in (9, 7, 6):
        if name := assignments.get(digits[:length]):
            return (None, "ambiguous") if isinstance(name, list) else (name, "registered")
    return None, "unlisted"
