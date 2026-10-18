"""UniFi's bodyless HTTP 200 delete still requires a complete policy readback."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.family_network.api.unifi import UniFiGateway
from custom_components.family_network.models import Conflict, FamilyError

from .conftest import command


def response_context(status, effect=None):
    response = MagicMock(status=status)
    response.json = AsyncMock(side_effect=ValueError("empty response body"))

    async def enter():
        if effect:
            effect()
        return response

    context = MagicMock()
    context.__aenter__ = AsyncMock(side_effect=enter)
    context.__aexit__ = AsyncMock(return_value=None)
    return context, response


@pytest.mark.parametrize("status", [200, 204])
@pytest.mark.parametrize("deleted", [True, False])
async def test_empty_delete_receipt_requires_absent_policy_readback(household, status, deleted):
    engine, simulated, _, _ = household
    await command(engine, "set_management", enabled=True, gateway_timezone_confirmed=True)
    await command(engine, "pause_internet", group_id="child", duration_minutes=2)
    await engine.refresh()
    assert len(simulated.policies) == 2
    session = MagicMock()
    responses = []

    def request(method, url, **kwargs):
        assert method == "DELETE"
        policy_id = url.rsplit("/", 1)[-1]
        context, response = response_context(
            status, (lambda: simulated.policies.pop(policy_id)) if deleted else None
        )
        responses.append(response)
        return context

    session.request.side_effect = request
    adapter = UniFiGateway(session, "https://controller.test", "test-key")
    adapter.site = "test-site"
    simulated.delete = adapter.delete
    await command(engine, "resume_internet", group_id="child")
    if deleted:
        await engine.refresh()
        assert engine.state.sync_status == "applied"
        assert not engine.state.owned and not simulated.policies
        assert all(op["status"] == "verified" for op in engine.state.journal)
        assert session.request.call_count == 2
    else:
        with pytest.raises(Conflict, match="Deletion not confirmed"):
            await engine.refresh()
        assert engine.state.sync_status != "applied"
        assert len(engine.state.owned) == 2
        with pytest.raises(Conflict, match="Original policy is still present"):
            await engine.refresh()
        assert session.request.call_count == 1  # Never blindly repeat a write.
    for response in responses:
        response.json.assert_not_awaited()


@pytest.mark.parametrize("method", ["GET", "POST", "PUT"])
async def test_empty_http_200_is_not_accepted_for_json_endpoints(method):
    context, response = response_context(200)
    session = MagicMock()
    session.request.return_value = context
    gateway = UniFiGateway(session, "https://controller.test", "test-key")
    with pytest.raises(FamilyError, match="Malformed gateway response"):
        await gateway.request(method, "/v1/sites/test-site/firewall/policies")
    response.json.assert_awaited_once()


@pytest.mark.parametrize("status", [403, 429, 503])
async def test_failed_delete_is_not_accepted_or_retried(status):
    context, response = response_context(status)
    session = MagicMock()
    session.request.return_value = context
    gateway = UniFiGateway(session, "https://controller.test", "test-key")
    with pytest.raises(FamilyError, match=str(status)):
        await gateway.delete("test-policy")
    session.request.assert_called_once()
    response.json.assert_not_awaited()
