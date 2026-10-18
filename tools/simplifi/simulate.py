"""Offline executable simulator; no HA server and no production credentials."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custom_components.simplifi.api.simulator import FakeGateway  # noqa: E402
from custom_components.simplifi.engine import Engine  # noqa: E402
from custom_components.simplifi.models import Group, State  # noqa: E402


async def main():
    gateway = FakeGateway()
    state = State("simulator", "demo-site", ["demo-family"], gateway_timezone_confirmed=True)
    state.groups["demo"] = Group("demo", "Demo family")

    async def save(state):
        # This CLI is ephemeral; installed HA uses its durable Store adapter.
        return None

    engine = Engine(state, gateway, save)
    await engine.refresh()
    for device in engine.state.devices.values():
        await engine.command(
            "assign_device",
            {"device_id": device.id, "group_id": "demo"},
            "simulator-admin",
            administrator=True,
        )
    await engine.command(
        "set_management",
        {"enabled": True, "gateway_timezone_confirmed": True},
        "simulator-admin",
        administrator=True,
    )
    result = await engine.command(
        "pause_internet",
        {"group_id": "demo", "duration_minutes": 30},
        "simulator-admin",
        administrator=True,
    )
    await engine.refresh()
    print(
        json.dumps(
            {
                "simulation": True,
                "change_id": result["id"],
                "managed_state": engine.status("demo"),
                "sync": engine.state.sync_status,
                "fake_policy_count": len(gateway.policies),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
