from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.reservations import month_bounds_utc, to_cents


class TestToCents:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("1000.000", "1000.00"),
            ("2.345", "2.35"),  # half-up, not banker's rounding
            ("2.344", "2.34"),
            ("0.005", "0.01"),
            ("4975.5", "4975.50"),
            (Decimal("333.333") * 3, "1000.00"),
            (0, "0.00"),
            (None, "0.00"),
        ],
    )
    def test_rounds_half_up_to_cents(self, raw, expected):
        assert to_cents(raw) == Decimal(expected)

    def test_does_not_inherit_float_error(self):
        # 0.1 + 0.2 == 0.30000000000000004 as a float; summing Decimals must stay exact
        total = sum([Decimal("0.1"), Decimal("0.2")], Decimal("0"))
        assert to_cents(total) == Decimal("0.30")

    def test_float_of_cents_is_exact_cent_value(self):
        assert float(to_cents("1199.255")) == 1199.26


class TestMonthBoundsUtc:
    def test_paris_march_starts_before_utc_midnight(self):
        start, end = month_bounds_utc(2024, 3, "Europe/Paris")
        assert start == datetime(2024, 2, 29, 23, 0, tzinfo=timezone.utc)  # CET = UTC+1
        assert end == datetime(2024, 3, 31, 22, 0, tzinfo=timezone.utc)  # CEST = UTC+2 after DST

    def test_new_york_march_handles_dst(self):
        start, end = month_bounds_utc(2024, 3, "America/New_York")
        assert start == datetime(2024, 3, 1, 5, 0, tzinfo=timezone.utc)  # EST = UTC-5
        assert end == datetime(2024, 4, 1, 4, 0, tzinfo=timezone.utc)  # EDT = UTC-4

    def test_december_rolls_over_to_next_year(self):
        start, end = month_bounds_utc(2024, 12, "UTC")
        assert start == datetime(2024, 12, 1, tzinfo=timezone.utc)
        assert end == datetime(2025, 1, 1, tzinfo=timezone.utc)

    def test_late_feb_utc_booking_belongs_to_march_in_paris(self):
        check_in = datetime(2024, 2, 29, 23, 30, tzinfo=timezone.utc)  # res-tz-1
        start, end = month_bounds_utc(2024, 3, "Europe/Paris")
        assert start <= check_in < end
        utc_start, _ = month_bounds_utc(2024, 3, "UTC")
        assert check_in < utc_start  # the old naive-UTC logic dropped it from March

    @pytest.mark.parametrize("month", [0, 13])
    def test_rejects_invalid_month(self, month):
        with pytest.raises(ValueError):
            month_bounds_utc(2024, month, "UTC")
