"""
Shared fixtures: an in-memory stand-in for the Postgres database, loaded with the same
rows as database/seed.sql, so the revenue services can be tested without Docker.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"

PROPERTIES = [
    ("prop-001", TENANT_A, "Europe/Paris"),
    ("prop-001", TENANT_B, "America/New_York"),
    ("prop-002", TENANT_A, "Europe/Paris"),
    ("prop-003", TENANT_A, "Europe/Paris"),
    ("prop-004", TENANT_B, "America/New_York"),
    ("prop-005", TENANT_B, "America/New_York"),
]

# (property_id, tenant_id, check_in UTC, total_amount) as in database/seed.sql
RESERVATIONS = [
    ("prop-001", TENANT_A, "2024-02-29T23:30:00+00:00", "1250.000"),
    ("prop-001", TENANT_A, "2024-03-15T10:00:00+00:00", "333.333"),
    ("prop-001", TENANT_A, "2024-03-16T10:00:00+00:00", "333.333"),
    ("prop-001", TENANT_A, "2024-03-17T10:00:00+00:00", "333.334"),
    ("prop-002", TENANT_A, "2024-03-05T14:00:00+00:00", "1250.00"),
    ("prop-002", TENANT_A, "2024-03-12T16:00:00+00:00", "1475.50"),
    ("prop-002", TENANT_A, "2024-03-20T15:00:00+00:00", "1199.25"),
    ("prop-002", TENANT_A, "2024-03-25T18:00:00+00:00", "1050.75"),
    ("prop-003", TENANT_A, "2024-03-02T15:00:00+00:00", "2850.00"),
    ("prop-003", TENANT_A, "2024-03-18T16:00:00+00:00", "3250.50"),
    ("prop-004", TENANT_B, "2024-03-08T18:00:00+00:00", "420.00"),
    ("prop-004", TENANT_B, "2024-03-14T17:00:00+00:00", "560.75"),
    ("prop-004", TENANT_B, "2024-03-22T16:00:00+00:00", "480.25"),
    ("prop-004", TENANT_B, "2024-03-28T19:00:00+00:00", "315.50"),
    ("prop-005", TENANT_B, "2024-03-06T19:00:00+00:00", "920.00"),
    ("prop-005", TENANT_B, "2024-03-15T18:00:00+00:00", "1080.40"),
    ("prop-005", TENANT_B, "2024-03-24T20:00:00+00:00", "1255.60"),
]


@dataclass
class FakeDatabase:
    properties: list
    reservations: list

    def __post_init__(self):
        self.executed = []  # (sql, params) of every query, for assertions

    def run(self, sql: str, params: dict):
        self.executed.append((sql, params))
        if "FROM properties" in sql:
            for pid, tid, tz in self.properties:
                if pid == params["property_id"] and tid == params["tenant_id"]:
                    return SimpleNamespace(timezone=tz)
            return None
        if "FROM reservations" in sql:
            # Mirror the SQL filters; refuse queries that are not tenant-scoped.
            assert "tenant_id = :tenant_id" in sql, "reservation query is not scoped by tenant"
            rows = [
                Decimal(amount)
                for pid, tid, check_in, amount in self.reservations
                if pid == params["property_id"]
                and tid == params["tenant_id"]
                and ("start_date" not in params or params["start_date"] <= datetime.fromisoformat(check_in))
                and ("end_date" not in params or datetime.fromisoformat(check_in) < params["end_date"])
            ]
            return SimpleNamespace(total_revenue=sum(rows, Decimal("0")), reservation_count=len(rows))
        raise AssertionError(f"Unexpected query: {sql}")


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def one(self):
        assert self._row is not None, "query returned no rows"
        return self._row


class FakeSession:
    def __init__(self, db: FakeDatabase):
        self._db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query, params):
        return FakeResult(self._db.run(str(query), params))


class FakePool:
    def __init__(self, db: FakeDatabase):
        self._db = db
        self.session_factory = object()

    async def initialize(self):
        pass

    def get_session(self):
        return FakeSession(self._db)


@pytest.fixture
def fake_db(monkeypatch):
    """Route the services' database pool to an in-memory copy of the seed data."""
    from app.core import database_pool

    db = FakeDatabase(list(PROPERTIES), list(RESERVATIONS))
    monkeypatch.setattr(database_pool, "db_pool", FakePool(db))
    return db


@pytest.fixture
def fake_redis(monkeypatch):
    import fakeredis
    from app.services import cache

    client = fakeredis.FakeAsyncRedis()
    monkeypatch.setattr(cache, "redis_client", client)
    return client
