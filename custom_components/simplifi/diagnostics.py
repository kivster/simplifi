"""Deliberately compact diagnostics with no credentials or household telemetry."""


async def async_get_config_entry_diagnostics(hass, entry):
    engine = entry.runtime_data.engine
    state = engine.state
    protection = entry.runtime_data.protection.snapshot(engine.clock())
    coexistence = entry.runtime_data.coexistence.snapshot(engine.clock(), state)
    health = entry.runtime_data.gateway_health.snapshot()
    return {
        "simulation": entry.data["simulation"],
        "discovery_readback": getattr(engine.gateway, "discovery_readback", None),
        "inventory_readback": engine.gateway.current_network_reader.snapshot(engine.clock())
        if getattr(engine.gateway, "current_network_reader", None)
        else None,
        "schema": state.schema,
        "desired_revision": state.revision,
        "confirmed_revision": state.confirmed_revision,
        "sync_status": state.sync_status,
        "last_observed": state.last_observed,
        "management_enabled": state.management,
        "capabilities": engine.gateway.capabilities,
        "protection_readback": {
            k: protection[k] for k in ("status", "fresh", "profile_count", "observed_at")
        },
        "policy_readback": {
            k: coexistence[k]
            for k in ("status", "fresh", "policy_count", "observed_at", "ordering")
        },
        "alternate_controls": {
            "status": coexistence["controls"]["status"],
            "count": len(coexistence["controls"]["items"]),
        },
        "counts": {
            "groups": len(state.groups),
            "devices": len(state.devices),
            "rules": len(state.rules),
            "owned_policies": len(state.owned),
        },
        "unresolved_operations": [
            {"action": j["action"], "status": j["status"], "revision": j["revision"]}
            for j in state.journal
            if j["status"] != "verified"
        ],
        "issue": state.issue,
        "controller_requests": health["requests"],
        "device_health": {
            k: health[k]
            for k in (
                "status",
                "read_at",
                "last_attempt_at",
                "returned_devices",
                "total_devices",
                "capped",
            )
        },
    }
