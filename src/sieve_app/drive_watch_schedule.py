"""Calculate the next Drive folder scan in the recruiter's time zone."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

SCHEDULES = ("instant", "daily", "weekends")


def next_scan_at(schedule: str, zone_name: str, now: datetime) -> datetime:
    if schedule not in SCHEDULES:
        raise ValueError("Unsupported notification schedule")
    if schedule == "instant":
        return now + timedelta(seconds=2)

    zone = ZoneInfo(zone_name)
    local_now = now.astimezone(zone)
    for offset in range(8):
        day = local_now.date() + timedelta(days=offset)
        if schedule == "weekends" and day.weekday() < 5:
            continue
        candidate = datetime.combine(day, time(18, 0), tzinfo=zone).astimezone(UTC)
        if candidate > now:
            return candidate
    raise RuntimeError("Could not calculate next Drive scan")
