"""Validate the API fields we consume; application versions are diagnostic only."""

import re
from copy import deepcopy

from .models import CapabilityError

TESTED_NETWORK_VERSIONS = ("10.6.106", "10.6.109")


def version_label(value):
    """Never put arbitrary response content in diagnostics or error messages."""
    return (
        value
        if isinstance(value, str)
        and re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){2}(?:[-+][A-Za-z0-9.-]{1,24})?", value)
        else "unknown"
    )


def identity(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


def require(condition, resource):
    if not condition:
        raise CapabilityError(
            f"UniFi returned incompatible {resource} data. Policy updates are paused; saved settings are retained"
        )


def validate_sites(rows):
    require(
        all(
            identity(row.get("id"))
            and isinstance(row.get("name"), str)
            and (row.get("internalReference") is None or identity(row["internalReference"]))
            for row in rows
        ),
        "site",
    )


def validate_network(row, zones):
    require(
        identity(row.get("id"))
        and isinstance(row.get("name"), str)
        and (row.get("zoneId") is None or identity(row["zoneId"]) and row["zoneId"] in zones),
        "network",
    )


def validate_catalogue(rows):
    require(
        all(
            type(row.get("id")) is int and row["id"] >= 0 and isinstance(row.get("name"), str)
            for row in rows
        ),
        "application catalogue",
    )


def validate_policy(row):
    # Foreign policies may use selectors SimpliFi never writes. Validate their
    # shared envelope, then retain unknown fields for strict ownership/readback
    # comparison. An unfamiliar semantic field on an owned policy must not be
    # silently dropped by PUT or treated as proof of the requested policy.
    require(
        identity(row.get("id"))
        and isinstance(row.get("name"), str)
        and type(row.get("enabled")) is bool
        and type(row.get("loggingEnabled")) is bool
        and isinstance(row.get("action"), dict)
        and identity(row["action"].get("type"))
        and isinstance(row.get("ipProtocolScope"), dict)
        and identity(row["ipProtocolScope"].get("ipVersion"))
        and all(
            isinstance(row.get(side), dict) and identity(row[side].get("zoneId"))
            for side in ("source", "destination")
        )
        and (row.get("schedule") is None or isinstance(row["schedule"], dict)),
        "firewall policy",
    )


def snapshot(gateway):
    if gateway.simulation:
        return {
            "status": "simulated",
            "application_version": "simulator",
            "features": {},
            "issue": None,
        }
    return deepcopy(gateway.compatibility)
