"""Native Sections configuration generated from HA registry bindings.

Generation is read-only. Saving/refreshing the dashboard remains a reviewed HA UI/API action.
"""

from homeassistant.helpers import entity_registry as er

from .const import CARD_RESOURCE


def build_native_dashboard(entry_id: str, state, bindings: dict[str, str]) -> dict:
    def tile(key, name=None):
        if key not in bindings:
            return {"type": "markdown", "content": f"Waiting for entity: {name or key}"}
        return {
            "type": "tile",
            "entity": bindings[key],
            "name": name or key,
            "tap_action": {"action": "more-info"},
        }

    def action(name, service, data=None, states=None, entity=None):
        card = {
            "type": "button",
            "name": name,
            "icon": "mdi:gesture-tap-button",
            "show_state": False,
            "tap_action": {
                "action": "perform-action",
                "perform_action": f"family_network.{service}",
                "data": {"entry_id": entry_id, **(data or {})},
                "confirmation": {"text": name + "?"},
            },
        }
        if states and entity:
            card["visibility"] = [{"condition": "state", "entity": entity, "state": states}]
        return card

    def nav(name, path="/config/integrations/integration/family_network"):
        return {
            "type": "button",
            "name": name,
            "icon": "mdi:cog-outline",
            "tap_action": {"action": "navigate", "navigation_path": path},
        }

    def section(name, *cards):
        return {
            "type": "grid",
            "cards": [{"type": "heading", "heading": name, "heading_style": "title"}, *cards],
        }

    def view(name, path, icon, sections):
        return {
            "title": name,
            "path": path,
            "icon": icon,
            "type": "sections",
            "max_columns": 3,
            "sections": sections,
        }

    status = section(
        "SimpliFi",
        tile("connected", "Controller connection"),
        tile("sync", "Gateway sync"),
        tile("unassigned", "Unassigned devices"),
        {
            "type": "markdown",
            "content": "Controls affect integration-managed internet restrictions. Existing network content filters still apply.",
        },
    )
    if "connected" in bindings:
        status["cards"].append(
            {
                "type": "markdown",
                "content": "**Unable to confirm current state.** Last observations may be stale.",
                "visibility": [
                    {"condition": "state", "entity": bindings["connected"], "state": "off"}
                ],
            }
        )
    if "expiry_dependency" in bindings:
        status["cards"].append(
            {
                "type": "markdown",
                "content": "**Temporary exception expiry requires Home Assistant.** During an outage, allowances may continue past their deadlines.",
                "visibility": [
                    {"condition": "state", "entity": bindings["expiry_dependency"], "state": "on"}
                ],
            }
        )
    if state.controller == "simulator":
        status["cards"].insert(
            1,
            {
                "type": "markdown",
                "content": "**SIMULATOR** · Fictional devices and policies. No production connectivity.",
            },
        )
    family = [status]
    if not state.groups:
        family.append(
            section(
                "Start your household",
                {
                    "type": "markdown",
                    "content": "Create a family or Things group in integration options, then assign discovered devices.",
                },
                nav("Manage household"),
            )
        )
    for group in state.groups.values():
        if group.archived:
            continue
        key = f"group:{group.id}:internet"
        entity = bindings.get(key)
        cards = [
            tile(key, "Managed internet"),
            tile(f"group:{group.id}:enforcement", "Confirmation"),
        ]
        if entity:
            # Jinja only in a Markdown card, never in an action payload.
            cards.append(
                {
                    "type": "markdown",
                    "text_only": True,
                    "content": "{{ state_attr('"
                    + entity
                    + "', 'reason') or 'Content restrictions may still apply' }}\n\n{{ state_attr('"
                    + entity
                    + "', 'actor') or '' }} · {{ state_attr('"
                    + entity
                    + "', 'expires_at') or '' }}",
                    "entity_id": [entity],
                }
            )
        cards.extend(
            [
                action(
                    "Pause 30 minutes",
                    "pause_internet",
                    {"group_id": group.id, "duration_minutes": 30},
                    ["available", "allowed"],
                    entity,
                ),
                action(
                    "Resume internet", "resume_internet", {"group_id": group.id}, "paused", entity
                ),
                action(
                    "Add 30 minutes",
                    "extend_pause",
                    {"group_id": group.id, "duration_minutes": 30},
                    "paused",
                    entity,
                ),
                action(
                    "Allow 30 minutes",
                    "allow_internet",
                    {"group_id": group.id, "duration_minutes": 30},
                    "scheduled_block",
                    entity,
                ),
                action(
                    "Return to schedule", "end_allowance", {"group_id": group.id}, "allowed", entity
                ),
                tile(f"group:{group.id}:next", "Next predicted change"),
                tile(f"group:{group.id}:devices", "Assigned devices"),
                nav("Details and options"),
            ]
        )
        family.append(section(group.name, *cards))
    devices = [
        section(
            "Devices",
            tile("unassigned", "Unassigned devices"),
            nav("Assign or reassign devices"),
            {
                "type": "markdown",
                "content": "Names do not prove identity. Randomised MACs appear as new devices. Quarantine blocks after discovery and requires HA to discover new devices.",
            },
        )
    ]
    for group_id in [None, *state.groups]:
        rows = [
            tile(f"device:{d.id}", d.name) for d in state.devices.values() if d.group == group_id
        ]
        if rows:
            devices.append(
                section(state.groups[group_id].name if group_id else "Unassigned", *rows)
            )
    rules = [
        section(
            "Rules",
            nav("Edit rules and windows"),
            {
                "type": "markdown",
                "content": "Switches save rule intent. Check gateway sync for confirmation. Calendar shows projected schedules, including windows that exceptions may lift.",
            },
        )
    ]
    for rule in state.rules.values():
        names = ", ".join(state.groups[g].name for g in rule.groups)
        if rule.networks:
            names = "Whole networks: " + ", ".join(rule.networks)
        rules.append(
            section(
                rule.name,
                tile(f"rule:{rule.id}", "Enabled intent"),
                {"type": "markdown", "content": f"{rule.kind.capitalize()} restriction · {names}"},
                tile("sync", "Confirmation"),
            )
        )
    if "calendar" in bindings:
        rules.append(
            section(
                "Upcoming schedules",
                {
                    "type": "calendar",
                    "entities": [bindings["calendar"]],
                    "initial_view": "listWeek",
                    "grid_options": {"columns": "full", "rows": "auto"},
                },
            )
        )
    filtering = [
        section(
            "Network protection",
            tile("protection", "External filtering"),
            {
                "type": "markdown",
                "content": "Existing content filters, SafeSearch and domain exceptions are read through the matching Home Assistant UniFi integration. See the enhanced Filtering view for each profile. Configuration readback does not test client traffic; an allowance does not remove these filters.",
            },
        ),
        section(
            "Managed restrictions",
            {
                "type": "markdown",
                "content": "Category, application and domain rules apply to selected groups. Policy readback is separate from real traffic enforcement.",
            },
            nav("Manage filtering rules"),
        ),
        section(
            "Observed DNS checks",
            {
                "type": "markdown",
                "content": "Sample observations from Home Assistant's network. They do not prove Family client protection, SafeSearch, VPN blocking or universal category coverage.",
            },
            action("Check DNS now", "check_dns"),
            nav("Edit lists and resolvers"),
        ),
    ]
    for key, probe in state.probes.items():
        filtering.append(section(probe["name"], tile(f"probe:{key}", "Observed result")))
    activity = [
        section(
            "Activity",
            tile("activity", "Last requested change"),
            tile("sync", "Sync status"),
            action("Sync now", "sync_now"),
        ),
        section(
            "Administration",
            nav("Integration options"),
            {
                "type": "markdown",
                "content": "Export/import and reviewed owned-policy cleanup are in integration options. Unloading keeps gateway policies. Review diagnostics and recovery documentation before cleanup.",
            },
        ),
    ]
    return {
        "title": "SimpliFi",
        "views": [
            view("Family", "family", "mdi:account-group", family),
            view("Devices", "devices", "mdi:devices", devices),
            view("Rules", "rules", "mdi:calendar-clock", rules),
            view("Filtering", "filtering", "mdi:shield-search", filtering),
            view("Activity", "activity", "mdi:history", activity),
        ],
    }


def build_dashboard(entry_id: str, state, bindings: dict[str, str]) -> dict:
    """Normal Sections views; dynamic content remains within Lovelace cards."""
    views = []
    for title, mode in (
        ("Family", "family"),
        ("Devices", "devices"),
        ("Rules", "rules"),
        ("Filtering", "filtering"),
        ("Activity", "activity"),
    ):
        cards = []
        if mode == "family":
            cards.append(
                {"type": "custom:family-network-card", "mode": "header", "entry_id": entry_id}
            )
        cards.append({"type": "custom:family-network-card", "mode": mode, "entry_id": entry_id})
        section: dict = {
            "type": "grid",
            "column_span": 2,
            "cards": [{**card, "grid_options": {"columns": "full"}} for card in cards],
        }
        view = {
            "title": title,
            "path": mode,
            "type": "sections",
            "max_columns": 2,
            "sections": [section],
        }
        if mode == "rules" and "calendar" in bindings:
            section["cards"].append(
                {
                    "type": "calendar",
                    "title": "Upcoming restrictions",
                    "entities": [bindings["calendar"]],
                    "initial_view": "listWeek",
                    "grid_options": {"columns": "full"},
                }
            )
        views.append(view)
    return {"title": "SimpliFi", "views": views}


def generate_from_registry(hass, entry, presentation="enhanced"):
    registry = er.async_get(hass)
    prefix = entry.entry_id + ":"
    bindings = {
        entity.unique_id.removeprefix(prefix): entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if entity.unique_id.startswith(prefix)
    }
    return {
        "dashboard": (build_native_dashboard if presentation == "native" else build_dashboard)(
            entry.entry_id, entry.runtime_data.engine.state, bindings
        ),
        "resource": CARD_RESOURCE,
        "bindings": bindings,
        "url_path": "family-network",
        "note": "Preview only. Save through HA dashboard UI/API; do not edit .storage. Regeneration must preserve/review user edits.",
    }
