import importlib
import json
import sys
from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def load_app(monkeypatch):
    controller = MagicMock()
    controller.getDayNightMode.return_value = "auto"
    controller.setDayNightMode.return_value = {"error_code": 0}
    controller.getPresets.return_value = {"1": "Entrée", "2": "Canapé"}
    controller.getPrivacyMode.return_value = {"enabled": "off"}
    controller.getLED.return_value = {"enabled": "on"}
    controller.getAutoTrackTarget.return_value = {"enabled": "off"}
    controller.getAlarm.return_value = {"enabled": "off"}
    controller.getAudioConfig.return_value = {"speaker": {"volume": 50}}
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


def auth():
    return {"Authorization": "Bearer test-token"}


def test_list_cameras(monkeypatch):
    _, client, _ = load_app(monkeypatch)
    assert client.get("/api/v1/cameras", headers=auth()).json() == {
        "cameras": ["cuisine"]
    }


def test_ptz(monkeypatch):
    _, client, controller = load_app(monkeypatch)
    response = client.post(
        "/api/v1/cameras/cuisine/ptz",
        headers=auth(),
        json={"direction": "left", "steps": 2},
    )
    assert response.status_code == 200
    assert controller.moveMotorCounterClockWise.call_count == 2


def test_presets_and_goto_by_name(monkeypatch):
    _, client, controller = load_app(monkeypatch)
    assert client.get(
        "/api/v1/cameras/cuisine/presets", headers=auth()
    ).json()["presets"] == {"1": "Entrée", "2": "Canapé"}
    response = client.post(
        "/api/v1/cameras/cuisine/presets/goto",
        headers=auth(),
        json={"preset": "Canapé"},
    )
    assert response.json()["preset_id"] == "2"
    controller.setPreset.assert_called_once_with("2")


def test_switch_controls(monkeypatch):
    _, client, controller = load_app(monkeypatch)
    endpoints = {
        "privacy": "setPrivacyMode",
        "led": "setLEDEnabled",
        "auto-track": "setAutoTrackTarget",
    }
    for endpoint, method in endpoints.items():
        response = client.put(
            f"/api/v1/cameras/cuisine/{endpoint}",
            headers=auth(),
            json={"enabled": True},
        )
        assert response.status_code == 200
        getattr(controller, method).assert_called_once_with(True)


def test_alarm(monkeypatch):
    _, client, controller = load_app(monkeypatch)
    response = client.put(
        "/api/v1/cameras/cuisine/alarm",
        headers=auth(),
        json={"enabled": True, "sound": True, "light": False, "volume": 40},
    )
    assert response.status_code == 200
    controller.setAlarm.assert_called_once_with(True, True, False, 40, None, None)
    client.post(
        "/api/v1/cameras/cuisine/alarm/manual",
        headers=auth(),
        json={"action": "start"},
    )
    controller.startManualAlarm.assert_called_once_with()


def test_audio(monkeypatch):
    _, client, controller = load_app(monkeypatch)
    response = client.put(
        "/api/v1/cameras/cuisine/audio",
        headers=auth(),
        json={
            "speaker_volume": 70,
            "microphone_muted": True,
            "record_audio": False,
        },
    )
    assert response.status_code == 200
    controller.setSpeakerVolume.assert_called_once_with(70)
    controller.setMicrophone.assert_called_once_with(None, True, None)
    controller.setRecordAudio.assert_called_once_with(False)


def test_reboot(monkeypatch):
    _, client, controller = load_app(monkeypatch)
    response = client.post("/api/v1/cameras/cuisine/reboot", headers=auth())
    assert response.json()["rebooting"] is True
    controller.reboot.assert_called_once_with()


def test_camera_error_is_a_bad_gateway(monkeypatch):
    _, client, controller = load_app(monkeypatch)
    controller.getLED.side_effect = RuntimeError("unsupported")
    response = client.get("/api/v1/cameras/cuisine/led", headers=auth())
    assert response.status_code == 502
