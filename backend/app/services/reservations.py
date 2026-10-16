from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional, Tuple
from zoneinfo import ZoneInfo
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

CENTS = Decimal("0.01")


class PropertyNotFoundError(Exception):
    """Raised when a property does not exist for the given tenant."""


def to_cents(value: Any) -> Decimal:
    """Round a monetary amount to cents using half-up rounding (never via float)."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def month_bounds_utc(year: int, month: int, tz_name: str) -> Tuple[datetime, datetime]:
    """
    Return the [start, end) UTC instants of a calendar month as experienced in the property's timezone.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid month: {month}")
    tz = ZoneInfo(tz_name)
    start_local = datetime(year, month, 1, tzinfo=tz)
    end_local = datetime(year + 1, 1, 1, tzinfo=tz) if month == 12 else datetime(year, month + 1, 1, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


async def _get_session_factory():
    from app.core.database_pool import db_pool

    await db_pool.initialize()
    if not db_pool.session_factory:
        raise RuntimeError("Database pool not available")
    return db_pool


async def calculate_monthly_revenue(property_id: str, tenant_id: str, month: int, year: int) -> Dict[str, Any]:
    """
    Calculates revenue for a calendar month in the property's local timezone.
    """
    pool = await _get_session_factory()
    async with pool.get_session() as session:
        prop = (await session.execute(
            text("SELECT timezone FROM properties WHERE id = :property_id AND tenant_id = :tenant_id"),
            {"property_id": property_id, "tenant_id": tenant_id},
        )).fetchone()
        if not prop:
            raise PropertyNotFoundError(property_id)

        start_utc, end_utc = month_bounds_utc(year, month, prop.timezone or "UTC")

        row = (await session.execute(
            text("""
                SELECT
                    COALESCE(SUM(total_amount), 0) AS total_revenue,
                    COUNT(*) AS reservation_count
                FROM reservations
                WHERE property_id = :property_id
                AND tenant_id = :tenant_id
                AND check_in_date >= :start_date
                AND check_in_date < :end_date
            """),
            {"property_id": property_id, "tenant_id": tenant_id, "start_date": start_utc, "end_date": end_utc},
        )).one()

    return {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "total": str(to_cents(row.total_revenue)),
        "currency": "USD",
        "count": row.reservation_count,
        "month": month,
        "year": year,
    }


async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates all-time revenue for a property, scoped to the tenant.
    """
    pool = await _get_session_factory()
    async with pool.get_session() as session:
        row = (await session.execute(
            text("""
                SELECT
                    COALESCE(SUM(total_amount), 0) AS total_revenue,
                    COUNT(*) AS reservation_count
                FROM reservations
                WHERE property_id = :property_id AND tenant_id = :tenant_id
            """),
            {"property_id": property_id, "tenant_id": tenant_id},
        )).one()

    return {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "total": str(to_cents(row.total_revenue)),
        "currency": "USD",
        "count": row.reservation_count,
    }
