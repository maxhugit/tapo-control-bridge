import importlib
import json
import sys
from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def load_app(monkeypatch):
    controller = MagicMock()
    controller.getDayNightMode.return_value = "auto"
    controller.setDayNightMode.return_value = {"error_code": 0}
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv(
        "CAMERAS_JSON",
        json.dumps(
            {
                "cuisine": {
                    "host": "192.0.2.10",
                    "username": "user",
                    "password": "password",
                }
            }
        ),
    )
    monkeypatch.setattr("pytapo.Tapo", lambda *args, **kwargs: controller)
    sys.modules.pop("app.main", None)
    module = importlib.import_module("app.main")
    return module, TestClient(module.app), controller


def test_health(monkeypatch):
    _, client, _ = load_app(monkeypatch)
    assert client.get("/health").json() == {"status": "ok"}


def test_authentication_required(monkeypatch):
    _, client, _ = load_app(monkeypatch)
    response = client.get("/api/v1/cameras/cuisine/night-vision")
    assert response.status_code == 401


def test_get_mode(monkeypatch):
    _, client, controller = load_app(monkeypatch)
    response = client.get(
        "/api/v1/cameras/cuisine/night-vision",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.json() == {"camera": "cuisine", "mode": "auto"}
    controller.getDayNightMode.assert_called_once_with()


def test_set_mode(monkeypatch):
    _, client, controller = load_app(monkeypatch)
    response = client.put(
        "/api/v1/cameras/cuisine/night-vision",
        headers={"Authorization": "Bearer test-token"},
        json={"mode": "on"},
    )
    assert response.json() == {"camera": "cuisine", "mode": "on"}
    controller.setDayNightMode.assert_called_once_with("on")


def test_invalid_mode(monkeypatch):
    _, client, _ = load_app(monkeypatch)
    response = client.put(
        "/api/v1/cameras/cuisine/night-vision",
        headers={"Authorization": "Bearer test-token"},
        json={"mode": "invalid"},
    )
    assert response.status_code == 422
