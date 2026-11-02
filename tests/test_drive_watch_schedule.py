"""Notification schedules honor the recruiter's calendar and time zone."""

from datetime import UTC, datetime

import pytest

from sieve_app.drive_watch_schedule import next_scan_at


@pytest.mark.parametrize(("schedule", "expected"), [
    ("instant", datetime(2026, 10, 23, 12, 30, 2, tzinfo=UTC)),
    ("daily", datetime(2026, 10, 24, 12, 30, tzinfo=UTC)),
    ("weekends", datetime(2026, 10, 24, 12, 30, tzinfo=UTC)),
])
def test_next_scan_from_friday_evening_in_india(schedule, expected):
    now = datetime(2026, 10, 23, 12, 30, tzinfo=UTC)
    assert next_scan_at(schedule, "Asia/Kolkata", now) == expected


def test_same_day_before_cutoff_and_weekend_sunday():
    now = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)
    assert next_scan_at("weekends", "Asia/Kolkata", now) == datetime(
        2026, 10, 24, 12, 30, tzinfo=UTC,
    )
    later = datetime(2026, 10, 24, 14, 0, tzinfo=UTC)
    assert next_scan_at("weekends", "Asia/Kolkata", later) == datetime(
        2026, 10, 25, 12, 30, tzinfo=UTC,
    )


def test_weekdays_is_no_longer_supported():
    with pytest.raises(ValueError, match="Unsupported notification schedule"):
        next_scan_at("weekdays", "Asia/Kolkata", datetime.now(UTC))
