import json
import logging
import redis.asyncio as redis
from typing import Dict, Any, Optional
import os

logger = logging.getLogger(__name__)

# Initialize Redis client (typically configured centrally).
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

CACHE_TTL_SECONDS = 300


def revenue_cache_key(tenant_id: str, property_id: str, month: Optional[int] = None, year: Optional[int] = None) -> str:
    """Cache key scoped by tenant: property IDs are only unique per tenant."""
    period = f"{year:04d}-{month:02d}" if month and year else "all"
    return f"revenue:{tenant_id}:{property_id}:{period}"


async def get_revenue_summary(
    property_id: str, tenant_id: str, month: Optional[int] = None, year: Optional[int] = None
) -> Dict[str, Any]:
    """
    Fetches revenue summary, utilizing caching to improve performance.
    """
    cache_key = revenue_cache_key(tenant_id, property_id, month, year)

    # Try to get from cache; a cache outage must not break the dashboard
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Revenue cache read failed for {cache_key}: {e}")

    # Revenue calculation is delegated to the reservation service.
    from app.services.reservations import calculate_monthly_revenue, calculate_total_revenue

    if month and year:
        result = await calculate_monthly_revenue(property_id, tenant_id, month, year)
    else:
        result = await calculate_total_revenue(property_id, tenant_id)

    try:
        await redis_client.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(result))
    except Exception as e:
        logger.warning(f"Revenue cache write failed for {cache_key}: {e}")

    return result
