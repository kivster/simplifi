"""Real HA 2026.10 integration setup, registry, action admission and unload."""

import pytest
from homeassistant.components import http
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import entity_registry as er

from custom_components.simplifi.const import VERSION
from custom_components.simplifi.dashboard import generate_from_registry


async def test_actual_ha_setup_registry_and_unload(hass, entry, hass_admin_user):
    assert entry.runtime_data.engine.state.last_observed
    result = generate_from_registry(hass, entry)
    assert len(result["dashboard"]["views"]) == 5
    assert {"connected", "sync", "calendar", "group:demo-family:internet"} <= result[
        "bindings"
    ].keys()
    response = await hass.services.async_call(
        "simplifi",
        "pause_internet",
        {"entry_id": entry.entry_id, "group_id": "demo-family", "duration_minutes": 30},
        context=Context(user_id=hass_admin_user.id),
        blocking=True,
        return_response=True,
    )
    assert response["outcome"] == "pending"
    await hass.async_block_till_done()
    assert not entry.runtime_data.engine.gateway.policies  # Management disabled by default.
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("context_kind", ["missing", "unknown", "non_admin"])
async def test_direct_service_denies_non_admin(hass, entry, hass_read_only_user, context_kind):
    user_id = {"missing": None, "unknown": "not-a-user", "non_admin": hass_read_only_user.id}[
        context_kind
    ]
    before = entry.runtime_data.engine.state.revision
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "simplifi",
            "pause_internet",
            {"entry_id": entry.entry_id, "group_id": "demo-family", "duration_minutes": 30},
            context=Context(user_id=user_id),
            blocking=True,
        )
    assert entry.runtime_data.engine.state.revision == before


async def test_simulator_config_flow(hass):
    result = await hass.config_entries.flow.async_init("simplifi", context={"source": "user"})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"simulation": True, "verify_ssl": True}
    )
    assert result["type"] == "create_entry"
    assert result["data"]["simulation"] is True


async def test_missing_request_actor_denies_native_editor(hass, entry):
    with pytest.raises(Unauthorized):
        await hass.config_entries.options.async_init(entry.entry_id)


async def test_native_editor_is_actor_bound_and_uses_real_selectors(
    hass, entry, hass_admin_user, hass_read_only_user
):
    token = http.current_request.set({http.KEY_HASS_USER: hass_admin_user})
    try:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == "menu"
        flow_id = result["flow_id"]
        result = await hass.config_entries.options.async_configure(
            flow_id, {"next_step_id": "groups"}
        )
        result = await hass.config_entries.options.async_configure(
            flow_id, {"action": "upsert_group"}
        )
        assert result["step_id"] == "edit"
        result = await hass.config_entries.options.async_configure(
            flow_id, {"name": "Demo Things", "kind": "thing", "archived": False}
        )
        assert result["step_id"] == "preview"
        result = await hass.config_entries.options.async_configure(flow_id, {"confirm": True})
        assert result["step_id"] == "result"
        assert any(g.name == "Demo Things" for g in entry.runtime_data.engine.state.groups.values())
        # A second account cannot adopt the still-open draft, even via direct flow calls.
        other = http.current_request.set({http.KEY_HASS_USER: hass_read_only_user})
        try:
            with pytest.raises(Unauthorized):
                await hass.config_entries.options.async_configure(flow_id, {})
        finally:
            http.current_request.reset(other)
    finally:
        http.current_request.reset(token)


async def test_rule_switch_retains_user_context_and_denies_missing_actor(
    hass, entry, hass_admin_user
):
    await hass.services.async_call(
        "simplifi",
        "upsert_rule",
        {
            "entry_id": entry.entry_id,
            "name": "Demo bedtime",
            "kind": "internet",
            "groups": ["demo-family"],
        },
        context=Context(user_id=hass_admin_user.id),
        blocking=True,
    )
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    rule_entity = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "switch"
    )
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": rule_entity}, context=Context(), blocking=True
        )
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": rule_entity},
        context=Context(user_id=hass_admin_user.id),
        blocking=True,
    )
    assert not next(iter(entry.runtime_data.engine.state.rules.values())).enabled


async def test_simulator_dns_cannot_reach_production(hass, entry, hass_admin_user, monkeypatch):
    import dns.asyncresolver

    def forbidden(*args, **kwargs):
        raise AssertionError("Simulator attempted a real DNS query")

    monkeypatch.setattr(dns.asyncresolver, "Resolver", forbidden)
    context = Context(user_id=hass_admin_user.id)
    await hass.services.async_call(
        "simplifi",
        "upsert_probe",
        {
            "entry_id": entry.entry_id,
            "name": "Demo list",
            "domains": ["example.org"],
            "resolver": "192.168.4.1",
            "baseline_resolver": "8.8.8.8",
        },
        context=context,
        blocking=True,
    )
    result = await hass.services.async_call(
        "simplifi",
        "check_dns",
        {"entry_id": entry.entry_id},
        context=context,
        blocking=True,
        return_response=True,
    )
    assert all(
        r["simulation"]
        for bucket in result["observations"].values()
        for r in bucket["contexts"].values()
    )
    assert all(
        "no DNS queries" in r["vantage"]
        for bucket in result["observations"].values()
        for r in bucket["contexts"].values()
    )


async def test_dashboard_reads_are_admin_only_and_do_not_create_changes(
    hass, entry, hass_admin_user, hass_read_only_user
):
    before = entry.runtime_data.engine.state.revision
    for action, data in (("dashboard_data", {}), ("dashboard_catalogue", {"kind": "category"})):
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                "simplifi",
                action,
                {"entry_id": entry.entry_id, **data},
                context=Context(user_id=hass_read_only_user.id),
                blocking=True,
                return_response=True,
            )
        result = await hass.services.async_call(
            "simplifi",
            action,
            {"entry_id": entry.entry_id, **data},
            context=Context(user_id=hass_admin_user.id),
            blocking=True,
            return_response=True,
        )
        assert result
    assert entry.runtime_data.engine.state.revision == before


async def test_dashboard_honours_stale_observations_and_resolves_actors(
    hass, entry, hass_admin_user
):
    context = Context(user_id=hass_admin_user.id)
    engine = entry.runtime_data.engine
    device_id = next(iter(engine.state.devices))
    for action, payload in (
        ("assign_device", {"device_id": device_id, "group_id": "demo-family"}),
        ("pause_internet", {"group_id": "demo-family", "duration_minutes": 30}),
    ):
        await hass.services.async_call(
            "simplifi",
            action,
            {"entry_id": entry.entry_id, **payload},
            context=context,
            blocking=True,
            return_response=True,
        )
        await hass.async_block_till_done()
    result = await hass.services.async_call(
        "simplifi",
        "dashboard_data",
        {"entry_id": entry.entry_id},
        context=context,
        blocking=True,
        return_response=True,
    )
    assert result["groups"][0]["control_state"] == "paused"
    assert result["groups"][0]["state"] == "unknown"  # Saved intent, management disabled.
    assert all(
        c["state"] == ("inherited" if c["slug"] == "adult" else "unknown")
        for c in result["groups"][0]["categories"]
    )
    assert result["groups"][0]["actor"] == hass_admin_user.name
    assert result["changes"][0]["actor"] == hass_admin_user.name
    assert "owned" not in result and "api_key" not in result and "journal" not in result
    await hass.services.async_call(
        "simplifi",
        "set_management",
        {
            "entry_id": entry.entry_id,
            "enabled": True,
            "expiry_acknowledged": True,
            "gateway_timezone_confirmed": True,
        },
        context=context,
        blocking=True,
    )
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    result = await hass.services.async_call(
        "simplifi",
        "dashboard_data",
        {"entry_id": entry.entry_id},
        context=context,
        blocking=True,
        return_response=True,
    )
    assert result["confirmed"]
    assert result["groups"][0]["state"] == "paused"
    engine.state.inventory_complete = False
    result = await hass.services.async_call(
        "simplifi",
        "dashboard_data",
        {"entry_id": entry.entry_id},
        context=context,
        blocking=True,
        return_response=True,
    )
    assert not result["fresh"]
    assert result["groups"][0]["state"] == "unknown"


async def test_dashboard_configuration_has_native_views_and_a_fallback(hass, entry):
    enhanced = generate_from_registry(hass, entry)
    assert all(v["type"] == "sections" for v in enhanced["dashboard"]["views"])
    assert all("icon" not in v for v in enhanced["dashboard"]["views"])  # Labelled tabs.
    assert enhanced["resource"].endswith(f"?v={VERSION}")
    native = generate_from_registry(hass, entry, "native")
    assert "custom:simplifi-card" not in str(native["dashboard"])


async def test_dashboard_timeline_clips_overnight_on_dst_day(hass, entry, hass_admin_user):
    from datetime import datetime

    from custom_components.simplifi.presentation import dashboard_data

    engine = entry.runtime_data.engine
    engine.clock = lambda: datetime.fromisoformat("2026-10-25T12:00:00+00:00")
    await hass.services.async_call(
        "simplifi",
        "upsert_rule",
        {
            "entry_id": entry.entry_id,
            "name": "Bedtime",
            "kind": "internet",
            "groups": ["demo-family"],
            "windows": [
                {
                    "name": "Every night",
                    "days": list(range(7)),
                    "start": "21:00",
                    "end": "07:00",
                    "overnight": True,
                    "all_day": False,
                }
            ],
        },
        context=Context(user_id=hass_admin_user.id),
        blocking=True,
    )
    data = await dashboard_data(hass, entry)
    start, end = map(datetime.fromisoformat, (data["day_start"], data["day_end"]))
    assert (end - start).total_seconds() == 25 * 3600
    timeline = data["groups"][0]["timeline"]
    assert len(timeline) == 2
    assert timeline[0]["start"] == data["day_start"]
    assert timeline[-1]["end"] == data["day_end"]


async def test_dashboard_catalogue_keeps_zero_and_bounds_search(entry):
    from custom_components.simplifi.presentation import dashboard_catalogue

    gateway = entry.runtime_data.engine.gateway
    gateway.applications = [{"id": i, "name": f"Chat app {i}"} for i in range(120)]
    result = dashboard_catalogue(entry, "application", "CHAT")
    assert result["capped"] and result["total"] == 120
    assert len(result["items"]) == 100 and result["items"][0]["id"] == 0
    assert dashboard_catalogue(entry, "category", "messaging")["items"][0]["id"] == 0


async def test_connection_error_is_visible_without_exposing_key(hass, caplog):
    import json
    from unittest.mock import patch

    from custom_components.simplifi.models import SimpliFiError

    result = await hass.config_entries.flow.async_init("simplifi", context={"source": "user"})
    with patch(
        "custom_components.simplifi.api.unifi.UniFiGateway.connect",
        side_effect=SimpliFiError("UniFi rejected the API key (HTTP 401)"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "simulation": False,
                "controller": "https://example.local",
                "api_key": "private-flow-key",
                "verify_ssl": True,
            },
        )
    assert result["type"] == "form" and result["step_id"] == "user"
    assert result["errors"] == {"base": "setup_failed"}
    assert "HTTP 401" in result["description_placeholders"]["error"]
    assert "private-flow-key" not in json.dumps(result, default=str)
    assert "private-flow-key" not in caplog.text
    assert not hass.config_entries.async_entries("simplifi")


async def test_site_error_preserves_flow_and_can_be_retried(hass, caplog):
    import json
    from unittest.mock import patch

    from custom_components.simplifi.models import SimpliFiError

    result = await hass.config_entries.flow.async_init("simplifi", context={"source": "user"})
    with patch(
        "custom_components.simplifi.api.unifi.UniFiGateway.connect",
        return_value=[{"id": "test-site", "name": "Test site"}],
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "simulation": False,
                "controller": "https://example.local",
                "api_key": "private-flow-key",
                "verify_ssl": True,
            },
        )
    assert result["step_id"] == "site"
    with patch(
        "custom_components.simplifi.api.unifi.UniFiGateway.refresh_resources",
        side_effect=SimpliFiError("Invalid pagination metadata"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"site": "test-site"}
        )
    assert result["type"] == "form" and result["step_id"] == "site"
    assert result["errors"] == {"base": "setup_failed"}
    assert result["description_placeholders"]["error"] == "Invalid pagination metadata"
    assert "private-flow-key" not in json.dumps(result, default=str)
    assert "private-flow-key" not in caplog.text

    async def retry_resources(gateway):
        gateway.zones = [
            {"id": "external", "name": "External", "metadata": {"origin": "SYSTEM_DEFINED"}}
        ]

    with patch(
        "custom_components.simplifi.api.unifi.UniFiGateway.refresh_resources",
        new=retry_resources,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"site": "test-site"}
        )
    assert result["type"] == "form" and result["step_id"] == "scope"
    assert not hass.config_entries.async_entries("simplifi")


async def real_scope_flow(hass, zones):
    """Exercise the real adapter and config flow with only the HTTP boundary replaced."""
    from unittest.mock import patch

    async def read(gateway, method, path, body=None, params=None):
        assert method == "GET" and body is None
        if path == "/v1/info":
            return {"applicationVersion": "10.6.106"}
        if path == "/v1/sites/site/networks/family":
            return {"id": "family", "internetAccessEnabled": True}
        rows = {
            "/v1/sites": [{"id": "site", "name": "Test site"}],
            "/v1/sites/site/networks": [{"id": "family", "name": "Family", "zoneId": "internal"}],
            "/v1/sites/site/firewall/zones": zones,
            "/v1/dpi/categories": [],
            "/v1/dpi/applications": [],
        }[path]
        return {"data": rows, "offset": 0, "count": len(rows), "totalCount": len(rows)}

    with patch("custom_components.simplifi.api.unifi.UniFiGateway.request", new=read):
        result = await hass.config_entries.flow.async_init("simplifi", context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "simulation": False,
                "controller": "https://example.local",
                "api_key": "private-flow-key",
                "verify_ssl": True,
            },
        )
        assert result["step_id"] == "site"
        return await hass.config_entries.flow.async_configure(result["flow_id"], {"site": "site"})


@pytest.mark.parametrize(
    "membership", [{}, {"networkIds": None}, {"networkIds": []}, {"networkIds": ["wan"]}]
)
async def test_scope_serializes_visible_external_and_saves_verified_id(hass, membership):
    from unittest.mock import patch

    from homeassistant.helpers import config_validation as cv
    from probatio import to_field_list

    result = await real_scope_flow(
        hass,
        [
            {
                "id": "external",
                "name": "External",
                "metadata": {"origin": "SYSTEM_DEFINED"},
                **membership,
            },
            {"id": "internal", "name": "Internal", "metadata": {"origin": "SYSTEM_DEFINED"}},
            {"id": "custom", "name": "External", "metadata": {"origin": "USER_DEFINED"}},
        ],
    )
    assert result["step_id"] == "scope"
    fields = to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    field = next(f for f in fields if f["name"] == "external_zone")
    assert field["default"] == "external"
    assert field["selector"]["select"]["mode"] == "dropdown"
    assert field["selector"]["select"]["options"] == [{"value": "external", "label": "External"}]
    # Bypassing the selector cannot persist another destination.
    flow = hass.config_entries.flow._progress[result["flow_id"]]
    rejected = await flow.async_step_scope(
        {"networks": ["family"], "external_zone": "internal", "timezone": "Europe/London"}
    )
    assert rejected["errors"] == {"base": "invalid_scope"}
    assert not hass.config_entries.async_entries("simplifi")
    # Omitting the preselected field uses its verified default, not a guessed ID.
    with patch("custom_components.simplifi.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"networks": ["family"], "timezone": "Europe/London"}
        )
    assert result["type"] == "create_entry"
    assert result["data"]["external_zone"] == "external"
    assert result["data"]["networks"] == ["family"]


@pytest.mark.parametrize(
    "zones", [[], [{"id": "custom", "name": "External", "metadata": {"origin": "USER_DEFINED"}}]]
)
async def test_missing_builtin_external_stays_at_retryable_site_form(hass, zones):
    result = await real_scope_flow(hass, zones)
    assert result["type"] == "form" and result["step_id"] == "site"
    assert result["errors"] == {"base": "setup_failed"}
    assert "built-in External" in result["description_placeholders"]["error"]
    assert not hass.config_entries.async_entries("simplifi")


async def test_late_dns_results_are_discarded_after_settings_edit(hass, entry, monkeypatch):
    import asyncio

    from custom_components.simplifi import coordinator as module
    from custom_components.simplifi.dns_checks import simulated_probe

    from .conftest import command

    coordinator = entry.runtime_data
    engine = coordinator.engine
    started, release = asyncio.Event(), asyncio.Event()
    original_revision = engine.state.revision

    async def delayed(spec, now=None):
        started.set()
        await release.wait()
        return await simulated_probe(spec, now)

    monkeypatch.setattr(module, "simulated_probe", delayed)
    task = hass.async_create_task(coordinator.check_dns("builtin:video"))
    await started.wait()
    await command(
        engine, "upsert_probe", probe_id="builtin:video", name="Video", domains=["changed.example"]
    )
    release.set()
    await task
    assert "builtin:video" not in engine.state.probe_results
    assert engine.state.revision == original_revision
    assert not coordinator.dns_progress["running"]


async def test_dns_service_does_not_request_policy_sync(hass, entry, hass_admin_user, monkeypatch):
    from unittest.mock import AsyncMock

    refresh = AsyncMock()
    monkeypatch.setattr(entry.runtime_data, "async_request_refresh", refresh)
    engine = entry.runtime_data.engine
    before = engine.state.revision
    await hass.services.async_call(
        "simplifi",
        "set_dns_settings",
        {
            "entry_id": entry.entry_id,
            "enabled": True,
            "household_resolver": "",
            "baseline_resolver": "https://dns.example/dns-query",
            "freshness_hours": 48,
            "group_resolvers": {"demo-family": "192.0.2.54"},
        },
        context=Context(user_id=hass_admin_user.id),
        blocking=True,
    )
    await hass.async_block_till_done()
    refresh.assert_not_called()
    assert engine.state.revision == before and engine.state.dns_revision == 1


async def test_pre_upgrade_storage_is_preserved_and_old_lists_get_defaults(hass, entry):
    from custom_components.simplifi.models import State

    storage = entry.runtime_data.storage
    raw = entry.runtime_data.engine.state.to_dict()
    raw.pop("dns_settings")
    raw.pop("dns_revision")
    raw["probes"] = {
        "custom": {
            "name": "Legacy",
            "domains": ["example.org"],
            "resolver": "192.0.2.53",
            "baseline_resolver": "192.0.2.54",
            "group_id": None,
            "revision": 3,
        }
    }
    await storage.store.async_save(raw)
    migrated = await storage.load(State("simulator", "demo-site", ["demo-family"]))
    assert (await storage.dns_backup.async_load()) == raw
    assert migrated.probes["custom"]["enabled"]
    assert migrated.probes["custom"]["category"] == "custom"
    assert len(migrated.probes) == 9
    assert migrated.revision == raw["revision"]


async def test_inventory_upgrade_backup_preserves_old_device_shape(hass, entry):
    from custom_components.simplifi.models import State

    storage = entry.runtime_data.storage
    raw = entry.runtime_data.engine.state.to_dict()
    for device in raw["devices"].values():
        for field in (
            "connected_at",
            "network_source",
            "uplink_name",
            "registrant",
            "registrant_status",
        ):
            device.pop(field)
    await storage.store.async_save(raw)
    restored = await storage.load(State("simulator", "demo-site", ["demo-family"]))
    assert await storage.inventory_backup.async_load() == raw
    await storage.save(restored)
    await storage.load(restored)
    assert await storage.inventory_backup.async_load() == raw


async def test_device_and_allowance_services_require_admin_context(hass, entry):
    from homeassistant.exceptions import Unauthorized

    for action, data in (
        ("forget_device", {"device_id": "x", "confirm": True}),
        ("edit_allowance", {"exception_id": "x", "expires_at": "2026-10-15T12:00:00Z"}),
    ):
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                "simplifi", action, {"entry_id": entry.entry_id, **data}, blocking=True
            )


async def test_network_rule_service_and_native_choices(hass, entry, hass_admin_user):
    from custom_components.simplifi.presentation import dashboard_data

    await hass.services.async_call(
        "simplifi",
        "upsert_rule",
        {
            "entry_id": entry.entry_id,
            "rule_id": "network",
            "name": "Network bedtime",
            "kind": "internet",
            "networks": ["demo-family"],
        },
        context=Context(user_id=hass_admin_user.id),
        blocking=True,
    )
    await hass.async_block_till_done()
    result = await dashboard_data(hass, entry)
    rule = next(r for r in result["rules"] if r["id"] == "network")
    assert rule["networks"] == ["demo-family"] and rule["groups"] == []
    assert not entry.runtime_data.engine.gateway.policies


async def test_recovery_remains_loaded_after_uncertain_create_restart(hass, entry, monkeypatch):
    from custom_components.simplifi.models import Conflict, Rule

    engine = entry.runtime_data.engine
    gateway = engine.gateway
    engine.state.management = True
    engine.state.rules["wide"] = Rule(
        "wide", "Whole network", "internet", [], networks=["demo-family"]
    )
    gateway.failure = "create_after"
    with pytest.raises(Conflict):
        await engine.refresh()
    assert await hass.config_entries.async_unload(entry.entry_id)
    monkeypatch.setattr("custom_components.simplifi.FakeGateway", lambda: gateway)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state.name == "LOADED"
    assert not entry.runtime_data.last_update_success
    assert (
        entry.runtime_data.engine.state.sync_status == "partial"
        or entry.runtime_data.engine.state.sync_status == "failed"
    )
    assert hass.services.has_service("simplifi", "preview_recovery")


@pytest.mark.parametrize("action", ["activity_history", "preview_recovery", "resolve_operation"])
async def test_history_recovery_require_active_admin(hass, entry, hass_read_only_user, action):
    data = {"entry_id": entry.entry_id}
    if action == "resolve_operation":
        data.update(
            operation_id="untrusted", preview_hash="untrusted", decision="attach", confirm=True
        )
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "simplifi",
            action,
            data,
            context=Context(user_id=hass_read_only_user.id),
            blocking=True,
        )


async def test_retained_sync_history_service_redacts_and_never_reconciles(
    hass, entry, hass_admin_user
):
    engine = entry.runtime_data.engine
    before = engine.state.revision
    result = await hass.services.async_call(
        "simplifi",
        "activity_history",
        {"entry_id": entry.entry_id, "kind": "sync"},
        context=Context(user_id=hass_admin_user.id),
        blocking=True,
        return_response=True,
    )
    assert result["items"][0]["outcome"] == "management_disabled"
    assert result["items"][0]["writes"] == {"create": 0, "update": 0, "delete": 0}
    assert engine.state.revision == before


async def test_calendar_and_dashboard_split_repeated_wall_time(hass, entry, hass_admin_user):
    from datetime import datetime, timedelta

    from custom_components.simplifi.calendar import SimpliFiCalendar
    from custom_components.simplifi.presentation import dashboard_data

    engine = entry.runtime_data.engine
    await hass.services.async_call(
        "simplifi",
        "assign_device",
        {
            "entry_id": entry.entry_id,
            "device_id": next(iter(engine.state.devices)),
            "group_id": "demo-family",
        },
        context=Context(user_id=hass_admin_user.id),
        blocking=True,
    )
    start = datetime.fromisoformat("2026-10-25T00:00:00+00:00")
    engine.clock = lambda: start + timedelta(minutes=15)
    await hass.services.async_call(
        "simplifi",
        "upsert_rule",
        {
            "entry_id": entry.entry_id,
            "name": "Repeated-hour restriction",
            "kind": "internet",
            "groups": ["demo-family"],
            "windows": [
                {
                    "name": "Sunday",
                    "days": [6],
                    "start": "01:10",
                    "end": "01:20",
                    "overnight": False,
                    "all_day": False,
                }
            ],
        },
        context=Context(user_id=hass_admin_user.id),
        blocking=True,
    )
    data = await dashboard_data(hass, entry)
    timeline = data["groups"][0]["timeline"]
    assert [(r["start"], r["end"]) for r in timeline] == [
        ((start + timedelta(minutes=10)).isoformat(), (start + timedelta(minutes=20)).isoformat()),
        (
            (start + timedelta(hours=1, minutes=10)).isoformat(),
            (start + timedelta(hours=1, minutes=20)).isoformat(),
        ),
    ]
    assert data["groups"][0]["next_change"] == (start + timedelta(minutes=20)).isoformat()
    calendar = SimpliFiCalendar(entry.runtime_data, entry, "test-calendar", "Projected schedule")
    events = await calendar.async_get_events(hass, start, start + timedelta(days=1))
    assert [(e.start.isoformat(), e.end.isoformat()) for e in events] == [
        (r["start"], r["end"]) for r in timeline
    ]
    engine.clock = lambda: start + timedelta(minutes=25)
    data = await dashboard_data(hass, entry)
    assert not data["rules"][0]["active"]
    assert data["groups"][0]["next_change"] == (start + timedelta(hours=1, minutes=10)).isoformat()


@pytest.mark.parametrize("failure", ["unsupported", "unauthorized", "timeout"])
async def test_setup_retry_exposes_safe_connection_reason(hass, caplog, failure):
    from unittest.mock import patch

    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.simplifi.models import SimpliFiError

    message = {
        "unsupported": "UniFi Network 10.6.110 is not supported. Check for a SimpliFi update in HACS",
        "unauthorized": "UniFi rejected the API key (HTTP 401)",
        "timeout": "The controller connection timed out; will retry",
    }[failure]
    error = (
        TimeoutError("private-timeout-detail") if failure == "timeout" else SimpliFiError(message)
    )
    item = MockConfigEntry(
        domain="simplifi",
        data={
            "simulation": False,
            "controller": "https://example.local",
            "api_key": "private-key",
            "site": "site",
            "networks": ["family"],
            "external_zone": "external",
            "timezone": "Europe/London",
        },
    )
    item.add_to_hass(hass)
    with patch("custom_components.simplifi.api.unifi.UniFiGateway.connect", side_effect=error):
        assert not await hass.config_entries.async_setup(item.entry_id)
        await hass.async_block_till_done()
    assert item.state is ConfigEntryState.SETUP_RETRY
    assert item.reason == message
    assert "private" not in caplog.text
