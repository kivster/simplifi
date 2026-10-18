"""Portable restore must preserve intent without importing operational authority."""

from copy import deepcopy

import pytest

from custom_components.family_network.models import Conflict, Device, FamilyError, Rule, State
from custom_components.family_network.portable import prepare, unpack

from .conftest import command


async def test_portable_roundtrip_rebind_and_later_discovery(household):
    engine, gateway, _, _ = household
    engine.state.rules["network"] = Rule(
        "network", "Night", "internet", [], networks=["demo-family"]
    )
    original = list(engine.state.devices.values())
    engine.state.quarantine = True
    engine.state.quarantine_excluded = [original[1].id]
    engine.state.groups["child"].person = "person.previous_home"
    data = engine.export()
    assert data["version"] == 2 and len(data["assignments"]) == len(original)
    assert not {"api_key", "owned", "journal", "access_grants", "exceptions"} & data.keys()
    engine.state = State("new-controller", "new-site", ["new-family"])
    # One device is already visible under a new controller-specific ID.
    engine.state.devices = {
        "new-id": Device("new-id", original[0].mac, "Current name", "new-family")
    }
    with pytest.raises(FamilyError, match="map every"):
        await command(engine, "preview_import", configuration=data)
    mapping = {"demo-family": "new-family"}
    preview = await command(engine, "preview_import", configuration=data, network_mapping=mapping)
    assert len(preview["matched"]) == len(preview["pending"]) == 1
    assert preview["dns_resolvers_reset"]
    await command(
        engine,
        "apply_import",
        configuration=data,
        network_mapping=mapping,
        preview_hash=preview["preview_hash"],
        expected_revision=0,
    )
    assert engine.state.controller == "new-controller"
    assert engine.state.rules["network"].networks == ["new-family"]
    assert engine.state.devices["new-id"].group == "child"
    assert engine.state.groups["child"].person is None
    assert not engine.state.management and not engine.state.gateway_timezone_confirmed
    assert engine.state.quarantine_excluded == [f"restore:{original[1].mac}"]
    # A restart retains the unseen assignment; discovery migrates its MAC once.
    engine.state = State.from_dict(engine.state.to_dict())
    gateway.clients = [Device("later-id", original[1].mac, "Later", "new-family", connected=True)]
    await engine.refresh()
    assert engine.state.devices["later-id"].group == "child"
    assert engine.state.quarantine_excluded == ["later-id"]
    assert len(engine.state.devices) == 2
    assert not gateway.policies


@pytest.mark.parametrize("mutation", ["dns", "access", "device", "actor", "mapping"])
async def test_restore_review_binds_settings_and_identity(household, mutation):
    engine, _, _, _ = household
    data = engine.export()
    preview = await command(engine, "preview_import", configuration=data)
    actor = "admin-id"
    mapping = {}
    if mutation == "dns":
        engine.state.dns_revision += 1
    elif mutation == "access":
        engine.state.access_revision += 1
    elif mutation == "device":
        next(iter(engine.state.devices.values())).network = None
    elif mutation == "actor":
        actor = "other-admin"
    else:
        mapping = {"extra": "demo-family"}
    with pytest.raises(FamilyError):
        await engine.command(
            "apply_import",
            {
                "configuration": data,
                "network_mapping": mapping,
                "preview_hash": preview["preview_hash"],
                "expected_revision": engine.state.revision,
            },
            actor,
            administrator=True,
        )


@pytest.mark.parametrize("blocker", ["management", "owned", "journal"])
async def test_restore_never_loses_gateway_ownership(household, blocker):
    engine, _, _, _ = household
    data = engine.export()
    preview = await command(engine, "preview_import", configuration=data)
    if blocker == "management":
        engine.state.management = True
    elif blocker == "owned":
        engine.state.owned["foreign"] = {"id": "policy"}
    else:
        engine.state.journal.append({"status": "uncertain"})
    with pytest.raises(FamilyError, match="clean up"):
        await command(
            engine,
            "apply_import",
            configuration=data,
            preview_hash=preview["preview_hash"],
            expected_revision=0,
        )


async def test_restore_backup_failure_is_atomic_and_backup_is_exact(household):
    engine, _, _, _ = household
    data = engine.export()
    preview = await command(engine, "preview_import", configuration=data)
    before = engine.state.to_dict()

    async def failed(_):
        raise OSError("disk failure")

    engine.import_backup = failed
    with pytest.raises(OSError):
        await command(
            engine,
            "apply_import",
            configuration=data,
            preview_hash=preview["preview_hash"],
            expected_revision=0,
        )
    assert engine.state.to_dict() == before
    backups = []

    async def backup(raw):
        backups.append(deepcopy(raw))

    engine.import_backup = backup
    await command(
        engine,
        "apply_import",
        configuration=data,
        preview_hash=preview["preview_hash"],
        expected_revision=0,
    )
    assert backups == [before]


def test_old_export_and_malformed_exports(household):
    engine, _, _, _ = household
    old = engine.export()["configuration"]
    draft, _ = prepare(engine.state, old, {}, "admin")
    assert all(d.group is None for d in draft.devices.values())
    for data in [
        {**engine.export(), "version": 3},
        {**old, "api_key": "secret"},
        {**old, "groups": "x" * 2_000_001},
    ]:
        with pytest.raises(FamilyError):
            unpack(data)
    data = engine.export()
    data["assignments"].append(deepcopy(data["assignments"][0]))
    with pytest.raises(FamilyError, match="Duplicate"):
        prepare(engine.state, data, {}, "admin")


async def test_inventory_reused_id_or_duplicate_mac_does_not_transfer_owner(household):
    engine, gateway, _, _ = household
    original = deepcopy(engine.state.devices)
    gateway.clients[0].mac = "02:00:00:00:00:99"
    with pytest.raises(Conflict, match="reused"):
        await engine.refresh()
    assert engine.state.devices == original
    gateway.clients = [deepcopy(next(iter(original.values())))] * 2
    with pytest.raises(FamilyError, match="Duplicate"):
        await engine.refresh()
    assert engine.state.devices == original


async def test_reconfiguration_freezes_commands_and_refresh(household):
    engine, _, _, _ = household
    engine.reconfiguring = True
    with pytest.raises(Conflict, match="reload"):
        await command(engine, "export_configuration")
    with pytest.raises(Conflict, match="reload"):
        await engine.refresh()
