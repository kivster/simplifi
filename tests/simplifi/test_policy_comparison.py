"""UniFi Network 11 readback keys must not look like external policy edits."""

from copy import deepcopy

import pytest

from custom_components.simplifi.planner import (
    format_policy_mismatch,
    policy_difference,
    policy_fingerprint,
    policy_matches,
    policy_mismatch_fields,
)


def pre_11_policy():
    """Stored body shape from before Network 11, using fictional addresses."""
    return {
        "id": "11111111-1111-4111-8111-111111111111",
        "enabled": True,
        "name": "SimpliFi rule:example",
        "description": "simplifi operation recorded-id",
        "index": 4,
        "action": {"type": "BLOCK"},
        "source": {
            "zoneId": "home",
            "trafficFilter": {
                "type": "NETWORK",
                "networkFilter": {"networkIds": ["lan"], "matchOpposite": False},
                "macAddressFilter": "02:00:00:00:00:01",
            },
        },
        "destination": {"zoneId": "wan"},
        "ipProtocolScope": {"ipVersion": "IPV4_AND_IPV6"},
        "loggingEnabled": False,
        "schedule": {
            "mode": "EVERY_WEEK",
            "repeatOnDays": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"],
            "timeFilter": {"startTime": "22:00", "stopTime": "07:00"},
        },
        "metadata": {"origin": "USER_DEFINED"},
    }


def live_from(stored, **extra):
    body = deepcopy(stored)
    body.update(extra)
    return body


@pytest.mark.parametrize("report_flow", [False, True])
def test_network_11_report_flow_matches_pre_11_stored_body(report_flow):
    stored = pre_11_policy()
    live = live_from(stored, reportFlowEnabled=report_flow)
    receipt = policy_fingerprint(stored)
    assert policy_fingerprint(live) != receipt
    assert policy_matches(live, stored, receipt)
    assert policy_difference(live, stored) == []
    assert policy_mismatch_fields(live, stored, receipt) == []
    assert stored == pre_11_policy()
    assert live["reportFlowEnabled"] is report_flow


def test_report_flow_value_change_and_stored_only_field_are_not_owned_edits():
    stored = live_from(pre_11_policy(), reportFlowEnabled=False)
    live = live_from(pre_11_policy(), reportFlowEnabled=True)
    assert policy_matches(live, stored, policy_fingerprint(stored))
    downgraded = pre_11_policy()
    assert policy_matches(downgraded, stored, policy_fingerprint(stored))


def test_server_added_non_default_top_level_key_is_ignored():
    stored = pre_11_policy()
    live = live_from(stored, unexpected=[2, 1])
    assert policy_matches(live, stored, policy_fingerprint(stored))
    assert "unexpected" not in policy_difference(live, stored)


@pytest.mark.parametrize(
    "edit,path,hidden",
    [
        (lambda body: body["action"].__setitem__("type", "ALLOW"), "action.type", "ALLOW"),
        (
            lambda body: body["schedule"]["timeFilter"].__setitem__("startTime", "21:00"),
            "schedule.timeFilter.startTime",
            "21:00",
        ),
        (lambda body: body.__setitem__("loggingEnabled", True), "loggingEnabled", "True"),
        (
            lambda body: body["schedule"].__setitem__("repeatOnDays", ["FRIDAY"]),
            "schedule.repeatOnDays",
            "FRIDAY",
        ),
        (
            lambda body: body["source"].__setitem__("unexpected", "nested-secret"),
            "source.unexpected",
            "nested-secret",
        ),
    ],
)
def test_owned_field_edits_are_still_flagged(edit, path, hidden):
    stored = pre_11_policy()
    live = live_from(stored, reportFlowEnabled=True)
    edit(live)
    receipt = policy_fingerprint(stored)
    assert not policy_matches(live, stored, receipt)
    assert policy_difference(live, stored) == [path]
    detail = format_policy_mismatch(live, stored, receipt)
    assert detail == f"differing fields: {path}"
    assert hidden not in detail and "reportFlowEnabled" not in detail
    assert "02:00:00:00:00:01" not in detail


def test_weekday_order_still_matches_and_wrong_receipt_names_the_receipt():
    stored = pre_11_policy()
    live = deepcopy(stored)
    live["schedule"]["repeatOnDays"].reverse()
    receipt = policy_fingerprint(stored)
    assert policy_fingerprint(live) != receipt
    assert policy_matches(live, stored, receipt)
    assert policy_difference(live, stored) == []
    assert not policy_matches(live, stored, "wrong receipt")
    assert policy_mismatch_fields(live, stored, "wrong receipt") == ["stored receipt"]
    assert stored["schedule"]["repeatOnDays"] == [
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
    ]


def test_difference_paths_omit_values_and_are_capped():
    stored = pre_11_policy()
    live = deepcopy(stored)
    live["source"]["bad key"] = "secret-value"
    fields = policy_difference(live, stored)
    detail = format_policy_mismatch(live, stored, policy_fingerprint(stored))
    assert fields == ["source.unrecognized"]
    assert "secret-value" not in detail and "bad key" not in detail
    for index in range(20):
        live["source"][f"flag{index}"] = f"secret-{index}"
    fields = policy_difference(live, stored)
    assert fields[-1] == "additional fields" and len(fields) == 13
    detail = format_policy_mismatch(live, stored, policy_fingerprint(stored))
    assert "secret-0" not in detail and "secret-value" not in detail
    assert "source.flag0" in fields
