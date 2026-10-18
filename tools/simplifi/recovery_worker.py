"""Disposable cold-process recovery drill. Operates only inside an owned temporary lab."""


# The network guard and selected archived component must precede HA imports.
# ruff: noqa: E402

import asyncio
import fcntl
import hashlib
import ipaddress
import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

root = Path(sys.argv[1]).resolve()
phase = sys.argv[2]
assert root.parent == Path(tempfile.gettempdir()).resolve() and root.name.startswith(
    "simplifi-recovery-lab-"
)
assert json.loads((root / "lab-owner.json").read_text()) == {
    "purpose": "isolated SimpliFi restore drill",
    "config": "config",
}
config = root / "config"
lab_lock = (root / ".worker.lock").open("w")
fcntl.flock(lab_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
sys.path.insert(0, str(config))


# Block external networking through CPython audit events without changing socket types.
def local(address):
    if not isinstance(address, tuple):
        return
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode("ascii")
    if host == "localhost":
        return
    if not ipaddress.ip_address(host).is_loopback:
        raise PermissionError("Recovery lab permits loopback networking only")


def audit_network(event, args):
    if event in {"socket.connect", "socket.sendto", "socket.sendmsg"}:
        local(args[1])
    elif event == "socket.getaddrinfo" and args[0] is not None:
        local((args[0], 0))


sys.addaudithook(audit_network)

if phase == "restored":
    from homeassistant.backup_restore import restore_backup

    assert restore_backup(str(config)) is True

import aiohttp
import yaml
from homeassistant import bootstrap
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.core import Context, CoreState
from homeassistant.runner import RuntimeConfig, create_event_loop, ensure_single_execution

import custom_components.simplifi as component
from custom_components.simplifi.api.simulator import FakeGateway
from custom_components.simplifi.const import CARD_RESOURCE, VERSION

gateway_file = root / "gateway.json"
gateway_data = json.loads(gateway_file.read_text()) if gateway_file.exists() else None


def write_json(path, value):
    temporary = path.with_suffix(".pending")
    with temporary.open("w") as target:
        json.dump(value, target, indent=2)
        target.flush()
        os.fsync(target.fileno())
    temporary.replace(path)


class DurableFakeGateway(FakeGateway):
    """Keep the simulated external controller independent of HA backup/restore."""

    def __init__(self):
        super().__init__()
        if gateway_data:
            self.policies = deepcopy(gateway_data["policies"])
            self.counter = gateway_data["counter"]

    async def persist(self):
        await asyncio.to_thread(
            write_json, gateway_file, {"policies": self.policies, "counter": self.counter}
        )

    async def create(self, body):
        try:
            return await super().create(body)
        finally:
            await self.persist()

    async def update(self, key, body):
        try:
            return await super().update(key, body)
        finally:
            await self.persist()

    async def delete(self, key):
        try:
            return await super().delete(key)
        finally:
            await self.persist()


component.FakeGateway = DurableFakeGateway


@asynccontextmanager
async def native_ui(hass, user_id):
    user = await hass.auth.async_get_user(user_id)
    refresh = await hass.auth.async_create_refresh_token(user, client_id="http://127.0.0.1/")
    token = hass.auth.async_create_access_token(refresh)
    settings = yaml.safe_load(await asyncio.to_thread((config / "configuration.yaml").read_text))
    port = settings["http"]["server_port"]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{port}{CARD_RESOURCE}",
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                assert response.status == 200
                served = await response.read()
                installed = await asyncio.to_thread(
                    (config / "custom_components/simplifi/frontend/simplifi-card.js").read_bytes
                )
                assert hashlib.sha256(served).digest() == hashlib.sha256(installed).digest()
            async with session.ws_connect(f"http://127.0.0.1:{port}/api/websocket") as ws:
                assert (await ws.receive_json())["type"] == "auth_required"
                await ws.send_json({"type": "auth", "access_token": token})
                assert (await ws.receive_json())["type"] == "auth_ok"
                count = 0

                async def command(command_type, **data):
                    nonlocal count
                    count += 1
                    await ws.send_json({"id": count, "type": command_type, **data})
                    response = await ws.receive_json()
                    assert response["id"] == count and response.get("success"), response
                    return response.get("result")

                yield command
    finally:
        hass.auth.async_remove_refresh_token(refresh)


async def main():
    hass = await bootstrap.async_setup_hass(
        RuntimeConfig(
            config_dir=str(config),
            skip_pip=True,
            log_file=str(root / (phase + ".log")),
            log_no_color=True,
        )
    )
    assert hass is not None and not hass.config.safe_mode
    running = asyncio.create_task(hass.async_run(attach_signals=False))
    try:
        await asyncio.sleep(0)
        await hass.async_block_till_done()
        assert hass.state is CoreState.running
        if phase == "seed":
            admin = await hass.auth.async_create_user("Lab adult", group_ids=[GROUP_ID_ADMIN])
            delegate = await hass.auth.async_create_user("Lab delegate", group_ids=[GROUP_ID_USER])
            flow = await hass.config_entries.flow.async_init(
                "simplifi",
                context={"source": "user"},
                data={"simulation": True, "verify_ssl": True},
            )
            assert flow["type"] == "create_entry", flow
            await hass.async_block_till_done()
            # A fictional credential marker verifies native entry-data preservation.
            # Simulation remains mandatory; this value cannot authenticate anywhere.
            hass.config_entries.async_update_entry(
                flow["result"],
                data={**flow["result"].data, "api_key": "lab-not-a-real-credential"},
            )
            await hass.async_block_till_done()
            await asyncio.to_thread(
                write_json,
                root / "identities.json",
                {"admin": admin.id, "delegate": delegate.id, "entry": flow["result"].entry_id},
            )
        identities = await asyncio.to_thread(
            lambda: json.loads((root / "identities.json").read_text())
        )
        entry = hass.config_entries.async_get_entry(identities["entry"])
        assert entry and entry.state.name == "LOADED" and entry.data["simulation"] is True
        coordinator = entry.runtime_data
        engine = coordinator.engine
        assert isinstance(engine.gateway, DurableFakeGateway)

        async def action(action_name, **data):
            return await hass.services.async_call(
                "simplifi",
                action_name,
                {"entry_id": entry.entry_id, **data},
                blocking=True,
                return_response=True,
                context=Context(user_id=identities["admin"]),
            )

        if phase == "seed":
            for device in list(engine.state.devices):
                await action("assign_device", device_id=device, group_id="demo-family")
            await action("upsert_group", group_id="demo-family", name="Lab household")
            await action(
                "upsert_rule",
                rule_id="lab-internet",
                name="Lab internet",
                kind="internet",
                groups=["demo-family"],
            )
            await action(
                "upsert_rule",
                rule_id="lab-video",
                name="Lab video",
                kind="category",
                groups=["demo-family"],
                targets=[4],
            )
            await action(
                "set_access_grant",
                user_id=identities["delegate"],
                scope="watch_rules",
                groups=["demo-family"],
                confirm=True,
            )
            await action(
                "set_management",
                enabled=True,
                gateway_timezone_confirmed=True,
                expiry_acknowledged=True,
            )
            await coordinator.async_refresh()
            generated = await action("dashboard_configuration")
            generated["dashboard"]["title"] = "Lab household dashboard"
            generated["dashboard"]["views"][0]["sections"].append(
                {
                    "type": "grid",
                    "cards": [{"type": "markdown", "content": "User customization preserved"}],
                }
            )
            async with native_ui(hass, identities["admin"]) as ws:
                await ws(
                    "lovelace/dashboards/create",
                    url_path="lab-simplifi",
                    mode="storage",
                    title="Lab household",
                )
                await ws(
                    "lovelace/config/save", url_path="lab-simplifi", config=generated["dashboard"]
                )
                await ws(
                    "lovelace/dashboards/create",
                    url_path="lab-unrelated",
                    mode="storage",
                    title="Other dashboard",
                )
                await ws(
                    "lovelace/config/save",
                    url_path="lab-unrelated",
                    config={
                        "title": "Other dashboard",
                        "views": [
                            {
                                "title": "Keep me",
                                "cards": [
                                    {"type": "markdown", "content": "Unrelated content preserved"}
                                ],
                            }
                        ],
                    },
                )
                await ws(
                    "lovelace/resources/create", res_type="module", url="/local/lab-unrelated.js"
                )
        elif phase == "new-controls":
            await action("pause_internet", group_id="demo-family", duration_minutes=30)
            await action(
                "allow_internet",
                group_id="demo-family",
                duration_minutes=45,
                request_id="lab-bounded-allowance",
                request_expires_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
            )
        elif phase == "retry-after-restore":
            original = next(
                c for c in engine.state.changes if c.get("request_id") == "lab-bounded-allowance"
            )
            before = engine.state.to_dict()
            response = await action(
                "allow_internet",
                group_id="demo-family",
                duration_minutes=45,
                request_id=original["request_id"],
                request_expires_at=original["request_expires_at"],
            )
            assert response["id"] == original["id"]
            assert engine.state.to_dict() == before, "Retained retry mutated intent"
        elif phase == "backup":
            from homeassistant.components.backup import async_get_manager

            manager = async_get_manager(hass)
            result = await manager.async_create_backup(
                agent_ids=["backup.local"],
                include_addons=None,
                include_all_addons=False,
                include_database=False,
                include_folders=None,
                include_homeassistant=True,
                name="SimpliFi isolated recovery drill",
                password=None,
            )
            archive = manager.local_backup_agents["backup.local"].get_backup_path(
                result.backup_job_id
            )
            await asyncio.to_thread(
                write_json,
                root / "archive.json",
                {"id": result.backup_job_id, "path": str(archive)},
            )
        elif phase == "change-after-backup":
            await action("upsert_group", group_id="demo-family", name="Changed after backup")
        elif phase == "request-restore":
            from homeassistant.components.backup import async_get_manager

            archive = await asyncio.to_thread(
                lambda: json.loads((root / "archive.json").read_text())
            )
            await async_get_manager(hass).async_restore_backup(
                archive["id"],
                agent_id="backup.local",
                password=None,
                restore_addons=None,
                restore_database=False,
                restore_folders=None,
                restore_homeassistant=True,
            )
            assert (config / ".HA_RESTORE").is_file()
            return
        await coordinator.async_refresh()
        assert engine.state.sync_status == "applied"
        history = await coordinator.storage.history.read(limit=100)
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        async with native_ui(hass, identities["admin"]) as ws:
            ui = {
                "dashboards": await ws("lovelace/dashboards/list"),
                "resources": await ws("lovelace/resources"),
                "household": await ws("lovelace/config", url_path="lab-simplifi"),
                "unrelated": await ws("lovelace/config", url_path="lab-unrelated"),
            }
        snapshot = {
            "ui": ui,
            "phase": phase,
            "version": VERSION,
            "entry": entry.entry_id,
            "entry_data": dict(entry.data),
            "state": engine.state.to_dict(),
            "export": await action("export_configuration"),
            "gateway": {"policies": engine.gateway.policies, "counter": engine.gateway.counter},
            "entities": {
                e.unique_id: e.entity_id
                for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            },
            "users": [
                {"id": u.id, "name": u.name, "active": u.is_active}
                for u in await hass.auth.async_get_users()
            ],
            "history": history,
        }
        await asyncio.to_thread(write_json, root / (phase + "-result.json"), snapshot)
        print(
            json.dumps(
                {
                    "phase": phase,
                    "version": snapshot["version"],
                    "sync": engine.state.sync_status,
                    "revision": engine.state.revision,
                    "policies": len(engine.gateway.policies),
                    "journal": len(engine.state.journal),
                    "history": history.get("retained"),
                }
            ),
            flush=True,
        )
    finally:
        if not hass.is_stopping:
            await hass.async_stop()
        await running
        assert hass.state is CoreState.stopped


loop = create_event_loop()
try:
    asyncio.set_event_loop(loop)
    with ensure_single_execution(str(config)) as lock:
        assert lock.exit_code is None, "Lab is already running"
        loop.run_until_complete(main())
finally:
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.run_until_complete(loop.shutdown_default_executor())
    asyncio.set_event_loop(None)
    loop.close()
