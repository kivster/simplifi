"""Shared strict schemas for HA actions, native forms and pure-engine callers."""

from typing import Any

import probatio as vol

BASE: dict[Any, Any] = {
    vol.Optional("expected_access_revision"): vol.All(int, vol.Range(min=0)),
    vol.Optional("expected_dns_revision"): vol.All(int, vol.Range(min=0)),
    vol.Optional("expected_revision"): vol.All(int, vol.Range(min=0)),
    vol.Optional("request_id"): vol.All(str, vol.Length(min=1, max=100)),
    vol.Optional("reason", default=""): vol.All(str, vol.Length(max=300)),
}
GROUP: dict[Any, Any] = {vol.Required("group_id"): str}
RULE: dict[Any, Any] = {vol.Required("rule_id"): str, vol.Optional("group_id"): str}
TIME: dict[Any, Any] = {
    vol.Optional("duration_minutes"): vol.All(int, vol.Range(min=1, max=10080)),
    vol.Optional("expires_at"): str,
    vol.Optional("next_window_end"): bool,
    vol.Optional("indefinite"): bool,
}
SPECS: dict[str, dict[Any, Any]] = {
    "preview_setup": {vol.Required("configuration"): dict},
    "apply_setup": {
        vol.Required("configuration"): dict,
        vol.Required("preview_hash"): str,
        vol.Required("expected_revision"): int,
        vol.Required("confirm", default=False): bool,
    },
    "access_status": {},
    "access_users": {},
    "list_access_grants": {},
    "set_access_grant": {
        vol.Required("user_id"): str,
        vol.Required("scope"): vol.In(["read_only", "agent_controls", "watch_rules"]),
        vol.Optional("groups", default=[]): [str],
        vol.Optional("networks", default=[]): [str],
        vol.Optional("all_groups", default=False): bool,
        vol.Optional("expires_at"): str,
        vol.Required("confirm", default=False): bool,
    },
    "revoke_access_grant": {
        vol.Required("user_id"): str,
        vol.Required("confirm", default=False): bool,
    },
    "upsert_group": {
        vol.Optional("group_id"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=100)),
        vol.Optional("kind", default="family"): vol.In(["family", "thing"]),
        vol.Optional("age"): vol.In(["child", "teen", "adult", ""]),
        vol.Optional("person"): str,
        vol.Optional("archived", default=False): bool,
    },
    "delete_group": {**GROUP, vol.Required("confirm", default=False): bool},
    "assign_device": {vol.Required("device_id"): str, vol.Optional("group_id"): str},
    "forget_device": {vol.Required("device_id"): str, vol.Required("confirm", default=False): bool},
    "upsert_rule": {
        vol.Optional("rule_id"): str,
        vol.Required("name"): str,
        vol.Required("kind"): vol.In(["internet", "category", "application", "domain"]),
        vol.Optional("groups", default=[]): [str],
        vol.Optional("networks", default=[]): [str],
        vol.Optional("targets", default=[]): [vol.Any(str, int)],
        vol.Optional("windows", default=[]): [dict],
        vol.Optional("enabled", default=True): bool,
    },
    "delete_rule": {vol.Required("rule_id"): str},
    "set_rule_enabled": {vol.Required("rule_id"): str, vol.Required("enabled"): bool},
    "pause_internet": {**GROUP, **TIME},
    "resume_internet": GROUP,
    "extend_pause": {
        **GROUP,
        vol.Required("duration_minutes"): vol.All(int, vol.Range(min=1, max=10080)),
    },
    "allow_internet": {**GROUP, **TIME},
    "end_allowance": GROUP,
    "unblock_group": {**GROUP, **TIME},
    "end_group_unblock": GROUP,
    "extend_group_unblock": {
        **GROUP,
        vol.Required("duration_minutes"): vol.All(int, vol.Range(min=1, max=10080)),
    },
    "edit_allowance": {vol.Required("exception_id"): str, vol.Required("expires_at"): str},
    "suspend_rule": {**RULE, **TIME},
    "resume_rule": RULE,
    "extend_rule_suspension": {
        **RULE,
        vol.Required("duration_minutes"): vol.All(int, vol.Range(min=1, max=10080)),
    },
    "allow_rule": {**RULE, **TIME},
    "end_rule_allowance": RULE,
    "set_quarantine": {
        vol.Required("enabled"): bool,
        vol.Required("excluded_devices"): [str],
        vol.Required("confirm", default=False): bool,
    },
    "suspend_quarantine": TIME,
    "extend_quarantine_suspension": {
        vol.Required("duration_minutes"): vol.All(int, vol.Range(min=1, max=10080))
    },
    "resume_quarantine": {},
    "set_management": {
        vol.Required("enabled"): bool,
        vol.Optional("expiry_acknowledged", default=False): bool,
        vol.Optional("gateway_timezone_confirmed", default=False): bool,
    },
    "upsert_probe": {
        vol.Optional("probe_id"): str,
        vol.Required("name"): str,
        vol.Required("domains"): [str],
        vol.Optional("resolver", default=""): str,
        vol.Optional("baseline_resolver", default=""): str,
        vol.Optional("category", default="custom"): str,
        vol.Optional("enabled", default=True): bool,
        vol.Optional("group_id"): str,
        vol.Optional("vantage", default="Home Assistant host network"): str,
    },
    "delete_probe": {vol.Required("probe_id"): str},
    "set_probe_schedule": {
        vol.Required("enabled"): bool,
        vol.Required("days"): [int],
        vol.Required("time"): str,
    },
    "restore_probe": {vol.Required("probe_id"): str},
    "set_dns_settings": {
        vol.Required("enabled"): bool,
        vol.Required("household_resolver"): str,
        vol.Required("baseline_resolver"): str,
        vol.Required("group_resolvers"): dict,
        vol.Required("freshness_hours"): vol.All(int, vol.Range(min=1, max=168)),
    },
    "check_dns": {vol.Optional("probe_id"): str, vol.Optional("group_id"): str},
    "sync_now": {},
    "export_configuration": {},
    "preview_import": {
        vol.Required("configuration"): dict,
        vol.Optional("network_mapping", default=dict): dict,
    },
    "apply_import": {
        vol.Optional("network_mapping", default=dict): dict,
        vol.Required("configuration"): dict,
        vol.Required("preview_hash"): str,
        vol.Required("expected_revision"): int,
    },
    "cleanup_owned": {vol.Required("confirm", default=False): bool},
    "dashboard_configuration": {
        vol.Optional("presentation", default="enhanced"): vol.In(["enhanced", "native"]),
    },
    "dashboard_data": {},
    "gateway_health": {vol.Optional("refresh", default=False): bool},
    "dashboard_catalogue": {
        vol.Required("kind"): vol.In(["category", "application"]),
        vol.Optional("query", default=""): vol.All(str, vol.Length(max=100)),
    },
    "view_activity": {},
    "activity_history": {
        vol.Optional("kind", default="changes"): vol.In(["changes", "sync"]),
        vol.Optional("change_id"): vol.All(str, vol.Length(min=1, max=100)),
        vol.Optional("before_id"): str,
        vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=100)),
        vol.Optional("outcome"): str,
    },
    "preview_recovery": {vol.Optional("operation_id"): str},
    "resolve_operation": {
        vol.Required("operation_id"): str,
        vol.Required("preview_hash"): str,
        vol.Required("decision"): vol.In(["attach", "confirm_absent", "confirm_not_applied"]),
        vol.Required("confirm", default=False): bool,
        vol.Optional("request_finished", default=False): bool,
    },
}
DNS_ACTIONS = frozenset(
    {
        "upsert_probe",
        "delete_probe",
        "restore_probe",
        "set_probe_schedule",
        "set_dns_settings",
        "check_dns",
    }
)
UPDATE_ACTIONS = frozenset(
    {
        "update_status",
        "check_updates",
        "preview_update",
        "install_update",
        "set_update_schedule",
        "recover_update",
    }
)
UPDATE_REVISION = {vol.Required("expected_update_revision"): vol.All(int, vol.Range(min=0))}
SPECS.update(
    {
        "update_status": {},
        "check_updates": {},
        "preview_update": {},
        "install_update": {
            **UPDATE_REVISION,
            vol.Required("preview_hash"): str,
            vol.Required("request_id"): vol.All(str, vol.Length(min=1, max=100)),
            vol.Required("confirm", default=False): bool,
        },
        "set_update_schedule": {
            **UPDATE_REVISION,
            vol.Required("enabled"): bool,
            vol.Required("days"): vol.All(
                [vol.All(int, vol.Range(min=0, max=6))], vol.Length(min=1, max=7), vol.Unique()
            ),
            vol.Required("time"): vol.Match(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"),
            vol.Required("confirm", default=False): bool,
        },
        "recover_update": {**UPDATE_REVISION, vol.Required("confirm", default=False): bool},
    }
)
SCHEMAS = {
    name: vol.Schema({**BASE, **spec}, extra=vol.PREVENT_EXTRA) for name, spec in SPECS.items()
}
