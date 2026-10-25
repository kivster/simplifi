"""Administrator-only native reconfiguration with a durable binding handoff."""

import asyncio
from copy import deepcopy
from zoneinfo import available_timezones

import probatio as vol
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import selector

from .api.unifi import UniFiGateway, external_zone_id
from .binding import binding, review_state
from .const import DOMAIN
from .models import Conflict, SimpliFiError, State, fingerprint, uid, utcnow
from .portable import clean_binding, export, prepare
from .storage import HouseholdStorage


class ConnectionFlow:
    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        errors, placeholders = {}, {}
        if user_input is not None:
            # HA starts reauth without a web request. Only a submitting admin may
            # validate and replace the credential; controller/site stay fixed.
            await self._connection_actor()
            try:
                gateway = UniFiGateway(
                    async_get_clientsession(self.hass),
                    entry.data["controller"],
                    user_input["api_key"],
                    site=entry.data["site"],
                    verify_ssl=entry.data.get("verify_ssl", True),
                )
                sites = await gateway.connect()
                if entry.data["site"] not in {s["id"] for s in sites}:
                    raise SimpliFiError("This API key cannot access the configured site")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={"api_key": gateway.api_key},
                    reason="reauth_successful",
                )
            except (SimpliFiError, TimeoutError) as error:
                errors["base"] = "setup_failed"
                placeholders["error"] = (
                    str(error)
                    if isinstance(error, SimpliFiError)
                    else "Controller request timed out"
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required("api_key"): selector({"text": {"type": "password"}})}
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _connection_actor(self):
        from .config_flow import request_actor

        actor = await request_actor(self.hass)
        if getattr(self, "connection_actor", actor) != actor:
            raise SimpliFiError("This connection review belongs to another administrator")
        self.connection_actor = actor

    async def _connection_state(self):
        entry = self._get_reconfigure_entry()
        if entry.state.name == "LOADED":
            return deepcopy(entry.runtime_data.engine.state)
        data = entry.data
        return await HouseholdStorage(self.hass, entry.entry_id).load(
            State(data["controller"], data["site"], list(data["networks"]), data["timezone"]),
            data.get("binding_token"),
        )

    async def async_step_reconfigure(self, user_input=None):
        await self._connection_actor()
        entry = self._get_reconfigure_entry()
        if entry.data.get("simulation"):
            return self.async_abort(reason="simulator_reconfigure")
        errors, placeholders = {}, {}
        if user_input is not None:
            try:
                old = entry.data
                host = user_input["controller"].rstrip("/")
                key = user_input.get("api_key", "").strip()
                if not key:
                    if host != old["controller"].rstrip("/"):
                        raise SimpliFiError(
                            "Enter a new API key when changing the controller address"
                        )
                    key = old["api_key"]
                self.connection_gateway = UniFiGateway(
                    async_get_clientsession(self.hass),
                    host,
                    key,
                    verify_ssl=user_input["verify_ssl"],
                )
                self.connection_sites = await self.connection_gateway.connect()
                self.connection_data = {
                    **dict(old),
                    "controller": self.connection_gateway.controller,
                    "api_key": self.connection_gateway.api_key,
                    "verify_ssl": user_input["verify_ssl"],
                }
                self.connection_original = fingerprint(dict(old))
                return await self.async_step_connection_site()
            except (SimpliFiError, TimeoutError) as error:
                errors["base"] = "setup_failed"
                placeholders["error"] = str(error) or "Controller request timed out"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required("controller", default=entry.data["controller"]): str,
                    vol.Optional("api_key", default=""): selector({"text": {"type": "password"}}),
                    vol.Required("verify_ssl", default=entry.data.get("verify_ssl", True)): bool,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_connection_site(self, user_input=None):
        await self._connection_actor()
        errors, placeholders = {}, {}
        if user_input is not None:
            try:
                if user_input["site"] not in {s["id"] for s in self.connection_sites}:
                    raise SimpliFiError("Select a site returned by this controller")
                self.connection_gateway.site = user_input["site"]
                await self.connection_gateway.refresh_resources()
                self.connection_data["site"] = user_input["site"]
                return await self.async_step_connection_scope()
            except (SimpliFiError, TimeoutError) as error:
                errors["base"] = "setup_failed"
                placeholders["error"] = str(error) or "Site request timed out"
        sites = [{"value": s["id"], "label": s["name"]} for s in self.connection_sites]
        default = self.connection_data["site"]
        marker = (
            vol.Required("site", default=default)
            if default in {s["value"] for s in sites}
            else vol.Required("site")
        )
        return self.async_show_form(
            step_id="connection_site",
            data_schema=vol.Schema(
                {
                    marker: selector({"select": {"options": sites}}),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_connection_scope(self, user_input=None):
        await self._connection_actor()
        errors, placeholders = {}, {}
        gateway = self.connection_gateway
        destination = external_zone_id(gateway.zones)
        if user_input is not None:
            try:
                if (
                    not user_input["networks"]
                    or not set(user_input["networks"]) <= set(gateway.networks)
                    or user_input["external_zone"] != destination
                    or user_input["timezone"] not in available_timezones()
                ):
                    raise SimpliFiError(
                        "Select explicit networks, the External zone and a timezone"
                    )
                self.connection_data.update(user_input)
                self.connection_data["networks"] = sorted(set(user_input["networks"]))
                original_networks = self._get_reconfigure_entry().data["networks"]
                if set(original_networks) == set(self.connection_data["networks"]):
                    self.connection_data["networks"] = list(original_networks)
                self.connection_mapping = {}
                state = await self._connection_state()
                self.connection_changed = binding(self.connection_data) != binding(
                    dict(self._get_reconfigure_entry().data)
                )
                if self.connection_changed:
                    clean_binding(state)
                    if (state.controller, state.site, sorted(state.networks)) != (
                        gateway.controller,
                        gateway.site,
                        self.connection_data["networks"],
                    ):
                        self.connection_source_networks = list(state.networks)
                        return await self.async_step_connection_mapping()
                    self.connection_mapping = {n: n for n in state.networks}
                return await self._connection_review_start()
            except (SimpliFiError, TimeoutError) as error:
                errors["base"] = "setup_failed"
                placeholders["error"] = str(error) or "Scope request timed out"
        selected = [n for n in self.connection_data["networks"] if n in gateway.networks]
        return self.async_show_form(
            step_id="connection_scope",
            data_schema=vol.Schema(
                {
                    vol.Required("networks", default=selected): selector(
                        {
                            "select": {
                                "multiple": True,
                                "options": [
                                    {"value": n, "label": v["name"]}
                                    for n, v in gateway.networks.items()
                                ],
                            }
                        }
                    ),
                    vol.Required("external_zone", default=destination): selector(
                        {"select": {"options": [{"value": destination, "label": "External"}]}}
                    ),
                    vol.Required("timezone", default=self.connection_data["timezone"]): selector(
                        {"select": {"options": sorted(available_timezones())}}
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_connection_mapping(self, user_input=None):
        await self._connection_actor()
        errors, placeholders = {}, {}
        source = next(
            (n for n in self.connection_source_networks if n not in self.connection_mapping), None
        )
        if source is None:
            return await self._connection_review_start()
        if user_input is not None:
            if user_input["network"] not in self.connection_data["networks"]:
                errors["base"] = "invalid_scope"
            else:
                self.connection_mapping[source] = user_input["network"]
                return await self.async_step_connection_mapping()
        placeholders["source"] = source
        placeholders["position"] = str(len(self.connection_mapping) + 1)
        placeholders["total"] = str(len(self.connection_source_networks))
        return self.async_show_form(
            step_id="connection_mapping",
            data_schema=vol.Schema(
                {
                    vol.Required("network"): selector(
                        {
                            "select": {
                                "options": [
                                    {
                                        "value": n,
                                        "label": self.connection_gateway.networks[n]["name"],
                                    }
                                    for n in self.connection_data["networks"]
                                ]
                            }
                        }
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _connection_review_start(self):
        state = await self._connection_state()
        self.connection_review = review_state(state)
        self.connection_resources = fingerprint(self.connection_gateway.networks)
        self.connection_counts = f"{len(state.groups)} groups, {len(state.rules)} rules, {sum(bool(d.group) for d in state.devices.values())} device assignments"
        return await self.async_step_connection_review()

    async def async_step_connection_review(self, user_input=None):
        await self._connection_actor()
        errors, placeholders = {}, {}
        if user_input is not None and user_input["confirm"]:
            try:
                entry = self._get_reconfigure_entry()
                if fingerprint(dict(entry.data)) != self.connection_original:
                    raise Conflict("Connection settings changed; start a new review")
                # The final capability/resource check is read-only. Never copy credentials to a transaction store.
                await self.connection_gateway.refresh_resources()
                if (
                    fingerprint(self.connection_gateway.networks) != self.connection_resources
                    or external_zone_id(self.connection_gateway.zones)
                    != self.connection_data["external_zone"]
                ):
                    raise Conflict("Controller resources changed; start a new review")
                unique_id = f"{self.connection_data['controller']}:{self.connection_data['site']}"
                if any(
                    e.entry_id != entry.entry_id and e.unique_id == unique_id
                    for e in self.hass.config_entries.async_entries(DOMAIN)
                ):
                    raise Conflict("This controller and site already have a SimpliFi entry")
                locks = self.hass.data.setdefault(DOMAIN, {}).setdefault("connection_locks", {})
                async with locks.setdefault(entry.entry_id, asyncio.Lock()):
                    if entry.state.name in ("SETUP_IN_PROGRESS", "UNLOAD_IN_PROGRESS"):
                        raise Conflict("Wait for the integration to finish loading or unloading")
                    engine = entry.runtime_data.engine if entry.state.name == "LOADED" else None
                    if engine:
                        async with engine.lock:
                            engine.ensure_available()
                            return await self._connection_commit(
                                entry, engine.state, engine, unique_id
                            )
                    return await self._connection_commit(
                        entry, await self._connection_state(), None, unique_id
                    )
            except (SimpliFiError, TimeoutError) as error:
                errors["base"] = "setup_failed"
                placeholders["error"] = str(error) or "Controller request timed out"
        placeholders.update(
            controller=self.connection_data["controller"],
            site=self.connection_data["site"],
            networks=", ".join(
                self.connection_gateway.networks[n]["name"]
                for n in self.connection_data["networks"]
            ),
            timezone=self.connection_data["timezone"],
            counts=self.connection_counts,
            tls="Verified"
            if self.connection_data["verify_ssl"]
            else "Certificate verification disabled",
            mapping=", ".join(
                f"{source} → {self.connection_gateway.networks[target]['name']}"
                for source, target in self.connection_mapping.items()
            )
            or "Unchanged",
            consequence=(
                "Management stays disabled. Assignments are matched again by MAC; temporary exceptions and access grants are cleared. Review DNS settings and confirm gateway timezone before enabling management."
                if self.connection_changed
                else "Only connection credentials or TLS settings change. Existing household settings and policy ownership are retained."
            ),
        )
        return self.async_show_form(
            step_id="connection_review",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): bool,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _connection_commit(self, entry, state, engine, unique_id):
        if fingerprint(dict(entry.data)) != self.connection_original:
            raise Conflict("Connection settings changed; start a new review")
        if review_state(state) != self.connection_review:
            raise Conflict("Household settings changed; start a new connection review")
        data = dict(self.connection_data)
        if self.connection_changed:
            clean_binding(state)
            target = deepcopy(state)
            target.controller, target.site = data["controller"], data["site"]
            target.networks, target.devices = data["networks"], {}
            target.quarantine_excluded = []
            draft, _ = prepare(
                target, export(state), self.connection_mapping, self.connection_actor
            )
            draft.timezone = data["timezone"]
            for key, group in state.groups.items():
                draft.groups[key].person = group.person
            draft.binding_token = data["binding_token"] = uid()
            draft.revision += 1
            draft.changes.append(
                {
                    "id": uid(),
                    "revision": draft.revision,
                    "actor": self.connection_actor,
                    "action": "reconfigure_connection",
                    "targets": {},
                    "reason": "Reviewed controller/site/scope/timezone change",
                    "requested_at": utcnow().isoformat(),
                    "outcome": "saved_management_disabled",
                }
            )
            draft.validate()
            storage = HouseholdStorage(self.hass, entry.entry_id)
            await storage.stage_binding(state, draft, data)
        if engine:
            engine.reconfiguring = True
        return self.async_update_reload_and_abort(entry, data=data, unique_id=unique_id)
