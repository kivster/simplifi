"""Deterministic in-process gateway. This module cannot perform network I/O."""

from copy import deepcopy

from ..models import Device, SimpliFiError
from ..request_meter import RequestMeter


class FakeGateway:
    simulation = True
    controller = "simulator"
    site = "demo-site"
    external_zone = "demo-internet"
    networks = {
        "demo-family": {
            "name": "Demo Family",
            "zone": "demo-home",
            "subnet": "192.0.2.0/24",
            "dns": {"resolvers": ["192.0.2.53"], "source": "Simulated DHCP DNS", "issue": None},
        }
    }
    catalogues = {"category": {0, 3, 4, 5, 8, 11, 24}, "application": {123, 456}}
    categories = [
        {"id": 0, "name": "Messaging (demo)"},
        {"id": 3, "name": "Demo games"},
        {"id": 5, "name": "Demo social"},
        {"id": 4, "name": "Video (demo)"},
        {"id": 8, "name": "Gaming (demo)"},
        {"id": 11, "name": "VPN (demo)"},
        {"id": 24, "name": "Social (demo)"},
    ]
    applications = [{"id": 123, "name": "Demo chat"}, {"id": 456, "name": "Demo game"}]
    capabilities = {
        "internet": "simulated",
        "category": "simulated",
        "application": "simulated",
        "domain": "simulated",
        "recurrence": "simulated",
        "absolute_expiry": "unsupported",
        "external_filters": "unknown",
    }

    def __init__(self):
        self.request_meter = RequestMeter()
        self.policies: dict[str, dict] = {}
        self.counter = 0
        self.failure: str | None = None
        self.clients = [
            Device(
                "demo-site:02:00:00:00:00:01",
                "02:00:00:00:00:01",
                "Demo phone",
                "demo-family",
                connected=True,
                ip="192.0.2.10",
                kind="wireless",
            ),
            Device(
                "demo-site:02:00:00:00:00:02",
                "02:00:00:00:00:02",
                "Demo tablet",
                "demo-family",
                connected=False,
                ip="192.0.2.11",
                kind="wireless",
            ),
        ]

    async def discover(self):
        if self.failure == "inventory":
            self.failure = None
            raise SimpliFiError("Simulated incomplete inventory")
        return deepcopy(self.clients)

    async def list_policies(self):
        if self.failure == "list":
            self.failure = None
            raise SimpliFiError("Simulated policy read failure")
        return deepcopy(self.policies)

    async def create(self, body: dict) -> str:
        self.counter += 1
        key = f"demo-policy-{self.counter}"
        if self.failure == "create_before":
            self.failure = None
            raise TimeoutError
        self.policies[key] = {**deepcopy(body), "id": key}
        if self.failure == "create_after":
            self.failure = None
            raise TimeoutError
        return key

    async def policy_ordering(self, source, destination):
        return {
            "orderedFirewallPolicyIds": {
                "beforeSystemDefined": [
                    key
                    for key, row in self.policies.items()
                    if row["source"]["zoneId"] == source
                    and row["destination"]["zoneId"] == destination
                ],
                "afterSystemDefined": [],
            }
        }

    async def update(self, policy_id: str, body: dict):
        self.policies[policy_id] = {**deepcopy(body), "id": policy_id}
        if self.failure == "update_after":
            self.failure = None
            raise TimeoutError

    async def delete(self, policy_id: str):
        self.policies.pop(policy_id, None)
        if self.failure == "delete_after":
            self.failure = None
            raise TimeoutError

    async def close(self):
        return None
