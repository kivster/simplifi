"""HA actions: authenticated context only, strict schemas, explicit response contract."""

from copy import deepcopy

import probatio as vol
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError, Unauthorized

from .actions import DNS_ACTIONS, SCHEMAS, UPDATE_ACTIONS
from .const import DOMAIN
from .models import FamilyError
from .permissions import active_user, admitted_user


@callback
def register_services(hass):
    for action, schema in SCHEMAS.items():
        if hass.services.has_service(DOMAIN, action):
            continue

        async def handle(call, action=action):
            user = await active_user(hass, call.context.user_id)
            entry = hass.config_entries.async_get_entry(call.data["entry_id"])
            if entry is None or entry.domain != DOMAIN or entry.state.name != "LOADED":
                raise ServiceValidationError("Select a loaded SimpliFi entry")
            coordinator = entry.runtime_data
            user = await admitted_user(hass, user.id, coordinator.engine)
            actor = user.id
            from .access import EDITOR_ACTIONS, GROUP_CONTROLS, QUARANTINE_CONTROLS, RULE_CONTROLS

            if (
                not user.is_admin
                and action
                not in GROUP_CONTROLS
                | RULE_CONTROLS
                | QUARANTINE_CONTROLS
                | EDITOR_ACTIONS
                | {"access_status", "edit_allowance"}
            ):
                raise Unauthorized()
            data = {k: v for k, v in call.data.items() if k != "entry_id"}
            try:
                if action in UPDATE_ACTIONS:
                    if action in {"update_status", "check_updates"}:
                        return coordinator.updates.status()
                    raise FamilyError(
                        "SimpliFi updates are managed through HACS. "
                        "Legacy installation, scheduling and recovery actions are disabled."
                    )
                if action == "access_users":
                    return {
                        "users": [
                            {"id": u.id, "name": u.name}
                            for u in await hass.auth.async_get_users()
                            if u.is_active and not u.is_admin and not u.system_generated
                        ]
                    }
                if action == "set_access_grant":
                    target = await hass.auth.async_get_user(data["user_id"])
                    if (
                        target is None
                        or not target.is_active
                        or target.is_admin
                        or target.system_generated
                    ):
                        raise FamilyError(
                            "Select an existing active, non-administrator Home Assistant user"
                        )
                if action == "activity_history":
                    from .history import page

                    query = {k: data[k] for k in ("before_id", "limit", "outcome") if k in data}
                    if "change_id" in data:
                        if data["kind"] != "sync":
                            raise FamilyError("Choose sync history to inspect a change's attempts")
                        async with coordinator.engine.lock:
                            change = next(
                                (
                                    deepcopy(c)
                                    for c in coordinator.engine.state.changes
                                    if c["id"] == data["change_id"]
                                ),
                                None,
                            )
                        if change is None:
                            raise FamilyError("This change is no longer retained; open all history")
                        if (
                            "dns_revision" in change
                            or "access_revision" in change
                            or change["outcome"]
                            not in (
                                "pending",
                                "applying",
                                "applied",
                                "failed",
                                "partial",
                                "superseded",
                                "saved_management_disabled",
                            )
                        ):
                            raise FamilyError("This action does not have policy sync results")
                        result = await coordinator.storage.history.for_change(change, **query)
                        attributed = [result["change"]]
                    elif data["kind"] == "sync":
                        return await coordinator.storage.history.read(**query)
                    else:
                        async with coordinator.engine.lock:
                            result = page(coordinator.engine.state.changes, **query)
                        attributed = result["items"]
                    for row in attributed:
                        row.pop("digest", None)
                        row.pop("request_id", None)
                        user = await hass.auth.async_get_user(row["actor"])
                        row["actor"] = user.name if user else "Former administrator"
                    return result
                if action == "dashboard_data":
                    from .presentation import dashboard_data

                    return await dashboard_data(hass, entry)
                if action == "dashboard_catalogue":
                    from .presentation import dashboard_catalogue

                    return dashboard_catalogue(entry, data["kind"], data["query"])
                if action == "dashboard_configuration":
                    from .dashboard import generate_from_registry

                    return generate_from_registry(hass, entry, data["presentation"])
                result = await coordinator.engine.command(
                    action, data, actor, administrator=user.is_admin
                )
                coordinator.schedule_deadline()
                await coordinator.storage.history.observe_changes(coordinator.engine.state.changes)
                if action == "check_dns":
                    if coordinator.engine.gateway.simulation:
                        await coordinator.check_dns(data.get("probe_id"), data.get("group_id"))
                        return {
                            "change": result,
                            "observations": deepcopy(coordinator.engine.state.probe_results),
                        }
                    started = coordinator.start_dns(data.get("probe_id"), data.get("group_id"))
                    return {"change": result, "queued": started, "already_running": not started}
                elif action in DNS_ACTIONS or action in ("set_access_grant", "revoke_access_grant"):
                    coordinator.async_set_updated_data(coordinator.engine.state)
                elif not coordinator.closing and action not in (
                    "preview_setup",
                    "access_status",
                    "list_access_grants",
                    "export_configuration",
                    "preview_import",
                    "cleanup_owned",
                    "view_activity",
                    "preview_recovery",
                ):
                    entry.async_create_background_task(
                        hass, coordinator.async_request_refresh(), "family_network_sync"
                    )
                return result
            except FamilyError as err:
                raise ServiceValidationError(str(err)) from None

        async def guarded_handle(call, handle=handle):
            entry = hass.config_entries.async_get_entry(call.data["entry_id"])
            if entry is not None and entry.domain == DOMAIN and entry.state.name == "LOADED":
                try:
                    with entry.runtime_data.operation():
                        return await handle(call)
                except FamilyError as err:
                    raise ServiceValidationError(str(err)) from None
            return await handle(call)

        hass.services.async_register(
            DOMAIN,
            action,
            guarded_handle,
            schema=vol.Schema({vol.Required("entry_id"): str, **schema.schema}),
            supports_response=SupportsResponse.OPTIONAL,
        )
