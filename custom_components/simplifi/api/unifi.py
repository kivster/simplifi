"""Local official Network Integration API adapter with runtime contract checks.

No legacy/v2 calls, cloud connector, client-block actions or policy ordering writes.
All HTTP response bodies are excluded from errors to avoid credential leakage.
"""

import asyncio
import ipaddress
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp

from ..compatibility import (
    TESTED_NETWORK_VERSIONS,
    identity,
    require,
    validate_catalogue,
    validate_network,
    validate_policy,
    validate_sites,
    version_label,
)
from ..inventory import (
    InventoryScopeError,
    client_network,
    client_references,
    mac_registrant,
    network_subnets,
    registrant_database,
)
from ..models import (
    CapabilityError,
    Device,
    GatewayAuthenticationError,
    SimpliFiError,
    instant,
    mac_address,
    utcnow,
)
from ..request_meter import MeteredSession, RequestMeter

DISCOVERY_RETRY_TIMEOUT = 30


def external_zone_id(zones: list[dict]) -> str:
    """Identify the built-in internet zone without guessing from network membership."""
    matches = [
        zone
        for zone in zones
        if zone.get("name") == "External"
        and isinstance(zone.get("metadata"), dict)
        and zone["metadata"].get("origin") == "SYSTEM_DEFINED"
        and isinstance(zone.get("id"), str)
        and zone["id"]
    ]
    # External can contain WAN interfaces. An empty networkIds array is not its identity.
    if len(matches) != 1:
        raise CapabilityError(
            "UniFi did not return one identifiable built-in External internet zone. "
            "Check the site's firewall zones and API access, then select the site again"
        )
    return matches[0]["id"]


class UniFiGateway:
    simulation = False

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        api_key: str,
        site: str = "",
        networks: list[str] | None = None,
        external_zone: str = "",
        verify_ssl: bool = True,
    ):
        url = urlsplit(host)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.path not in ("", "/")
            or url.query
            or url.fragment
        ):
            raise SimpliFiError(
                "Controller must be a local HTTPS origin without credentials or a path"
            )
        self.session = session
        self.controller = host.rstrip("/")
        self.api_key = api_key.strip()
        if not self.api_key or any(c.isspace() for c in self.api_key):
            raise SimpliFiError("Enter the complete API key without spaces or line breaks")
        self.site = site
        self.scope = networks or []
        self.external_zone = external_zone
        self.verify_ssl = verify_ssl
        self.networks: dict[str, dict] = {}
        self.current_network_reader: Any = None
        self.catalogues: dict[str, set[int]] = {}
        self.categories: list[dict] = []
        self.applications: list[dict] = []
        self.zones: list[dict] = []
        self.capabilities = {
            k: "unknown"
            for k in (
                "internet",
                "category",
                "application",
                "domain",
                "recurrence",
                "absolute_expiry",
                "external_filters",
            )
        }
        self.version = "unknown"
        self.compatibility: dict[str, Any] = {
            "status": "not_checked",
            "application_version": "unknown",
            "tested_version": False,
            "checked_at": None,
            "issue": None,
            "features": {},
        }
        self.legacy_site = None
        self.request_meter = RequestMeter()
        self.discovery_readback: dict = {"status": "not_read", "attempts": 0, "scope_issues": []}

    @property
    def site_path(self):
        return f"/v1/sites/{quote(self.site, safe='')}"

    async def request(self, method: str, path: str, body=None, params=None):
        url = f"{self.controller}/proxy/network/integration{path}"
        attempts = 3 if method == "GET" else 1
        transport = MeteredSession(self.session, self.request_meter)
        for attempt in range(attempts):
            try:
                async with transport.request(
                    method,
                    url,
                    headers={"X-API-Key": self.api_key, "Accept": "application/json"},
                    json=body,
                    params=params,
                    ssl=self.verify_ssl,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if (
                        response.status in (429, 502, 503, 504)
                        and method == "GET"
                        and attempt < attempts - 1
                    ):
                        pass
                    elif response.status == 401:
                        raise GatewayAuthenticationError(
                            "UniFi rejected the API key (HTTP 401). Use the complete key created "
                            "in this console's local Integrations page"
                        )
                    elif response.status == 403:
                        raise SimpliFiError(
                            "UniFi denied access (HTTP 403). Check this key's Network "
                            "application and site permissions"
                        )
                    elif not 200 <= response.status < 300:
                        raise SimpliFiError(
                            f"Gateway HTTP {response.status}; response body withheld"
                        )
                    # UniFi 10.6.106 documents DELETE policy success as a bodyless
                    # 200. The reconciler still verifies absence with a full read.
                    elif response.status == 204 or (method == "DELETE" and response.status == 200):
                        return None
                    else:
                        try:
                            return await response.json()
                        except ValueError, aiohttp.ContentTypeError:
                            raise SimpliFiError("Malformed gateway response") from None
                # Backoff is outside the measured HTTP exchange and releases its response.
                await asyncio.sleep(2**attempt)
            except aiohttp.ClientConnectorCertificateError:
                raise SimpliFiError(
                    "The controller's HTTPS certificate could not be verified. Check its "
                    "hostname and certificate trust"
                ) from None
            except aiohttp.ClientSSLError:
                raise SimpliFiError("The HTTPS/TLS handshake with the controller failed") from None
            except TimeoutError:
                raise SimpliFiError("The controller did not respond within 20 seconds") from None
            except aiohttp.ClientError:
                raise SimpliFiError(
                    "Home Assistant could not connect to the controller HTTPS address"
                ) from None
        raise SimpliFiError("Read retries exhausted")

    async def pages(self, path: str, cap: int = 10000) -> list[dict]:
        result: list[dict] = []
        total = None
        while True:
            page = await self.request("GET", path, params={"offset": len(result), "limit": 100})
            if (
                not isinstance(page, dict)
                or not all(k in page for k in ("data", "offset", "count", "totalCount"))
                or not isinstance(page["data"], list)
            ):
                raise SimpliFiError("Missing pagination metadata; read is incomplete")
            if (
                any(type(page[k]) is not int for k in ("offset", "count", "totalCount"))
                or page["offset"] != len(result)
                or page["count"] != len(page["data"])
                or page["totalCount"] < 0
            ):
                raise SimpliFiError("Invalid pagination metadata")
            if total is not None and total != page["totalCount"]:
                raise SimpliFiError("Inventory changed during pagination; retry a full read")
            total = page["totalCount"]
            result.extend(page["data"])
            if total > cap or len(result) > total:
                raise SimpliFiError("Inventory cap/truncation; refusing incomplete results")
            if len(result) == total:
                break
            if not page["data"]:
                raise SimpliFiError("Unexpected empty page")
        if any(
            not isinstance(x, dict)
            or not (identity(x.get("id")) or type(x.get("id")) is int and x["id"] >= 0)
            for x in result
        ) or len({x["id"] for x in result}) != len(result):
            raise SimpliFiError("Duplicate or missing inventory identities")
        return result

    async def begin_read(self):
        self.compatibility.update(
            status="checking", issue=None, checked_at=utcnow().isoformat(), features={}
        )
        sites = await self.connect()
        if self.site not in {s["id"] for s in sites}:
            raise CapabilityError(
                "The selected UniFi site is unavailable. Check the API key's site permissions; saved settings are retained"
            )

    def finish_read(self, error=None):
        self.compatibility.update(
            status=(
                "authentication_required"
                if isinstance(error, GatewayAuthenticationError)
                else "paused"
                if error
                else "limited"
                if "unavailable" in self.compatibility["features"].values()
                else "available"
            ),
            issue=str(error) if error else None,
            checked_at=utcnow().isoformat(),
        )

    async def connect(self):
        try:
            info = await self.request("GET", "/v1/info")
        except GatewayAuthenticationError:
            raise
        except SimpliFiError, TimeoutError:
            # Version metadata is optional. Required site/resource reads still
            # establish connectivity, permissions and the usable API contract.
            info = None
            self.compatibility["features"]["application_info"] = "unavailable"
        self.version = version_label(
            info.get("applicationVersion") if isinstance(info, dict) else None
        )
        self.compatibility.update(
            application_version=self.version,
            tested_version=self.version in TESTED_NETWORK_VERSIONS,
        )
        sites = await self.pages("/v1/sites", cap=100)
        validate_sites(sites)
        if not sites:
            raise SimpliFiError(
                "UniFi returned no accessible sites. Check this key's site permissions"
            )
        self.legacy_site = next(
            (s.get("internalReference") for s in sites if s["id"] == self.site), None
        )
        return sites

    async def refresh_resources(self):
        summaries = await self.pages(self.site_path + "/networks", cap=1000)
        zones = await self.pages(self.site_path + "/firewall/zones", cap=1000)
        require(
            all(identity(z.get("id")) and isinstance(z.get("name"), str) for z in zones),
            "firewall zone",
        )
        destination = external_zone_id(zones)
        networks = {}
        # Full network details are required to constrain client scope; no legacy IDs.
        for summary in summaries:
            validate_network(summary, {z["id"] for z in zones})
            detail = await self.request(
                "GET", self.site_path + "/networks/" + quote(summary["id"], safe="")
            )
            if not isinstance(detail, dict) or detail.get("id") != summary["id"]:
                raise CapabilityError("Invalid network readback; policy updates paused")
            require(
                detail.get("internetAccessEnabled") is None
                or type(detail["internetAccessEnabled"]) is bool,
                "network",
            )
            for family in ("ipv4Configuration", "ipv6Configuration"):
                config = detail.get(family)
                require(config is None or isinstance(config, dict), "network subnet")
                if config:
                    require(
                        config.get("additionalHostIpSubnets") is None
                        or isinstance(config["additionalHostIpSubnets"], list),
                        "network subnet",
                    )
            subnets = network_subnets(detail)
            subnet = next((s for s in subnets if ipaddress.ip_network(s).version == 4), None)
            from ..dns_context import network_dns

            networks[summary["id"]] = {
                "name": summary["name"],
                "zone": summary.get("zoneId"),
                "subnet": subnet,
                "subnets": subnets,
                "internet_enabled": detail.get("internetAccessEnabled"),
                "dns": network_dns(detail),
            }
        categories = await self._catalogue("category", "/v1/dpi/categories", 10000)
        applications = await self._catalogue("application", "/v1/dpi/applications", 30000)
        if self.scope and not set(self.scope) <= set(networks):
            raise CapabilityError("Managed network is missing; writer frozen")
        if self.external_zone and self.external_zone != destination:
            raise CapabilityError(
                "Internet-only destination must be the system-defined External zone; writer frozen"
            )
        self.networks, self.zones = networks, zones
        self.categories, self.applications = categories, applications
        self.catalogues = {
            "category": {c["id"] for c in categories},
            "application": {a["id"] for a in applications},
        }
        self.capabilities.update(
            {k: "documented_not_live_tested" for k in ("internet", "domain", "recurrence")}
        )
        self.capabilities.update(
            {"absolute_expiry": "unsupported", "external_filters": "unsupported_official_api"}
        )

    async def _catalogue(self, kind, path, cap):
        try:
            rows = await self.pages(path, cap=cap)
            validate_catalogue(rows)
        except GatewayAuthenticationError:
            raise
        except SimpliFiError, TimeoutError:
            self.capabilities[kind] = "unavailable"
            self.compatibility["features"][kind] = "unavailable"
            return []
        self.capabilities[kind] = "catalogue_read"
        self.compatibility["features"][kind] = "available"
        return rows

    def require_rule_catalogues(self, rules):
        # Planning must never drop an existing rule merely because its catalogue
        # disappeared. Pause the shared policy plan if any saved rule needs it.
        for kind in ("category", "application"):
            if self.capabilities.get(kind) == "unavailable" and any(
                r.kind == kind for r in rules.values()
            ):
                raise CapabilityError(
                    f"UniFi's {kind} catalogue is unavailable. Policy updates are paused to preserve existing rules; SimpliFi will retry automatically"
                )

    async def discover(self) -> list[Device]:
        """Retry one inconsistent scope snapshot, without accepting either side of a conflict."""
        evidence = self.discovery_readback = {
            "status": "reading",
            "attempted_at": utcnow().isoformat(),
            "observed_at": None,
            "attempts": 0,
            "scope_issues": [],
            "lan_clients": None,
        }
        required_current: set[str] = set()
        try:
            for attempt in range(2):
                evidence["attempts"] = attempt + 1
                try:
                    # The retry rereads all resources and every page. Only its own
                    # complete, validated inventory can reach the engine. Bound
                    # extra controller work, including the brief settling delay.
                    async with asyncio.timeout(DISCOVERY_RETRY_TIMEOUT if attempt else None):
                        if attempt:
                            await asyncio.sleep(1)
                        devices = await self._discover_once(required_current)
                except InventoryScopeError as err:
                    evidence["scope_issues"].append(err.reason)
                    if attempt:
                        raise
                else:
                    evidence.update(
                        status="complete",
                        observed_at=utcnow().isoformat(),
                        lan_clients=len(devices),
                    )
                    return devices
        finally:
            if evidence["status"] == "reading":
                evidence["status"] = "incomplete"
        raise SimpliFiError("Scoped discovery is incomplete")

    async def _discover_once(self, required_current: set[str]) -> list[Device]:
        await self.refresh_resources()
        rows = await self.pages(self.site_path + "/clients", cap=2000)
        # Keep the two current-client observations adjacent. Display/reference
        # reads must not add avoidable skew between their scope evidence.
        current: dict[str, dict] = (
            await self.current_network_reader.read() if self.current_network_reader else {}
        )
        references: dict[str, set[str]] = {}
        for key in self.networks:
            try:
                payload = await self.request(
                    "GET", self.site_path + "/networks/" + quote(key, safe="") + "/references"
                )
            except GatewayAuthenticationError:
                raise
            except SimpliFiError:
                # Some 10.6.106 networks return HTTP 500 here. A unique configured
                # subnet remains a labelled fallback; unmapped clients still freeze
                # discovery. Never accept a truncated successful reference payload.
                references[key] = set()
                self.networks[key]["reference_status"] = "unavailable"
            else:
                references[key] = client_references(payload)
                self.networks[key]["reference_status"] = "read"
        # Names/registrants are optional display observations, never policy inputs.
        try:
            uplinks = {
                r["id"]: r.get("name")
                for r in await self.pages(self.site_path + "/devices", cap=2000)
            }
        except GatewayAuthenticationError:
            raise
        except SimpliFiError:
            uplinks = {}
        try:
            registrants = await asyncio.to_thread(registrant_database)
        except OSError, ValueError, KeyError:
            registrants = None
        devices = []
        seen = set()
        observed = utcnow().isoformat()
        for row in rows:
            require(
                identity(row.get("id"))
                and row.get("type") in ("WIRED", "WIRELESS", "VPN", "TELEPORT"),
                "client identity",
            )
            if row["type"] in ("VPN", "TELEPORT"):
                continue
            require(row.get("name") is None or isinstance(row["name"], str), "client name")
            require(
                row.get("ipAddress") is None or isinstance(row["ipAddress"], str), "client address"
            )
            try:
                mac = mac_address(row["macAddress"])
                ip = ipaddress.ip_address(row["ipAddress"]) if row.get("ipAddress") else None
            except KeyError, ValueError, TypeError:
                raise SimpliFiError(
                    "Client identity/address unavailable; discovery incomplete"
                ) from None
            if mac in seen:
                raise SimpliFiError("Duplicate client MAC; discovery incomplete")
            seen.add(mac)
            current_network = current.get(mac, {}).get("network")
            if mac in required_current and current_network is None:
                # Do not resolve a contradiction by losing the contradicting
                # source and falling back to the other side's IP subnet.
                raise InventoryScopeError("current_network_unavailable")
            try:
                network, source = client_network(
                    row["id"], ip, self.networks, references, current_network
                )
            except InventoryScopeError:
                if current_network is not None:
                    required_current.add(mac)
                raise
            connected_at = None
            if row.get("connectedAt"):
                try:
                    connected_at = instant(row["connectedAt"]).isoformat()
                except SimpliFiError, ValueError, TypeError:
                    pass
            registrant, status = (
                mac_registrant(mac, registrants)
                if registrants is not None
                else (None, "unavailable")
            )
            # Include out-of-scope observations so known roaming clients lose their
            # old scope. The engine never ingests a new out-of-scope client.
            devices.append(
                Device(
                    f"{self.site}:{mac}",
                    mac,
                    row.get("name", "Unnamed device"),
                    network,
                    connected=True,
                    last_seen=observed,
                    ip=str(ip) if ip else None,
                    uplink=row.get("uplinkDeviceId"),
                    kind=row["type"].lower(),
                    connected_at=connected_at,
                    uplink_name=uplinks.get(row.get("uplinkDeviceId")),
                    network_source=source,
                    registrant=registrant,
                    registrant_status=status,
                )
            )
        return devices

    async def list_policies(self):
        rows = await self.pages(self.site_path + "/firewall/policies", cap=10000)
        for row in rows:
            validate_policy(row)
        return {r["id"]: r for r in rows}

    async def create(self, body):
        result = await self.request("POST", self.site_path + "/firewall/policies", body=body)
        if not isinstance(result, dict) or not isinstance(result.get("id"), str):
            raise SimpliFiError("Create returned no policy identity")
        return result["id"]

    async def policy_ordering(self, source, destination):
        return await self.request(
            "GET",
            self.site_path + "/firewall/policies/ordering",
            params={"sourceFirewallZoneId": source, "destinationFirewallZoneId": destination},
        )

    async def update(self, policy_id, body):
        await self.request(
            "PUT", self.site_path + "/firewall/policies/" + quote(policy_id, safe=""), body=body
        )

    async def delete(self, policy_id):
        await self.request(
            "DELETE", self.site_path + "/firewall/policies/" + quote(policy_id, safe="")
        )

    async def close(self):
        # HA owns the shared aiohttp session.
        return None
