"""Use actual disk reads/writes to test recovery, rather than the HA storage mock."""

import asyncio
import json
from pathlib import Path

import pytest
from atomicwrites import AtomicWriter
from homeassistant.helpers.storage import Store

from custom_components.simplifi.checked_store import CheckedStore
from custom_components.simplifi.models import Rule, SimpliFiError

REAL_LOAD = Store._async_load
REAL_WRITE = Store._async_write_data


@pytest.fixture
def disk_store(hass, tmp_path, monkeypatch):
    store = CheckedStore(hass, 1, "simplifi.test")
    with monkeypatch.context() as patch:
        patch.setattr(Store, "_async_load", REAL_LOAD)
        patch.setattr(Store, "_async_write_data", REAL_WRITE)
        patch.setattr(store, "path", str(tmp_path / store.key))
        yield store


def envelope(store, **overrides):
    return {
        "key": store.key,
        "version": 1,
        "minor_version": 1,
        "data": {"receipt": "saved"},
        **overrides,
    }


@pytest.mark.parametrize("raw", [b'{"unfinished":', b"{}", b"null", b"[]", b'"text"'])
async def test_damaged_store_never_becomes_a_fresh_household(disk_store, raw):
    path = Path(disk_store.path)
    await asyncio.to_thread(path.write_bytes, raw)
    for _ in range(2):
        with pytest.raises(SimpliFiError, match="stored|Stored"):
            await disk_store.async_load()
        assert (await asyncio.to_thread(path.read_bytes)) == raw
        assert (await asyncio.to_thread(list, path.parent.iterdir())) == [path]
    with pytest.raises(SimpliFiError):
        await disk_store.async_save({"receipt": "replacement"})
    assert (await asyncio.to_thread(path.read_bytes)) == raw


@pytest.mark.parametrize(
    "overrides",
    [{"key": "simplifi.other"}, {"version": 2}, {"minor_version": 2}, {"data": None}],
)
async def test_foreign_or_unsupported_store_is_preserved(disk_store, overrides):
    path = Path(disk_store.path)
    raw = json.dumps(envelope(disk_store, **overrides)).encode()
    await asyncio.to_thread(path.write_bytes, raw)
    with pytest.raises(SimpliFiError, match="stored|Stored"):
        await disk_store.async_load()
    assert (await asyncio.to_thread(path.read_bytes)) == raw


async def test_missing_record_with_previous_corruption_is_not_new(disk_store):
    path = Path(disk_store.path)
    damaged = path.with_name(path.name + ".corrupt.2026-10-14T10:00:00")
    await asyncio.to_thread(damaged.write_bytes, b"broken")
    with pytest.raises(SimpliFiError, match="stored|Stored"):
        await disk_store.async_load()
    assert (
        not await asyncio.to_thread(path.exists)
        and await asyncio.to_thread(damaged.read_bytes) == b"broken"
    )


async def test_new_store_and_atomic_round_trip(disk_store):
    assert await disk_store.async_load() is None
    assert disk_store._atomic_writes
    await disk_store.async_save({"receipt": "saved"})
    assert await disk_store.async_load() == {"receipt": "saved"}
    assert json.loads(await asyncio.to_thread(Path(disk_store.path).read_text)) == envelope(
        disk_store
    )


async def test_legacy_envelope_without_minor_version_loads(disk_store):
    raw = envelope(disk_store)
    del raw["minor_version"]
    await asyncio.to_thread(Path(disk_store.path).write_text, json.dumps(raw))
    assert await disk_store.async_load() == raw["data"]


@pytest.mark.parametrize("mode", ["read_only", "load_empty"])
async def test_read_only_mode_cannot_acknowledge_a_save(disk_store, mode):
    await disk_store.async_save({"receipt": "original"})
    original = await asyncio.to_thread(Path(disk_store.path).read_bytes)
    if mode == "read_only":
        disk_store.make_read_only()
    else:
        disk_store.set_load_empty()
    with pytest.raises(SimpliFiError):
        await disk_store.async_load()
    with pytest.raises(SimpliFiError):
        await disk_store.async_save({"receipt": "replacement"})
    assert (await asyncio.to_thread(Path(disk_store.path).read_bytes)) == original


async def test_failed_sync_preserves_previous_complete_receipt(disk_store, monkeypatch):
    await disk_store.async_save({"receipt": "original"})
    path = Path(disk_store.path)
    original = await asyncio.to_thread(path.read_bytes)

    def failed_sync(self, file):
        raise OSError("injected filesystem sync failure")

    monkeypatch.setattr(AtomicWriter, "sync", failed_sync)
    with pytest.raises(SimpliFiError, match="persist"):
        await disk_store.async_save({"receipt": "replacement"})
    assert (await asyncio.to_thread(path.read_bytes)) == original
    assert (await asyncio.to_thread(list, path.parent.iterdir())) == [path]


async def test_corrupt_household_reload_preserves_existing_gateway_policies(
    hass, entry, tmp_path, monkeypatch
):
    engine = entry.runtime_data.engine
    gateway = engine.gateway
    engine.state.management = True
    engine.state.rules["r"] = Rule("r", "Rule", "internet", [], networks=["demo-family"])
    await engine.refresh()
    assert gateway.counter == len(gateway.policies) == 1
    key = entry.runtime_data.storage.store.key
    assert await hass.config_entries.async_unload(entry.entry_id)
    path = tmp_path / key
    await asyncio.to_thread(path.write_bytes, b'{"damaged":')
    mocked_load = Store._async_load

    async def load(store):
        if store.key == key:
            return await REAL_LOAD(store)
        return await mocked_load(store)

    with monkeypatch.context() as patch:
        patch.setattr(Store, "_async_load", load)
        patch.setattr(CheckedStore, "path", property(lambda store: str(tmp_path / store.key)))
        patch.setattr("custom_components.simplifi.FakeGateway", lambda: gateway)
        for _ in range(2):
            assert not await hass.config_entries.async_reload(entry.entry_id)
            assert gateway.counter == len(gateway.policies) == 1
            assert (await asyncio.to_thread(path.read_bytes)) == b'{"damaged":'
