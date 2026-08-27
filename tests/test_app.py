from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from system_registration_service import create_app
from system_registration_service.store import SystemStore


@pytest.fixture
def app() -> Flask:
    application = create_app(SystemStore())
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def register(client: FlaskClient, version: str = "1.2.0") -> dict[str, Any]:
    response = client.post(
        "/systems",
        json={"hostname": "capsule-17", "platform": "linux", "installed_version": version},
    )
    assert response.status_code == 201
    return response.get_json()


def test_register_and_retrieve_system(client: FlaskClient) -> None:
    system = register(client)
    response = client.get(f"/systems/{system['id']}")
    assert response.status_code == 200
    assert response.get_json()["hostname"] == "capsule-17"


def test_patch_required(client: FlaskClient) -> None:
    system = register(client, "1.2.0")
    response = client.get(f"/systems/{system['id']}/patch-status?target_version=1.3.0")
    assert response.status_code == 200
    assert response.get_json()["patch_required"] is True


def test_patch_not_required(client: FlaskClient) -> None:
    system = register(client, "1.3.0")
    response = client.get(f"/systems/{system['id']}/patch-status?target_version=1.3.0")
    assert response.status_code == 200
    assert response.get_json()["patch_required"] is False


def test_dashboard_and_inventory_api(client: FlaskClient) -> None:
    register(client, "1.2.0")
    register(client, "1.3.0")

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert b"System Patch Compliance" in dashboard.data
    assert b"capsule-17" in dashboard.data

    inventory = client.get("/api/systems").get_json()
    assert len(inventory["systems"]) == 2
    assert {system["status"] for system in inventory["systems"]} == {
        "compliant",
        "patch_required",
    }


def test_check_in_updates_installed_version(client: FlaskClient) -> None:
    system = register(client, "1.2.0")
    response = client.post(
        f"/systems/{system['id']}/check-ins",
        json={"installed_version": "1.3.0"},
    )
    assert response.status_code == 200
    assert response.get_json()["installed_version"] == "1.3.0"


def test_patch_request_records_approved_intent(client: FlaskClient) -> None:
    system = register(client, "1.2.0")
    response = client.post(f"/systems/{system['id']}/patch-requests", json={})
    assert response.status_code == 202
    assert response.get_json()["state"] == "queued"
    assert response.get_json()["target_version"] == "1.3.0"


def test_rejects_invalid_registration(client: FlaskClient) -> None:
    response = client.post("/systems", json={"hostname": "", "platform": "linux"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_request"


def test_missing_system_returns_not_found(client: FlaskClient) -> None:
    response = client.get("/systems/not-registered")
    assert response.status_code == 404


@pytest.mark.parametrize("path", ["/health/live", "/health/ready", "/version", "/metrics"])
def test_operational_endpoints(client: FlaskClient, path: str) -> None:
    assert client.get(path).status_code == 200
