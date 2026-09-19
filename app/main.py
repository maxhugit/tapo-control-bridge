import json
import os
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from pytapo import Tapo
from starlette.concurrency import run_in_threadpool


NightMode = Literal["auto", "on", "off"]
Direction = Literal["left", "right", "up", "down"]
AlarmAction = Literal["start", "stop"]


class NightModeRequest(BaseModel):
    mode: NightMode


class BooleanRequest(BaseModel):
    enabled: bool


class PtzRequest(BaseModel):
    direction: Direction
    steps: int = Field(default=1, ge=1, le=10)


class PresetRequest(BaseModel):
    preset: str


class AlarmConfigRequest(BaseModel):
    enabled: bool
    sound: bool = True
    light: bool = True
    volume: int | None = Field(default=None, ge=0, le=100)
    duration: int | None = Field(default=None, ge=1, le=600)
    alarm_type: str | None = None

    @model_validator(mode="after")
    def validate_outputs(self) -> "AlarmConfigRequest":
        if not self.sound and not self.light:
            raise ValueError("At least one of sound or light must be enabled")
        return self


class ManualAlarmRequest(BaseModel):
    action: AlarmAction


class AudioRequest(BaseModel):
    speaker_volume: int | None = Field(default=None, ge=0, le=100)
    microphone_volume: int | None = Field(default=None, ge=0, le=100)
    microphone_muted: bool | None = None
    noise_cancelling: bool | None = None
    record_audio: bool | None = None

    @model_validator(mode="after")
    def validate_change(self) -> "AudioRequest":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("At least one audio setting is required")
        return self


@dataclass(frozen=True)
class CameraConfig:
    host: str
    username: str
    password: str
    cloud_password: str = ""
    child_id: str | None = None
    control_port: int = 443


class CameraClient:
    def __init__(self, config: CameraConfig) -> None:
        self.lock = Lock()
        self.config = config
        self.controller: Tapo | None = None

    def get_controller(self) -> Tapo:
        if self.controller is None:
            self.controller = Tapo(
                self.config.host,
                self.config.username,
                self.config.password,
                cloudPassword=self.config.cloud_password,
                childID=self.config.child_id,
                controlPort=self.config.control_port,
                printDebugInformation=False,
                redactConfidentialInformation=True,
            )
        return self.controller


def load_cameras() -> dict[str, CameraClient]:
    raw = os.environ.get("CAMERAS_JSON", "")
    if not raw:
        raise RuntimeError("CAMERAS_JSON is required")
    try:
        values = json.loads(raw)
        return {
            name: CameraClient(CameraConfig(**config))
            for name, config in values.items()
        }
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError("CAMERAS_JSON is invalid") from exc


API_TOKEN = os.environ.get("API_TOKEN", "")
if not API_TOKEN:
    raise RuntimeError("API_TOKEN is required")

CAMERAS = load_cameras()
app = FastAPI(title="Tapo Control Bridge", version="2.0.0")


def authenticate(authorization: str | None = Header(default=None)) -> None:
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")


def get_camera(name: str) -> CameraClient:
    camera = CAMERAS.get(name)
    if camera is None:
        raise HTTPException(status_code=404, detail="Unknown camera")
    return camera


def call(camera: CameraClient, method: str, *args: Any, **kwargs: Any) -> Any:
    with camera.lock:
        return getattr(camera.get_controller(), method)(*args, **kwargs)


async def camera_call(camera_name: str, method: str, *args: Any, **kwargs: Any) -> Any:
    camera = get_camera(camera_name)
    try:
        return await run_in_threadpool(call, camera, method, *args, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def response(camera_name: str, **values: Any) -> dict[str, Any]:
    return {"camera": camera_name, **values}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/cameras", dependencies=[Depends(authenticate)])
def list_cameras() -> dict[str, list[str]]:
    return {"cameras": sorted(CAMERAS)}


@app.get("/api/v1/cameras/{camera_name}/night-vision", dependencies=[Depends(authenticate)])
async def get_night_vision(camera_name: str) -> dict[str, Any]:
    return response(camera_name, mode=await camera_call(camera_name, "getDayNightMode"))


@app.put("/api/v1/cameras/{camera_name}/night-vision", dependencies=[Depends(authenticate)])
async def set_night_vision(camera_name: str, payload: NightModeRequest) -> dict[str, Any]:
    await camera_call(camera_name, "setDayNightMode", payload.mode)
    return response(camera_name, mode=payload.mode)


@app.post("/api/v1/cameras/{camera_name}/ptz", dependencies=[Depends(authenticate)])
async def move_ptz(camera_name: str, payload: PtzRequest) -> dict[str, Any]:
    methods = {"right": "moveMotorClockWise", "left": "moveMotorCounterClockWise", "up": "moveMotorVertical", "down": "moveMotorHorizontal"}
    for _ in range(payload.steps):
        await camera_call(camera_name, methods[payload.direction])
    return response(camera_name, direction=payload.direction, steps=payload.steps)


@app.get("/api/v1/cameras/{camera_name}/presets", dependencies=[Depends(authenticate)])
async def get_presets(camera_name: str) -> dict[str, Any]:
    return response(camera_name, presets=await camera_call(camera_name, "getPresets"))


@app.post("/api/v1/cameras/{camera_name}/presets/goto", dependencies=[Depends(authenticate)])
async def goto_preset(camera_name: str, payload: PresetRequest) -> dict[str, Any]:
    presets = await camera_call(camera_name, "getPresets")
    preset_id = payload.preset
    if preset_id not in presets:
        matches = [key for key, name in presets.items() if name == payload.preset]
        if not matches:
            raise HTTPException(status_code=404, detail="Unknown preset")
        preset_id = matches[0]
    await camera_call(camera_name, "setPreset", preset_id)
    return response(camera_name, preset_id=preset_id, preset_name=presets[preset_id])


@app.get("/api/v1/cameras/{camera_name}/privacy", dependencies=[Depends(authenticate)])
async def get_privacy(camera_name: str) -> dict[str, Any]:
    return response(camera_name, state=await camera_call(camera_name, "getPrivacyMode"))


@app.put("/api/v1/cameras/{camera_name}/privacy", dependencies=[Depends(authenticate)])
async def set_privacy(camera_name: str, payload: BooleanRequest) -> dict[str, Any]:
    await camera_call(camera_name, "setPrivacyMode", payload.enabled)
    return response(camera_name, enabled=payload.enabled)


@app.get("/api/v1/cameras/{camera_name}/led", dependencies=[Depends(authenticate)])
async def get_led(camera_name: str) -> dict[str, Any]:
    return response(camera_name, state=await camera_call(camera_name, "getLED"))


@app.put("/api/v1/cameras/{camera_name}/led", dependencies=[Depends(authenticate)])
async def set_led(camera_name: str, payload: BooleanRequest) -> dict[str, Any]:
    await camera_call(camera_name, "setLEDEnabled", payload.enabled)
    return response(camera_name, enabled=payload.enabled)


@app.get("/api/v1/cameras/{camera_name}/auto-track", dependencies=[Depends(authenticate)])
async def get_auto_track(camera_name: str) -> dict[str, Any]:
    return response(camera_name, state=await camera_call(camera_name, "getAutoTrackTarget"))


@app.put("/api/v1/cameras/{camera_name}/auto-track", dependencies=[Depends(authenticate)])
async def set_auto_track(camera_name: str, payload: BooleanRequest) -> dict[str, Any]:
    await camera_call(camera_name, "setAutoTrackTarget", payload.enabled)
    return response(camera_name, enabled=payload.enabled)


@app.get("/api/v1/cameras/{camera_name}/alarm", dependencies=[Depends(authenticate)])
async def get_alarm(camera_name: str) -> dict[str, Any]:
    return response(camera_name, state=await camera_call(camera_name, "getAlarm"))


@app.put("/api/v1/cameras/{camera_name}/alarm", dependencies=[Depends(authenticate)])
async def set_alarm(camera_name: str, payload: AlarmConfigRequest) -> dict[str, Any]:
    await camera_call(camera_name, "setAlarm", payload.enabled, payload.sound, payload.light, payload.volume, payload.duration, payload.alarm_type)
    return response(camera_name, **payload.model_dump())


@app.post("/api/v1/cameras/{camera_name}/alarm/manual", dependencies=[Depends(authenticate)])
async def manual_alarm(camera_name: str, payload: ManualAlarmRequest) -> dict[str, Any]:
    await camera_call(camera_name, "startManualAlarm" if payload.action == "start" else "stopManualAlarm")
    return response(camera_name, action=payload.action)


@app.get("/api/v1/cameras/{camera_name}/audio", dependencies=[Depends(authenticate)])
async def get_audio(camera_name: str) -> dict[str, Any]:
    return response(camera_name, state=await camera_call(camera_name, "getAudioConfig"))


@app.put("/api/v1/cameras/{camera_name}/audio", dependencies=[Depends(authenticate)])
async def set_audio(camera_name: str, payload: AudioRequest) -> dict[str, Any]:
    if payload.speaker_volume is not None:
        await camera_call(camera_name, "setSpeakerVolume", payload.speaker_volume)
    if any(value is not None for value in (payload.microphone_volume, payload.microphone_muted, payload.noise_cancelling)):
        await camera_call(camera_name, "setMicrophone", payload.microphone_volume, payload.microphone_muted, payload.noise_cancelling)
    if payload.record_audio is not None:
        await camera_call(camera_name, "setRecordAudio", payload.record_audio)
    return response(camera_name, **payload.model_dump())


@app.post("/api/v1/cameras/{camera_name}/reboot", dependencies=[Depends(authenticate)])
async def reboot(camera_name: str) -> dict[str, Any]:
    await camera_call(camera_name, "reboot")
    return response(camera_name, rebooting=True)
