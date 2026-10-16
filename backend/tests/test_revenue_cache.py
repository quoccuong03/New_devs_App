import pytest

from app.services import cache
from app.services.cache import get_revenue_summary, revenue_cache_key

from .conftest import TENANT_A, TENANT_B



def test_cache_key_contains_tenant_and_period():
    assert revenue_cache_key(TENANT_A, "prop-001") == "revenue:tenant-a:prop-001:all"
    assert revenue_cache_key(TENANT_A, "prop-001", 3, 2024) == "revenue:tenant-a:prop-001:2024-03"
    assert revenue_cache_key(TENANT_A, "prop-001") != revenue_cache_key(TENANT_B, "prop-001")


async def test_cached_value_of_one_tenant_is_never_served_to_another(fake_db, fake_redis):
    first = await get_revenue_summary("prop-001", TENANT_A)
    second = await get_revenue_summary("prop-001", TENANT_B)
    assert first["total"] == "2250.00"
    assert second["total"] == "0.00"
    assert second["tenant_id"] == TENANT_B


async def test_second_request_is_served_from_cache(fake_db, fake_redis):
    await get_revenue_summary("prop-002", TENANT_A)
    queries_after_first = len(fake_db.executed)
    again = await get_revenue_summary("prop-002", TENANT_A)
    assert again["total"] == "4975.50"
    assert len(fake_db.executed) == queries_after_first
    assert await fake_redis.ttl("revenue:tenant-a:prop-002:all") > 0


async def test_monthly_and_all_time_are_cached_separately(fake_db, fake_redis):
    march = await get_revenue_summary("prop-001", TENANT_A, 3, 2024)
    feb = await get_revenue_summary("prop-001", TENANT_A, 2, 2024)
    assert (march["total"], feb["total"]) == ("2250.00", "0.00")


async def test_redis_outage_falls_back_to_database(fake_db, monkeypatch):
    class DownRedis:
        async def get(self, key):
            raise ConnectionError("redis down")

        async def setex(self, key, ttl, value):
            raise ConnectionError("redis down")

    monkeypatch.setattr(cache, "redis_client", DownRedis())
    result = await get_revenue_summary("prop-005", TENANT_B)
    assert result["total"] == "3256.00"
