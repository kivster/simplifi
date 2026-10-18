"""Native HA setup and actor-bound options forms. Management starts disabled."""

import logging
from copy import deepcopy
from dataclasses import asdict

import probatio as vol
from homeassistant import config_entries
from homeassistant.components import http
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import selector

from .actions import DNS_ACTIONS, SCHEMAS, SPECS
from .api.unifi import UniFiGateway, external_zone_id
from .connection import ConnectionFlow
from .const import DOMAIN
from .models import FamilyError, Window, uid
from .permissions import require_admin

_LOGGER = logging.getLogger(__name__)


def weekday_options():
    return [
        {"value": str(i), "label": name}
        for i, name in enumerate(
            ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        )
    ]


async def request_actor(hass):
    request = http.current_request.get()
    user = request.get(http.KEY_HASS_USER) if request is not None else None
    return await require_admin(hass, user.id if user else None)


class FamilyNetworkConfigFlow(ConnectionFlow, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        placeholders = {}
        if user_input is not None:
            if user_input["simulation"]:
                await self.async_set_unique_id("family_network_simulator")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="SimpliFi · Simulator",
                    data={
                        "simulation": True,
                        "controller": "simulator",
                        "site": "demo-site",
                        "networks": ["demo-family"],
                        "timezone": "Europe/London",
                    },
                )
            try:
                self.gateway = UniFiGateway(
                    async_get_clientsession(self.hass),
                    user_input["controller"],
                    user_input["api_key"],
                    verify_ssl=user_input["verify_ssl"],
                )
                self.sites = await self.gateway.connect()
                self.connection = {**user_input, "api_key": self.gateway.api_key}
                return await self.async_step_site()
            except FamilyError as err:
                errors["base"] = "setup_failed"
                placeholders["error"] = str(err)
                _LOGGER.warning("SimpliFi connection setup failed: %s", err)
            except TimeoutError:
                errors["base"] = "setup_failed"
                placeholders["error"] = (
                    "The controller did not respond before the request timed out"
                )
                _LOGGER.warning("SimpliFi connection setup timed out")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("simulation", default=True): bool,
                    vol.Optional("controller", default="https://unifi.local"): str,
                    vol.Optional("api_key", default=""): selector({"text": {"type": "password"}}),
                    vol.Required("verify_ssl", default=True): bool,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_site(self, user_input=None):
        errors = {}
        placeholders = {}
        if user_input is not None:
            if user_input["site"] not in {s["id"] for s in self.sites}:
                return self.async_abort(reason="invalid_scope")
            self.gateway.site = user_input["site"]
            try:
                await self.gateway.refresh_resources()
            except FamilyError as err:
                errors["base"] = "setup_failed"
                placeholders["error"] = str(err)
                _LOGGER.warning("SimpliFi site setup failed: %s", err)
            except TimeoutError:
                errors["base"] = "setup_failed"
                placeholders["error"] = "Reading this site's resources timed out"
                _LOGGER.warning("SimpliFi site setup timed out")
            else:
                return await self.async_step_scope()
        return self.async_show_form(
            step_id="site",
            data_schema=vol.Schema(
                {
                    vol.Required("site"): selector(
                        {
                            "select": {
                                "options": [
                                    {"value": s["id"], "label": s["name"]} for s in self.sites
                                ]
                            }
                        }
                    )
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_scope(self, user_input=None):
        errors = {}
        destination = external_zone_id(self.gateway.zones)
        if user_input is not None:
            if (
                not user_input["networks"]
                or not set(user_input["networks"]) <= set(self.gateway.networks)
                or user_input["external_zone"] != destination
            ):
                errors["base"] = "invalid_scope"
            else:
                await self.async_set_unique_id(f"{self.gateway.controller}:{self.gateway.site}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="SimpliFi",
                    data={
                        **self.connection,
                        **user_input,
                        "site": self.gateway.site,
                        "simulation": False,
                    },
                )
        return self.async_show_form(
            step_id="scope",
            data_schema=vol.Schema(
                {
                    vol.Required("networks"): selector(
                        {
                            "select": {
                                "multiple": True,
                                "options": [
                                    {"value": k, "label": n["name"]}
                                    for k, n in self.gateway.networks.items()
                                ],
                            }
                        }
                    ),
                    vol.Required("external_zone", default=destination): selector(
                        {
                            "select": {
                                "mode": "dropdown",
                                "options": [{"value": destination, "label": "External"}],
                            }
                        }
                    ),
                    vol.Required("timezone", default="Europe/London"): selector(
                        {"select": {"options": ["Europe/London"]}}
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return FamilyNetworkOptionsFlow()


class FamilyNetworkOptionsFlow(config_entries.OptionsFlow):
    """The authenticated request actor is captured, then verified on every step."""

    async def _authorise(self):
        actor = await request_actor(self.hass)
        if getattr(self, "actor", actor) != actor:
            raise FamilyError("This editor belongs to another administrator")
        self.actor = actor
        self.coordinator = self.config_entry.runtime_data
        self.engine = self.coordinator.engine

    async def async_step_init(self, user_input=None):
        await self._authorise()
        self.revision = self.engine.state.revision
        self.dns_revision = self.engine.state.dns_revision
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "groups",
                "devices",
                "rules",
                "controls",
                "dns",
                "management",
                "updates",
                "recovery",
            ],
        )

    async def _choose(self, step, actions, user_input=None):
        await self._authorise()
        if user_input is not None:
            if user_input["action"] not in actions:
                raise FamilyError("Invalid editor action")
            self.action = user_input["action"]
            self.revision = self.engine.state.revision
            self.dns_revision = self.engine.state.dns_revision
            self.draft = {}
            return await self.async_step_edit()
        return self.async_show_form(
            step_id=step,
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector(
                        {
                            "select": {
                                "options": [
                                    {"value": a, "label": a.replace("_", " ").capitalize()}
                                    for a in actions
                                ]
                            }
                        }
                    )
                }
            ),
        )

    async def async_step_groups(self, user_input=None):
        return await self._choose("groups", ["upsert_group", "delete_group"], user_input)

    async def async_step_devices(self, user_input=None):
        return await self._choose(
            "devices",
            [
                "assign_device",
                "forget_device",
                "set_quarantine",
                "suspend_quarantine",
                "extend_quarantine_suspension",
                "resume_quarantine",
            ],
            user_input,
        )

    async def async_step_rules(self, user_input=None):
        return await self._choose(
            "rules",
            [
                "upsert_rule",
                "delete_rule",
                "suspend_rule",
                "resume_rule",
                "extend_rule_suspension",
                "allow_rule",
                "end_rule_allowance",
                "edit_allowance",
            ],
            user_input,
        )

    async def async_step_controls(self, user_input=None):
        return await self._choose(
            "controls",
            [
                "pause_internet",
                "resume_internet",
                "extend_pause",
                "allow_internet",
                "end_allowance",
                "unblock_group",
                "end_group_unblock",
                "extend_group_unblock",
                "edit_allowance",
                "sync_now",
            ],
            user_input,
        )

    async def async_step_dns(self, user_input=None):
        return await self._choose(
            "dns",
            [
                "upsert_probe",
                "delete_probe",
                "restore_probe",
                "set_dns_settings",
                "set_probe_schedule",
                "check_dns",
            ],
            user_input,
        )

    async def async_step_updates(self, user_input=None):
        await self._authorise()
        return self.async_abort(reason="updates_managed_by_hacs")

    async def async_step_management(self, user_input=None):
        return await self._choose("management", ["set_management"], user_input)

    async def async_step_recovery(self, user_input=None):
        return await self._choose(
            "recovery",
            [
                "export_configuration",
                "preview_import",
                "apply_import",
                "cleanup_owned",
                "view_activity",
            ],
            user_input,
        )

    def _schema(self):
        state = self.engine.state
        choices = {
            "group_id": {k: g.name for k, g in state.groups.items()},
            "groups": {k: g.name for k, g in state.groups.items()},
            "networks": {
                k: self.engine.gateway.networks[k]["name"]
                for k in state.networks
                if k in self.engine.gateway.networks
            },
            "device_id": {k: d.name for k, d in state.devices.items()},
            "excluded_devices": {k: d.name for k, d in state.devices.items()},
            "rule_id": {k: r.name for k, r in state.rules.items()},
            "probe_id": {k: p["name"] for k, p in state.probes.items()},
            "exception_id": {
                k: " · ".join(
                    [
                        state.groups[e.group].name if e.group else "Everyone on this rule",
                        state.rules[e.rule].name if e.rule else "Internet allowance",
                        e.expires_at or "No deadline",
                    ]
                )
                for k, e in state.exceptions.items()
                if e.kind in ("internet_allow", "rule_allow") and e.active(self.engine.clock())
            },
        }
        result = {}
        for marker, validator in SPECS[self.action].items():
            key = str(marker)
            if key in ("windows", "expected_revision", "targets"):
                continue
            if key in choices:
                options = [{"value": k, "label": v} for k, v in choices[key].items()]
                if key in ("group_id", "rule_id", "probe_id") and isinstance(marker, vol.Optional):
                    options.insert(0, {"value": "", "label": "New / none / all (as applicable)"})
                result[marker] = selector(
                    {
                        "select": {
                            "options": options,
                            "multiple": key in ("groups", "networks", "excluded_devices"),
                        }
                    }
                )
            elif key == "person":
                result[marker] = selector({"entity": {"domain": "person"}})
            elif key == "domains":
                result[marker] = selector(
                    {"select": {"options": [], "multiple": True, "custom_value": True}}
                )
            elif key == "days":
                result[marker] = selector(
                    {"select": {"options": weekday_options(), "multiple": True}}
                )
            elif key in ("configuration", "group_resolvers", "network_mapping"):
                result[marker] = selector({"object": {}})
            elif key == "freshness_hours":
                result[marker] = selector({"number": {"min": 1, "max": 168, "mode": "box"}})
            elif key == "category":
                from .dns_catalog import CATEGORIES

                result[marker] = selector({"select": {"options": ["custom", *CATEGORIES]}})
            elif key == "duration_minutes":
                result[marker] = selector({"number": {"min": 1, "max": 10080, "mode": "box"}})
            elif key == "kind":
                result[marker] = selector(
                    {
                        "select": {
                            "options": ["family", "thing"]
                            if self.action == "upsert_group"
                            else ["internet", "category", "application", "domain"]
                        }
                    }
                )
            elif key == "age":
                result[marker] = selector({"select": {"options": ["", "child", "teen", "adult"]}})
            elif validator is bool:
                result[marker] = bool
            else:
                result[marker] = str
        result[vol.Optional("reason", default="")] = str
        return vol.Schema(result)

    async def async_step_edit(self, user_input=None):
        await self._authorise()
        errors = {}
        if user_input is not None:
            try:
                values = deepcopy(user_input)
                for key in ("group_id", "rule_id", "probe_id"):
                    if values.get(key) == "":
                        values.pop(key)
                if "duration_minutes" in values:
                    values["duration_minutes"] = int(values["duration_minutes"])
                if "freshness_hours" in values:
                    values["freshness_hours"] = int(values["freshness_hours"])
                if "days" in values:
                    values["days"] = [int(d) for d in values["days"]]
                if self.action == "apply_import":
                    values["expected_revision"] = self.revision
                # Rule replacement is complete; window edit starts from current rule windows.
                if self.action == "upsert_rule":
                    existing = self.engine.state.rules.get(values.get("rule_id"))
                    values["windows"] = (
                        deepcopy([asdict(w) for w in existing.windows]) if existing else []
                    )
                self.draft = SCHEMAS[self.action](values)
                if self.action == "upsert_rule":
                    if self.draft["kind"] != "internet":
                        return await self.async_step_targets()
                    return await self.async_step_windows()
                return await self.async_step_preview()
            except FamilyError, vol.Invalid, TypeError, ValueError:
                errors["base"] = "invalid_input"
        catalogue = ""
        return self.async_show_form(
            step_id="edit",
            data_schema=self._schema(),
            errors=errors,
            description_placeholders={
                "action": self.action.replace("_", " "),
                "catalogue": catalogue,
            },
        )

    async def async_step_targets(self, user_input=None):
        await self._authorise()
        kind = self.draft["kind"]
        if user_input is not None:
            self.draft["targets"] = (
                [int(t) for t in user_input["targets"]]
                if kind in ("category", "application")
                else user_input["targets"]
            )
            return await self.async_step_windows()
        catalogue = (
            self.engine.gateway.categories
            if kind == "category"
            else self.engine.gateway.applications
            if kind == "application"
            else []
        )
        return self.async_show_form(
            step_id="targets",
            data_schema=vol.Schema(
                {
                    vol.Required("targets"): selector(
                        {
                            "select": {
                                "options": [
                                    {"value": str(c["id"]), "label": c["name"]} for c in catalogue
                                ],
                                "multiple": True,
                                "custom_value": kind == "domain",
                                "mode": "dropdown",
                            }
                        }
                    )
                }
            ),
        )

    async def async_step_windows(self, user_input=None):
        await self._authorise()
        if user_input is not None:
            if user_input["operation"] == "add":
                return await self.async_step_window()
            if user_input["operation"] == "clear":
                self.draft["windows"] = []
            if user_input["operation"] == "remove":
                return await self.async_step_remove_window()
            if user_input["operation"] == "save":
                return await self.async_step_preview()
        return self.async_show_form(
            step_id="windows",
            data_schema=vol.Schema(
                {
                    vol.Required("operation"): selector(
                        {"select": {"options": ["add", "remove", "clear", "save"]}}
                    )
                }
            ),
            description_placeholders={"windows": str(self.draft["windows"])},
        )

    async def async_step_window(self, user_input=None):
        await self._authorise()
        errors = {}
        if user_input is not None:
            try:
                user_input["days"] = [int(d) for d in user_input["days"]]
                window = Window(uid(), **user_input)
                window.validate()
                self.draft["windows"].append(asdict(window))
                return await self.async_step_windows()
            except FamilyError, TypeError:
                errors["base"] = "invalid_input"
        return self.async_show_form(
            step_id="window",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): str,
                    vol.Required("days"): selector(
                        {"select": {"options": weekday_options(), "multiple": True}}
                    ),
                    vol.Required("start", default="20:00"): str,
                    vol.Required("end", default="07:00"): str,
                    vol.Required("overnight", default=True): bool,
                    vol.Required("all_day", default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_remove_window(self, user_input=None):
        await self._authorise()
        if user_input is not None:
            self.draft["windows"] = [
                w for w in self.draft["windows"] if w["id"] != user_input["window_id"]
            ]
            return await self.async_step_windows()
        return self.async_show_form(
            step_id="remove_window",
            data_schema=vol.Schema(
                {
                    vol.Required("window_id"): selector(
                        {
                            "select": {
                                "options": [
                                    {"value": w["id"], "label": w["name"]}
                                    for w in self.draft["windows"]
                                ]
                            }
                        }
                    )
                }
            ),
        )

    async def async_step_preview(self, user_input=None):
        await self._authorise()
        errors = {}
        if user_input is not None:
            if not user_input["confirm"]:
                return self.async_abort(reason="cancelled")
            try:
                with self.coordinator.operation():
                    if self.action == "cleanup_owned" and self.draft.get("confirm"):
                        self.draft["confirm"] = True
                    result = await self.engine.command(
                        self.action,
                        {
                            **self.draft,
                            "expected_revision": self.revision,
                            "expected_dns_revision": self.dns_revision,
                        },
                        self.actor,
                        administrator=True,
                    )
                    self.coordinator.schedule_deadline()
                    await self.coordinator.storage.history.observe_changes(
                        self.engine.state.changes
                    )
                    if self.action == "check_dns":
                        started = self.coordinator.start_dns(
                            self.draft.get("probe_id"), self.draft.get("group_id")
                        )
                        result = {"change": result, "queued": started}
                    elif self.action in DNS_ACTIONS:
                        self.coordinator.async_set_updated_data(self.engine.state)
                    elif self.action not in (
                        "export_configuration",
                        "preview_import",
                        "cleanup_owned",
                        "view_activity",
                    ):
                        await self.coordinator.async_request_refresh()
                    self.result = result
                    return await self.async_step_result()
            except FamilyError, ValueError:
                errors["base"] = "change_failed"
        summary = {
            "action": self.action,
            "revision": self.revision,
            "managed_networks": self.engine.state.networks,
            "input": self.draft,
            "quarantine_enabled": self.engine.state.quarantine,
            "owned_policy_count": len(self.engine.state.owned),
            "notice": "Review affected groups/devices. Saved intent requires gateway readback; temporary exception expiry requires HA.",
        }
        return self.async_show_form(
            step_id="preview",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
            errors=errors,
            description_placeholders={"preview": str(summary)},
        )

    async def async_step_result(self, user_input=None):
        await self._authorise()
        if user_input is not None:
            return self.async_create_entry(title="", data={})
        import json

        return self.async_show_form(
            step_id="result",
            data_schema=vol.Schema({}),
            description_placeholders={"result": json.dumps(self.result, indent=2)},
        )
