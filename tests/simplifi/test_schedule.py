from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.simplifi.models import (
    CapabilityError,
    Rule,
    SimpliFiError,
    State,
    Window,
)
from custom_components.simplifi.planner import next_change, plan
from custom_components.simplifi.schedule import (
    active_end,
    gateway_schedules,
    occurrences,
    rule_active,
    wall_instant,
)

from .conftest import command


def test_sunday_overnight_end_is_exclusive():
    window = Window("w", "Sunday", [6], "20:00", "07:00", overnight=True)
    start = datetime(2026, 10, 11, 19, 0, tzinfo=UTC)
    end = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
    assert list(occurrences(window, start, end, "Europe/London")) == [(start, end)]
    assert list(occurrences(window, end, end + timedelta(minutes=1), "Europe/London")) == []
    assert gateway_schedules(window)[1]["repeatOnDays"] == ["MONDAY"]


@pytest.mark.parametrize("day,hours", [("2026-03-29", 23), ("2026-10-25", 25), ("2028-02-29", 24)])
def test_all_day_dst_and_leap_day(day, hours):
    start = datetime.fromisoformat(day).replace(tzinfo=UTC) - timedelta(hours=1)
    window = Window("w", "All day", list(range(7)), all_day=True)
    values = list(occurrences(window, start, start + timedelta(days=2), "Europe/London"))
    chosen = next((a, b) for a, b in values if b - a == timedelta(hours=hours))
    assert chosen[1] > chosen[0]


def test_fall_window_stops_when_clock_returns_before_its_start():
    window = Window("w", "Window", [6], "01:30", "02:30")
    start = datetime(2026, 10, 25, tzinfo=UTC)
    assert list(occurrences(window, start, start + timedelta(days=1), "Europe/London")) == [
        (start + timedelta(minutes=30), start + timedelta(hours=1)),
        (start + timedelta(hours=1, minutes=30), start + timedelta(hours=2, minutes=30)),
    ]


def test_spring_window_keeps_the_existing_minutes_after_the_gap():
    window = Window("w", "Window", [6], "01:30", "02:30")
    start = datetime(2026, 3, 29, tzinfo=UTC)
    assert list(occurrences(window, start, start + timedelta(days=1), "Europe/London")) == [
        (start + timedelta(hours=1), start + timedelta(hours=1, minutes=30))
    ]


@pytest.mark.parametrize(
    "window",
    [
        Window("w", "w", [], "20:00", "21:00"),
        Window("w", "w", [7], "20:00", "21:00"),
        Window("w", "w", [0], "20:00", "07:00"),
        Window("w", "w", [0], "20:00", "20:00"),
        Window("w", "w", [0], "24:00", "20:00"),
    ],
)
def test_ambiguous_windows_rejected(window):
    with pytest.raises(SimpliFiError):
        window.validate()


@pytest.mark.parametrize(
    "timezone,day,start_time,end_time,expected",
    [
        (
            "Europe/London",
            "2026-10-25",
            "01:10",
            "01:20",
            [("2026-10-25T00:10", "2026-10-25T00:20"), ("2026-10-25T01:10", "2026-10-25T01:20")],
        ),
        ("Europe/London", "2026-03-29", "01:10", "01:20", []),
        (
            "Europe/London",
            "2026-03-29",
            "00:30",
            "01:30",
            [("2026-03-29T00:30", "2026-03-29T01:00")],
        ),
        (
            "Australia/Lord_Howe",
            "2026-04-05",
            "01:40",
            "01:50",
            [("2026-04-04T14:40", "2026-04-04T14:50"), ("2026-04-04T15:10", "2026-04-04T15:20")],
        ),
        (
            "Australia/Lord_Howe",
            "2026-10-04",
            "02:10",
            "02:40",
            [("2026-10-03T15:30", "2026-10-03T15:40")],
        ),
        (
            "America/New_York",
            "2026-11-01",
            "01:10",
            "01:20",
            [("2026-11-01T05:10", "2026-11-01T05:20"), ("2026-11-01T06:10", "2026-11-01T06:20")],
        ),
        ("Pacific/Apia", "2011-12-30", "12:00", "13:00", []),
    ],
)
def test_wall_clock_vectors(timezone, day, start_time, end_time, expected):
    local_day = datetime.fromisoformat(day)
    window = Window("w", "Window", [local_day.weekday()], start_time, end_time)
    start = local_day.replace(tzinfo=UTC) - timedelta(days=1)
    actual = list(occurrences(window, start, start + timedelta(days=3), timezone))
    assert actual == [
        (
            datetime.fromisoformat(a).replace(tzinfo=UTC),
            datetime.fromisoformat(b).replace(tzinfo=UTC),
        )
        for a, b in expected
    ]


def test_long_overnight_window_near_negative_utc_offset_limit():
    start = datetime(2026, 10, 12, tzinfo=UTC)
    window = Window("w", "Nearly all day", [0], "23:59", "23:58", overnight=True)
    assert list(occurrences(window, start, start + timedelta(days=4), "Etc/GMT+12")) == [
        (
            start + timedelta(days=1, hours=11, minutes=59),
            start + timedelta(days=2, hours=11, minutes=58),
        )
    ]


def test_query_with_repeated_local_end_before_start_uses_elapsed_time():
    zone = ZoneInfo("Europe/London")
    start = datetime(2026, 10, 25, 1, 15, tzinfo=zone, fold=0)
    end = datetime(2026, 10, 25, 1, 12, tzinfo=zone, fold=1)
    window = Window("w", "Repeated", [6], "01:10", "01:20")
    assert len(list(occurrences(window, start, end, "Europe/London"))) == 2


@pytest.mark.parametrize(
    "timezone,day",
    [
        ("Europe/London", "2026-03-29"),
        ("Europe/London", "2026-10-25"),
        ("Australia/Lord_Howe", "2026-04-05"),
        ("Australia/Lord_Howe", "2026-10-04"),
    ],
)
def test_interval_projection_matches_independent_wall_clock_predicate(timezone, day):
    zone = ZoneInfo(timezone)
    base = datetime.fromisoformat(day).replace(tzinfo=UTC) - timedelta(days=1)
    windows = [
        Window("w", "Fold", [6], "01:10", "01:20"),
        Window("w", "Gap", [6], "01:30", "02:30"),
        Window("w", "Overnight", [5], "23:30", "01:15", overnight=True),
        Window("w", "All day", [6], all_day=True),
    ]
    for window in windows:
        spans = list(occurrences(window, base, base + timedelta(days=3), timezone))
        for minute in range(3 * 24 * 60):
            at = base + timedelta(minutes=minute, seconds=17)
            local = at.astimezone(zone)
            clock = local.strftime("%H:%M")
            if window.all_day:
                expected = local.weekday() in window.days
            elif window.overnight:
                expected = (
                    local.weekday() in window.days
                    and clock >= window.start
                    or (local.weekday() - 1) % 7 in window.days
                    and clock < window.end
                )
            else:
                expected = local.weekday() in window.days and window.start <= clock < window.end
            assert any(a <= at < b for a, b in spans) == expected, (timezone, window, at)


async def test_status_next_change_allowance_and_restart_follow_each_fold(household):
    engine, gateway, now, save = household
    base = datetime(2026, 10, 25, tzinfo=UTC)
    rule = Rule(
        "r",
        "Short restriction",
        "internet",
        ["child"],
        windows=[Window("w", "Sunday", [6], "01:10", "01:20")],
    )
    engine.state.rules[rule.id] = rule
    now[0] = base + timedelta(minutes=15)
    assert engine.status("child")["state"] == "scheduled_block"
    assert active_end(rule, now[0], engine.state.timezone) == base + timedelta(minutes=20)
    assert next_change(engine.state, "child", now[0]) == base + timedelta(minutes=20)
    await command(engine, "allow_internet", group_id="child")
    allowance = next(iter(engine.state.exceptions.values()))
    assert allowance.expires_at == (base + timedelta(minutes=20)).isoformat()
    engine.state = State.from_dict(save[-1])
    now[0] = base + timedelta(minutes=20)
    assert engine.status("child")["state"] == "available"
    assert not rule_active(rule, now[0], engine.state.timezone)
    assert next_change(engine.state, "child", now[0]) == base + timedelta(hours=1, minutes=10)
    now[0] = base + timedelta(hours=1, minutes=15)
    assert engine.status("child")["state"] == "scheduled_block"
    assert active_end(rule, now[0], engine.state.timezone) == base + timedelta(hours=1, minutes=20)
    # Projection does not turn recurrence into clock-driven policy enable writes.
    bodies = [
        plan(engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, at)
        for at in [
            base,
            base + timedelta(minutes=15),
            base + timedelta(hours=1, minutes=15),
            base + timedelta(hours=2),
        ]
    ]
    # An expired stored allowance at 00:20 is ignored after its deadline.
    assert bodies[2] == bodies[3]
    assert all("schedule" in body for body in bodies[3].values())
    engine.state.gateway_timezone_confirmed = False
    with pytest.raises(CapabilityError, match="timezone/schedule parity"):
        plan(engine.state, gateway.networks, gateway.external_zone, gateway.catalogues, now[0])


def test_once_daily_jobs_keep_their_distinct_gap_and_fold_semantics():
    zone = ZoneInfo("Europe/London")
    assert wall_instant(datetime(2026, 3, 29).date(), "01:30", zone, end=False) == datetime(
        2026, 3, 29, 1, 30, tzinfo=UTC
    )
    assert wall_instant(datetime(2026, 10, 25).date(), "01:30", zone, end=False) == datetime(
        2026, 10, 25, 0, 30, tzinfo=UTC
    )
