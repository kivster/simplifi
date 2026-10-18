"""Durable, JSON-compatible household records. No gateway or HA dependencies."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from .const import SCHEMA_VERSION


class FamilyError(Exception):
    """A safe, user-facing error; never includes an HTTP body or credentials."""


class Conflict(FamilyError):
    """Concurrent edit, ownership drift or unresolved external write."""


class CapabilityError(FamilyError):
    """The selected adapter cannot safely deliver this operation."""


def uid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


def instant(value: str | datetime) -> datetime:
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        raise FamilyError("Deadline must include a timezone")
    return dt.astimezone(UTC)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def domain_name(value: str) -> str:
    if not isinstance(value, str) or len(value) > 253:
        raise FamilyError("Invalid domain")
    try:
        name = value.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as err:
        raise FamilyError("Invalid domain") from err
    try:
        ipaddress.ip_address(name)
    except ValueError:
        pass
    else:
        raise FamilyError("Enter a domain, not an IP address")
    if "." not in name or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in name.split(".")
    ):
        raise FamilyError("Enter a domain without URLs, paths or wildcards")
    return name


def mac_address(value: str) -> str:
    value = value.lower().replace("-", ":")
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", value):
        raise FamilyError("Invalid MAC address")
    if int(value[:2], 16) & 1 or value == "00:00:00:00:00:00":
        raise FamilyError("Client MAC must be unicast and nonzero")
    return value


@dataclass
class Window:
    id: str
    name: str
    days: list[int]
    start: str = "00:00"
    end: str = "00:00"
    all_day: bool = False
    overnight: bool = False

    def validate(self) -> None:
        if (
            not self.days
            or len(set(self.days)) != len(self.days)
            or any(type(d) is not int or not 0 <= d <= 6 for d in self.days)
        ):
            raise FamilyError("Select unique start weekdays (Monday=0)")
        for value in (self.start, self.end):
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                raise FamilyError("Time must use HH:MM")
        if self.all_day:
            if self.overnight:
                raise FamilyError("All-day windows do not use overnight")
        elif self.start == self.end or self.overnight != (self.end < self.start):
            raise FamilyError("Select overnight explicitly for a window crossing midnight")


@dataclass
class Group:
    id: str
    name: str
    kind: str = "family"
    age: str | None = None
    person: str | None = None
    archived: bool = False


@dataclass
class Device:
    id: str
    mac: str
    name: str
    network: str | None
    group: str | None = None
    connected: bool = False
    last_seen: str | None = None
    ip: str | None = None
    uplink: str | None = None
    kind: str = "unknown"
    connected_at: str | None = None
    uplink_name: str | None = None
    network_source: str | None = None
    registrant: str | None = None
    registrant_status: str = "unavailable"


@dataclass
class Rule:
    id: str
    name: str
    kind: str
    groups: list[str]
    targets: list[str | int] = field(default_factory=list)
    windows: list[Window] = field(default_factory=list)
    enabled: bool = True
    networks: list[str] = field(default_factory=list)


@dataclass
class ExceptionRecord:
    id: str
    kind: str
    group: str | None
    rule: str | None
    captured: list[str]
    created_at: str
    expires_at: str | None
    actor: str
    reason: str

    def active(self, now: datetime) -> bool:
        return self.expires_at is None or instant(self.expires_at) > now


@dataclass
class State:
    controller: str
    site: str
    networks: list[str]
    timezone: str = "Europe/London"
    schema: int = SCHEMA_VERSION
    revision: int = 0
    confirmed_revision: int | None = None
    management: bool = False
    expiry_acknowledged: bool = False
    gateway_timezone_confirmed: bool = False
    quarantine: bool = False
    quarantine_excluded: list[str] = field(default_factory=list)
    quarantine_until: str | None = None
    quarantine_suspended: bool = False
    groups: dict[str, Group] = field(default_factory=dict)
    devices: dict[str, Device] = field(default_factory=dict)
    rules: dict[str, Rule] = field(default_factory=dict)
    exceptions: dict[str, ExceptionRecord] = field(default_factory=dict)
    owned: dict[str, dict[str, Any]] = field(default_factory=dict)
    journal: list[dict[str, Any]] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)
    audit_days: int = 30
    probes: dict[str, dict[str, Any]] = field(default_factory=dict)
    probe_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    dns_revision: int = 0
    dns_settings: dict[str, Any] = field(
        default_factory=lambda: {
            "enabled": True,
            "household_resolver": "",
            "group_resolvers": {},
            "baseline_resolver": "1.1.1.1",
            "freshness_hours": 24,
        }
    )
    probe_schedule: dict[str, Any] = field(
        default_factory=lambda: {
            "enabled": False,
            "days": list(range(7)),
            "time": "08:00",
            "last_claim": None,
        }
    )
    last_observed: str | None = None
    inventory_complete: bool = False
    sync_status: str = "unavailable"
    issue: str | None = None
    binding_token: str | None = None
    access_revision: int = 0
    access_grants: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        if data.get("schema") != SCHEMA_VERSION:
            raise FamilyError("Unsupported storage schema; preserve the original backup")
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise FamilyError("Unexpected state fields")
        raw = dict(data)
        raw.setdefault("quarantine_suspended", bool(data.get("quarantine_until")))
        raw["groups"] = {k: Group(**v) for k, v in data.get("groups", {}).items()}
        raw["devices"] = {k: Device(**v) for k, v in data.get("devices", {}).items()}
        raw["rules"] = {
            k: Rule(**{**v, "windows": [Window(**w) for w in v["windows"]]})
            for k, v in data.get("rules", {}).items()
        }
        raw["exceptions"] = {k: ExceptionRecord(**v) for k, v in data.get("exceptions", {}).items()}
        state = cls(**raw)
        state.validate()
        return state

    def quarantine_paused(self, now):
        return (
            self.quarantine
            and (self.quarantine_suspended or bool(self.quarantine_until))
            and (self.quarantine_until is None or instant(self.quarantine_until) > now)
        )

    def validate(self) -> None:
        if type(self.quarantine) is not bool or type(self.quarantine_suspended) is not bool:
            raise FamilyError("Invalid quarantine state")
        if self.quarantine_until:
            instant(self.quarantine_until)
        from .access import validate_grants

        validate_grants(self)
        if type(self.access_revision) is not int or self.access_revision < 0:
            raise FamilyError("Invalid access revision")
        if self.binding_token is not None and (
            type(self.binding_token) is not str or len(self.binding_token) != 36
        ):
            raise FamilyError("Invalid connection transaction token")
        ZoneInfo(self.timezone)
        if (
            not self.controller
            or not self.site
            or not self.networks
            or len(set(self.networks)) != len(self.networks)
        ):
            raise FamilyError("Controller, site and explicit networks are required")
        if type(self.revision) is not int or self.revision < 0 or not 1 <= self.audit_days <= 365:
            raise FamilyError("Invalid revision or retention")
        if len(self.groups) > 100 or len(self.rules) > 200 or len(self.devices) > 2000:
            raise FamilyError("Household size limit exceeded")
        for key, group in self.groups.items():
            if (
                key != group.id
                or not group.name.strip()
                or len(group.name) > 100
                or group.kind not in ("family", "thing")
                or group.age not in (None, "child", "teen", "adult")
            ):
                raise FamilyError("Invalid group")
        from .dns_checks import validate_probe
        from .dns_context import settings

        if type(self.dns_revision) is not int or self.dns_revision < 0:
            raise FamilyError("Invalid DNS settings revision")
        self.dns_settings = settings(self.dns_settings, self.groups)
        if (
            len(self.probes) > 100
            or sum(len(p.get("domains", [])) for p in self.probes.values()) > 10000
        ):
            raise FamilyError("DNS checks allow at most 100 lists and 10,000 sample domains")
        for probe in self.probes.values():
            validate_probe(probe)
            from .dns_catalog import CATEGORIES

            if probe.get("seed"):
                if probe["seed"] not in CATEGORIES or probe.get("category") != probe["seed"]:
                    raise FamilyError("Invalid built-in DNS category")
                for field_name in ("seed_domains", "removed_seed_domains"):
                    values = probe.get(field_name, [])
                    if (
                        not isinstance(values, list)
                        or len(values) > 1000
                        or any(domain_name(d) != d for d in values)
                    ):
                        raise FamilyError("Invalid built-in DNS samples")
            if probe.get("group_id") and probe["group_id"] not in self.groups:
                raise FamilyError("DNS list refers to an unknown group")
        seen = set()
        for key, device in self.devices.items():
            if (
                key != device.id
                or device.mac != mac_address(device.mac)
                or device.mac in seen
                or device.group is not None
                and device.group not in self.groups
            ):
                raise FamilyError("Invalid or duplicate device identity")
            seen.add(device.mac)
        for key, rule in self.rules.items():
            if (
                key != rule.id
                or not rule.name.strip()
                or len(rule.name) > 100
                or rule.kind not in ("internet", "category", "application", "domain")
                or bool(rule.groups) == bool(rule.networks)
                or any(g not in self.groups for g in rule.groups)
                or len(set(rule.groups)) != len(rule.groups)
                or any(n not in self.networks for n in rule.networks)
                or len(set(rule.networks)) != len(rule.networks)
            ):
                raise FamilyError("Choose explicit groups or managed networks, and a valid kind")
            if (
                rule.kind == "internet"
                and rule.targets
                or rule.kind != "internet"
                and not rule.targets
            ):
                raise FamilyError("Invalid rule targets")
            if (
                len(rule.targets) > 100
                or len(rule.windows) > 32
                or len({w.id for w in rule.windows}) != len(rule.windows)
            ):
                raise FamilyError("Too many or duplicate targets/windows")
            if rule.kind == "domain":
                for value in rule.targets:
                    if type(value) is not str or domain_name(value) != value:
                        raise FamilyError("Domain targets must be canonical")
            elif rule.kind in ("category", "application"):
                if any(type(t) is not int or t < 0 for t in rule.targets):
                    raise FamilyError("Catalogue targets must be nonnegative IDs")
            for window in rule.windows:
                window.validate()
        for key, exc in self.exceptions.items():
            if (
                key != exc.id
                or exc.kind not in ("pause", "internet_allow", "suspension", "rule_allow")
                or exc.group is not None
                and exc.group not in self.groups
                or exc.rule is not None
                and exc.rule not in self.rules
            ):
                raise FamilyError("Invalid exception scope")
            instant(exc.created_at)
            if exc.expires_at:
                instant(exc.expires_at)
            if not exc.actor:
                raise FamilyError("Exception must retain an authenticated actor")
