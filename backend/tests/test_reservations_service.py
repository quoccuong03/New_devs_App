import pytest

from app.core.database_pool import build_async_database_url
from app.services.reservations import (
    PropertyNotFoundError,
    calculate_monthly_revenue,
    calculate_total_revenue,
)

from .conftest import TENANT_A, TENANT_B



class TestTotalRevenue:
    async def test_same_property_id_is_isolated_per_tenant(self, fake_db):
        a = await calculate_total_revenue("prop-001", TENANT_A)
        b = await calculate_total_revenue("prop-001", TENANT_B)
        assert (a["total"], a["count"]) == ("2250.00", 4)
        assert (b["total"], b["count"]) == ("0.00", 0)
        assert a["tenant_id"] == TENANT_A and b["tenant_id"] == TENANT_B

    async def test_every_query_is_tenant_scoped(self, fake_db):
        await calculate_total_revenue("prop-004", TENANT_B)
        for sql, params in fake_db.executed:
            assert "tenant_id = :tenant_id" in sql
            assert params["tenant_id"] == TENANT_B

    @pytest.mark.parametrize(
        "property_id, tenant_id, total, count",
        [
            ("prop-002", TENANT_A, "4975.50", 4),
            ("prop-003", TENANT_A, "6100.50", 2),
            ("prop-004", TENANT_B, "1776.50", 4),
            ("prop-005", TENANT_B, "3256.00", 3),
        ],
    )
    async def test_totals_match_seed_data(self, fake_db, property_id, tenant_id, total, count):
        result = await calculate_total_revenue(property_id, tenant_id)
        assert (result["total"], result["count"]) == (total, count)

    async def test_other_tenants_property_returns_nothing(self, fake_db):
        result = await calculate_total_revenue("prop-002", TENANT_B)
        assert (result["total"], result["count"]) == ("0.00", 0)

    async def test_database_failure_raises_instead_of_returning_fake_numbers(self, monkeypatch):
        from app.core import database_pool

        class BrokenPool:
            session_factory = None

            async def initialize(self):
                pass

        monkeypatch.setattr(database_pool, "db_pool", BrokenPool())
        with pytest.raises(RuntimeError):
            await calculate_total_revenue("prop-001", TENANT_A)


class TestMonthlyRevenue:
    async def test_paris_march_includes_booking_made_late_feb_utc(self, fake_db):
        result = await calculate_monthly_revenue("prop-001", TENANT_A, month=3, year=2024)
        assert (result["total"], result["count"]) == ("2250.00", 4)

    async def test_paris_february_excludes_that_booking(self, fake_db):
        result = await calculate_monthly_revenue("prop-001", TENANT_A, month=2, year=2024)
        assert (result["total"], result["count"]) == ("0.00", 0)

    async def test_uses_property_timezone_for_bounds(self, fake_db):
        await calculate_monthly_revenue("prop-004", TENANT_B, month=3, year=2024)
        _, params = fake_db.executed[-1]
        assert params["start_date"].isoformat() == "2024-03-01T05:00:00+00:00"
        assert params["end_date"].isoformat() == "2024-04-01T04:00:00+00:00"

    async def test_property_of_another_tenant_is_not_found(self, fake_db):
        with pytest.raises(PropertyNotFoundError):
            await calculate_monthly_revenue("prop-002", TENANT_B, month=3, year=2024)


class TestDatabaseUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://postgres:postgres@db:5432/propertyflow",
            "postgres://postgres:postgres@db:5432/propertyflow",
            "postgresql+asyncpg://postgres:postgres@db:5432/propertyflow",
        ],
    )
    def test_uses_asyncpg_driver(self, url):
        assert build_async_database_url(url) == "postgresql+asyncpg://postgres:postgres@db:5432/propertyflow"

    def test_rejects_other_schemes(self):
        with pytest.raises(ValueError):
            build_async_database_url("mysql://x@y/z")
