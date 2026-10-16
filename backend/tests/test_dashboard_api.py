from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import dashboard, login
from app.core.auth import authenticate_request

from .conftest import TENANT_A, TENANT_B


def make_client(user=None):
    app = FastAPI()
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(login.router, prefix="/api/v1")
    if user is not None:
        app.dependency_overrides[authenticate_request] = lambda: user
    return TestClient(app)


@pytest.fixture
def tenant_a_client(fake_db, fake_redis):
    return make_client(SimpleNamespace(tenant_id=TENANT_A))


def test_returns_tenant_scoped_total(tenant_a_client):
    body = tenant_a_client.get("/api/v1/dashboard/summary", params={"property_id": "prop-002"}).json()
    assert body == {
        "property_id": "prop-002",
        "total_revenue": 4975.5,
        "currency": "USD",
        "reservations_count": 4,
    }


def test_monthly_summary_uses_property_timezone(tenant_a_client):
    body = tenant_a_client.get(
        "/api/v1/dashboard/summary", params={"property_id": "prop-001", "month": 3, "year": 2024}
    ).json()
    assert body["total_revenue"] == 2250.0
    assert body["reservations_count"] == 4
    assert (body["month"], body["year"]) == (3, 2024)


def test_total_is_rounded_to_cents(fake_db, fake_redis):
    fake_db.reservations.append(("prop-002", TENANT_A, "2024-03-29T10:00:00+00:00", "0.005"))
    client = make_client(SimpleNamespace(tenant_id=TENANT_A))
    body = client.get("/api/v1/dashboard/summary", params={"property_id": "prop-002"}).json()
    assert body["total_revenue"] == 4975.51


def test_user_without_tenant_is_rejected(fake_db, fake_redis):
    client = make_client(SimpleNamespace(tenant_id=None))
    response = client.get("/api/v1/dashboard/summary", params={"property_id": "prop-001"})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "params",
    [
        {"property_id": "prop-001", "month": 3},
        {"property_id": "prop-001", "year": 2024},
        {"property_id": "prop-001", "month": 13, "year": 2024},
    ],
)
def test_invalid_period_is_rejected(tenant_a_client, params):
    assert tenant_a_client.get("/api/v1/dashboard/summary", params=params).status_code == 422


def test_unknown_property_for_month_is_404(fake_db, fake_redis):
    client = make_client(SimpleNamespace(tenant_id=TENANT_B))
    response = client.get(
        "/api/v1/dashboard/summary", params={"property_id": "prop-002", "month": 3, "year": 2024}
    )
    assert response.status_code == 404


def test_database_failure_is_503_not_fake_data(monkeypatch, fake_redis):
    async def boom(*args, **kwargs):
        raise RuntimeError("Database pool not available")

    monkeypatch.setattr("app.services.reservations.calculate_total_revenue", boom)
    client = make_client(SimpleNamespace(tenant_id=TENANT_A))
    response = client.get("/api/v1/dashboard/summary", params={"property_id": "prop-001"})
    assert response.status_code == 503


def test_real_logins_see_only_their_own_prop_001(fake_db, fake_redis):
    """End to end through login + JWT auth: the two clients share property id prop-001."""
    client = make_client()

    def summary_for(email, password):
        token = client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        return client.get("/api/v1/dashboard/summary", params={"property_id": "prop-001"}, headers=headers).json()

    sunset = summary_for("sunset@propertyflow.com", "client_a_2024")
    ocean = summary_for("ocean@propertyflow.com", "client_b_2024")
    sunset_again = summary_for("sunset@propertyflow.com", "client_a_2024")

    assert sunset["total_revenue"] == 2250.0
    assert ocean["total_revenue"] == 0.0
    assert sunset_again == sunset
