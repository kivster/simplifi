"""Exercise HA's authenticated HTTP/WS routes, not injected service contexts.

All users, tokens, scripts, policies and storage belong to the isolated HA test
instance. The only sockets are the harness's loopback HTTP/WebSocket server.
"""

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from homeassistant.setup import async_setup_component


@pytest.fixture
async def transports(
    hass,
    entry,
    hass_client,
    hass_ws_client,
    hass_access_token,
    hass_read_only_access_token,
    hass_admin_user,
    hass_read_only_user,
    monkeypatch,
):
    # Failed-auth logging must not perform the OS resolver's reverse-DNS lookup.
    monkeypatch.setattr(
        "homeassistant.components.http.ban.gethostbyaddr", lambda ip: ("localhost", [], [ip])
    )
    assert await async_setup_component(hass, "api", {})
    assert await async_setup_component(hass, "websocket_api", {})
    clients = {
        "admin": await hass_client(hass_access_token),
        "delegate": await hass_client(hass_read_only_access_token),
        "anonymous": await hass_client(None),
    }
    sockets = {
        "admin": await hass_ws_client(hass, hass_access_token),
        "delegate": await hass_ws_client(hass, hass_read_only_access_token),
    }

    async def rest(action, principal="delegate", *, response=True, domain="simplifi", **data):
        if domain == "simplifi":
            data = {"entry_id": entry.entry_id, **data}
        async with asyncio.timeout(10):
            result = await clients[principal].post(
                f"/api/services/{domain}/{action}" + ("?return_response" if response else ""),
                json=data,
            )
            body = await result.text()
        try:
            body = json.loads(body)
        except ValueError:
            pass
        return result.status, body

    async def ws(action, principal="delegate", *, response=True, domain="simplifi", **data):
        if domain == "simplifi":
            data = {"entry_id": entry.entry_id, **data}
        socket = sockets[principal]
        await socket.send_json_auto_id(
            {
                "type": "call_service",
                "domain": domain,
                "service": action,
                "service_data": data,
                "return_response": response,
            }
        )
        async with asyncio.timeout(10):
            return await socket.receive_json()

    async def call(transport, action, principal="delegate", **data):
        if transport == "ws":
            result = await ws(action, principal, **data)
            return result["success"], result.get("result", result.get("error"))
        code, result = await rest(action, principal, **data)
        return code == 200, result

    async def grant(scope="watch_rules", user_id=None, **data):
        code, result = await rest(
            "set_access_grant",
            "admin",
            user_id=user_id or hass_read_only_user.id,
            scope=scope,
            groups=["demo-family"],
            confirm=True,
            **data,
        )
        assert code == 200, result

    return SimpleNamespace(
        rest=rest,
        ws=ws,
        call=call,
        grant=grant,
        clients=clients,
        sockets=sockets,
        admin=hass_admin_user,
        delegate=hass_read_only_user,
    )


@pytest.fixture
async def member(hass, hass_ws_client, transports):
    from homeassistant.auth.const import GROUP_ID_USER
    from pytest_homeassistant_custom_component.common import MockUser

    user = MockUser(groups=[await hass.auth.async_get_group(GROUP_ID_USER)]).add_to_hass(hass)
    token = await hass.auth.async_create_refresh_token(user, "https://example.test/companion")
    transports.sockets["member"] = await hass_ws_client(
        hass, hass.auth.async_create_access_token(token)
    )
    await transports.grant(user_id=user.id)
    return user


async def test_http_and_websocket_grants_bind_identity_and_preserve_attribution(
    hass, entry, transports
):
    t = transports
    engine = entry.runtime_data.engine
    await t.grant()
    code, _ = await t.rest(
        "assign_device", "admin", device_id="demo-site:02:00:00:00:00:01", group_id="demo-family"
    )
    assert code == 200
    code, _ = await t.rest("set_management", "admin", enabled=True)
    assert code == 200
    await hass.async_block_till_done()
    from homeassistant.components.logbook.const import EVENT_LOGBOOK_ENTRY

    logbook = []
    remove_listener = hass.bus.async_listen(EVENT_LOGBOOK_ENTRY, logbook.append)
    code, data = await t.rest("access_status")
    assert code == 200 and data["service_response"]["scope"] == "watch_rules"
    assert "devices" not in data["service_response"]
    assert "coexistence" not in data["service_response"]
    result = await t.ws("pause_internet", group_id="demo-family", duration_minutes=30)
    assert result["success"], result
    assert result["result"]["context"]["user_id"] == t.delegate.id
    change = result["result"]["response"]
    assert change["actor"] == t.delegate.id
    await hass.async_block_till_done()
    # The queued refresh is debounced; exercise the next real coordinator tick.
    await entry.runtime_data.async_refresh()
    assert engine.state.changes[-1]["actor"] == t.delegate.id
    assert len(engine.gateway.policies) == 1
    assert next(iter(engine.gateway.policies.values()))["enabled"]
    assert any(e.context.user_id == t.delegate.id for e in logbook)
    code, response = await t.rest("resume_internet", group_id="demo-family")
    assert code == 200 and response["service_response"]["actor"] == t.delegate.id
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    assert not engine.state.exceptions
    assert engine.gateway.simulation and engine.gateway.counter == 1
    assert not engine.gateway.policies
    remove_listener()


async def test_http_and_websocket_deny_missing_grants_and_admin_data(entry, transports):
    t = transports
    before = entry.runtime_data.engine.state.revision
    code, _ = await t.rest("access_status", "anonymous")
    assert code == 401
    code, _ = await t.rest("access_status")
    assert code == 401
    denied = await t.ws("access_status")
    assert not denied["success"]
    await t.grant()
    for action in ("dashboard_data", "list_access_grants", "access_users", "preview_recovery"):
        code, _ = await t.rest(action)
        assert code == 401
        denied = await t.ws(action)
        assert not denied["success"]
    assert entry.runtime_data.engine.state.revision == before


async def test_grant_cannot_be_reused_against_a_different_integration_entry(
    hass, entry, transports
):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    other = MockConfigEntry(
        domain="simplifi",
        title="Other test household",
        data=dict(entry.data),
        unique_id="other-transport-household",
    )
    other.add_to_hass(hass)
    assert await hass.config_entries.async_setup(other.entry_id)
    await hass.async_block_till_done()
    t = transports
    await t.grant()
    before = other.runtime_data.engine.state.revision
    code, _ = await t.rest("access_status", entry_id=other.entry_id)
    assert code == 401
    denied = await t.ws("pause_internet", entry_id=other.entry_id, group_id="demo-family")
    assert not denied["success"]
    assert other.runtime_data.engine.state.revision == before
    assert not other.runtime_data.engine.state.exceptions
    assert await hass.config_entries.async_unload(other.entry_id)


@pytest.mark.parametrize("transport", ["rest", "ws"])
async def test_live_connection_rechecks_scope_revocation_and_expiry(
    hass, entry, transports, transport
):
    t = transports
    engine = entry.runtime_data.engine
    await t.grant()
    payload = {"group_id": "demo-family", "duration_minutes": 30, "request_id": "same-request"}
    ok, _ = await t.call(transport, "pause_internet", **payload)
    assert ok
    await hass.async_block_till_done()
    before = engine.state.revision
    ok, _ = await t.call(transport, "pause_internet", **payload)
    assert ok and engine.state.revision == before  # Retried request has one durable change.
    ok, _ = await t.call(transport, "pause_internet", group_id="outside-scope", duration_minutes=30)
    assert not ok and engine.state.revision == before
    code, _ = await t.rest("revoke_access_grant", "admin", user_id=t.delegate.id, confirm=True)
    assert code == 200
    ok, _ = await t.call(transport, "pause_internet", **payload)
    assert not ok and engine.state.revision == before  # Same token/WS/request ID cannot replay.
    now = engine.clock()
    await t.grant(expires_at=(now + timedelta(seconds=30)).isoformat())
    engine.clock = lambda: now + timedelta(seconds=31)
    ok, _ = await t.call(transport, "resume_internet", group_id="demo-family")
    assert not ok and engine.state.revision == before


@pytest.mark.parametrize("transport", ["rest", "ws"])
async def test_remote_caller_cannot_supply_another_actor_or_arbitrary_gateway_body(
    entry, transports, transport
):
    t = transports
    await t.grant()
    before = entry.runtime_data.engine.state.revision
    for extra in (
        {"actor": t.admin.id},
        {"user_id": t.admin.id},
        {"context": {"user_id": t.admin.id}},
        {"policy_body": {"action": {"type": "ALLOW"}}},
    ):
        if transport == "rest":
            code, _ = await t.rest(
                "pause_internet", group_id="demo-family", duration_minutes=30, **extra
            )
            assert code == 400
        else:
            result = await t.ws(
                "pause_internet", group_id="demo-family", duration_minutes=30, **extra
            )
            assert not result["success"] and result["error"]["code"] == "invalid_format"
    assert entry.runtime_data.engine.state.revision == before
    assert not entry.runtime_data.engine.state.exceptions


@pytest.mark.parametrize("transport", ["rest", "ws"])
async def test_readonly_and_agent_editors_keep_their_bounds(hass, entry, transports, transport):
    t = transports
    engine = entry.runtime_data.engine
    await t.grant("read_only")
    ok, _ = await t.call(transport, "access_status")
    assert ok
    before = engine.state.revision
    ok, _ = await t.call(transport, "pause_internet", group_id="demo-family")
    assert not ok and engine.state.revision == before
    await t.grant("agent_controls")
    ok, _ = await t.call(transport, "upsert_group", group_id="demo-family", name="Delegated edit")
    assert ok
    await hass.async_block_till_done()
    assert engine.state.groups["demo-family"].name == "Delegated edit"
    assert engine.state.changes[-1]["actor"] == t.delegate.id
    before = engine.state.revision
    for action, payload in (
        ("upsert_group", {"name": "Outside scope"}),
        ("set_management", {"enabled": True}),
        (
            "set_access_grant",
            {
                "user_id": t.delegate.id,
                "scope": "agent_controls",
                "all_groups": True,
                "confirm": True,
            },
        ),
        ("set_dns_settings", {**engine.state.dns_settings, "enabled": False}),
    ):
        ok, _ = await t.call(transport, action, **payload)
        assert not ok
    assert engine.state.revision == before


async def test_script_wrapper_preserves_authenticated_actor_and_denies_contextless_runs(
    hass, entry, transports, member
):
    from homeassistant.core import Context
    from homeassistant.exceptions import Unauthorized

    t = transports
    engine = entry.runtime_data.engine
    await t.grant()
    # Real native script component and its service, configured only in this harness.
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "family_pause_test": {
                    "sequence": [
                        {
                            "action": "simplifi.pause_internet",
                            "data": {
                                "entry_id": entry.entry_id,
                                "group_id": "demo-family",
                                "duration_minutes": 30,
                            },
                        },
                    ]
                }
            }
        },
    )
    result = await t.ws("family_pause_test", "member", domain="script", response=False)
    assert result["success"], result
    await hass.async_block_till_done()
    assert engine.state.changes[-1]["actor"] == member.id
    # A HA read-only account can invoke a named script service; the explicit
    # SimpliFi grant, checked by the inner action, is the boundary here.
    result = await t.ws("family_pause_test", domain="script", response=False)
    assert result["success"] and engine.state.changes[-1]["actor"] == t.delegate.id
    await t.grant("read_only")
    before = engine.state.revision
    denied = await t.ws("family_pause_test", domain="script", response=False)
    assert not denied["success"] and engine.state.revision == before
    code, _ = await t.rest("revoke_access_grant", "admin", user_id=member.id, confirm=True)
    assert code == 200
    denied = await t.ws("family_pause_test", "member", domain="script", response=False)
    assert not denied["success"] and engine.state.revision == before
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "script", "family_pause_test", {}, blocking=True, context=Context()
        )
    assert engine.state.revision == before


async def test_native_rule_switch_over_websocket_keeps_identity_and_revocation(
    hass, entry, transports, member
):
    from homeassistant.helpers import entity_registry as er

    t = transports
    engine = entry.runtime_data.engine
    code, _ = await t.rest(
        "upsert_rule",
        "admin",
        rule_id="transport-rule",
        name="Transport rule",
        kind="internet",
        groups=["demo-family"],
    )
    assert code == 200
    await hass.async_block_till_done()
    entity = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == "switch" and "transport-rule" in e.unique_id
    )
    result = await t.ws("turn_off", "member", domain="switch", response=False, entity_id=entity)
    assert result["success"], result
    assert not engine.state.rules["transport-rule"].enabled
    assert engine.state.changes[-1]["actor"] == member.id
    before = engine.state.revision
    code, _ = await t.rest("revoke_access_grant", "admin", user_id=member.id, confirm=True)
    assert code == 200
    denied = await t.ws("turn_on", "member", domain="switch", response=False, entity_id=entity)
    assert not denied["success"]
    assert not engine.state.rules["transport-rule"].enabled and engine.state.revision == before
