"""Half-open wall-clock windows, converted to UTC for unambiguous comparisons."""

from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from .models import Rule, SimpliFiError, Window


def wall_instant(day: date, value: str, zone: ZoneInfo, *, end: bool) -> datetime:
    """Resolve a once-per-day job: earliest start, latest end; shift gaps forward.

    Recurring access windows instead include each existing wall-clock occurrence.
    """
    naive = datetime.combine(day, time.fromisoformat(value))
    choices = []
    for fold in (0, 1):
        utc = naive.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == naive:
            choices.append(utc)
    if choices:
        return max(choices) if end else min(choices)
    # Preserve minutes through a spring-forward gap; never create an earlier instant.
    options = [naive.replace(tzinfo=zone, fold=f).astimezone(UTC) for f in (0, 1)]
    return min(u for u in options if u.astimezone(zone).replace(tzinfo=None) > naive)


@lru_cache(maxsize=512)
def _offset_segments(day: date, timezone: str) -> tuple[tuple[datetime, datetime, timedelta], ...]:
    """UTC offset regimes around a local day, including folds and skipped dates.

    Probe hourly to bracket IANA offset transitions, then find their exact second.
    The bounded cache is shared by every window/status/calendar on that date.
    A one-day margin on each side covers all datetime-supported UTC offsets.
    """
    zone = ZoneInfo(timezone)
    left = datetime.combine(day, time(), UTC) - timedelta(days=1)
    stop = left + timedelta(days=4)
    offset = left.astimezone(zone).utcoffset()
    assert offset is not None
    segment = left
    result = []
    while left < stop:
        right = min(left + timedelta(hours=1), stop)
        after = right.astimezone(zone).utcoffset()
        assert after is not None
        if after != offset:
            low, high = left, right
            while high - low > timedelta(seconds=1):
                middle = low + timedelta(seconds=int((high - low).total_seconds()) // 2)
                if middle.astimezone(zone).utcoffset() == offset:
                    low = middle
                else:
                    high = middle
            result.append((segment, high, offset))
            segment, offset = high, after
        left = right
    result.append((segment, stop, offset))
    return tuple(result)


@lru_cache(maxsize=2048)
def _wall_intervals(day: date, start: str, end: str, next_day: bool, timezone: str):
    """Intersect a wall-time interval with each actual UTC offset regime."""
    wall_start = datetime.combine(day, time.fromisoformat(start), UTC)
    wall_end = datetime.combine(day + timedelta(days=int(next_day)), time.fromisoformat(end), UTC)
    result: list[tuple[datetime, datetime]] = []
    for a, b, offset in _offset_segments(day, timezone):
        first, last = max(a, wall_start - offset), min(b, wall_end - offset)
        if first >= last:
            continue
        if result and result[-1][1] == first:
            result[-1] = (result[-1][0], last)
        else:
            result.append((first, last))
    return tuple(result)


def occurrences(window: Window, start: datetime, end: datetime, timezone: str):
    window.validate()
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if end <= start:
        return
    zone = ZoneInfo(timezone)
    day = start.astimezone(zone).date() - timedelta(days=1)
    final = end.astimezone(zone).date()
    while day <= final:
        if day.weekday() in window.days:
            for a, b in _wall_intervals(
                day,
                "00:00" if window.all_day else window.start,
                "00:00" if window.all_day else window.end,
                window.overnight or window.all_day,
                timezone,
            ):
                if b > start and a < end:
                    yield a, b
        day += timedelta(days=1)


def rule_active(rule: Rule, now: datetime, timezone: str) -> bool:
    if not rule.enabled:
        return False
    return not rule.windows or any(
        a <= now < b
        for w in rule.windows
        for a, b in occurrences(w, now, now + timedelta(seconds=1), timezone)
    )


def active_end(rule: Rule, now: datetime, timezone: str) -> datetime:
    ends = [
        b
        for w in rule.windows
        for a, b in occurrences(w, now, now + timedelta(days=8), timezone)
        if a <= now < b
    ]
    if not ends:
        raise SimpliFiError("No active scheduled window has an end; choose a deadline")
    return max(ends)


def gateway_schedules(window: Window) -> list[dict]:
    """Native recurrence; split midnight crossing by its start weekdays.

    Midnight stopTime=00:00 interpretation requires a live scheduler test.
    """
    names = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

    def make(days, start=None, stop=None):
        body: dict = {"mode": "EVERY_WEEK", "repeatOnDays": [names[d] for d in sorted(days)]}
        if start is not None:
            body["timeFilter"] = {"startTime": start, "stopTime": stop}
        return body

    if window.all_day:
        return [make(window.days)]
    if not window.overnight:
        return [make(window.days, window.start, window.end)]
    parts = [make(window.days, window.start, "00:00")]
    if window.end != "00:00":
        parts.append(make([(d + 1) % 7 for d in window.days], "00:00", window.end))
    return parts
