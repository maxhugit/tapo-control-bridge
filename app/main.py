import json
import os
from dataclasses import dataclass
from threading import Lock
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel
from pytapo import Tapo
from starlette.concurrency import run_in_threadpool


NightMode = Literal["auto", "on", "off"]


class NightModeRequest(BaseModel):
    mode: NightMode


class NightModeResponse(BaseModel):
    camera: str
    mode: NightMode


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
        self.controller = Tapo(
            config.host,
            config.username,
            config.password,
            cloudPassword=config.cloud_password,
            childID=config.child_id,
            controlPort=config.control_port,
            printDebugInformation=False,
            redactConfidentialInformation=True,
        )


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
app = FastAPI(title="Tapo Control Bridge", version="1.0.0")


def authenticate(authorization: str | None = Header(default=None)) -> None:
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
        )


def get_camera(name: str) -> CameraClient:
    camera = CAMERAS.get(name)
    if camera is None:
        raise HTTPException(status_code=404, detail="Unknown camera")
    return camera


def read_mode(camera: CameraClient) -> NightMode:
    with camera.lock:
        value = camera.controller.getDayNightMode()
    if value not in {"auto", "on", "off"}:
        raise RuntimeError(f"Unexpected camera mode: {value}")
    return value


def write_mode(camera: CameraClient, mode: NightMode) -> NightMode:
    with camera.lock:
        result = camera.controller.setDayNightMode(mode)
    if isinstance(result, dict) and result.get("error_code", 0) != 0:
        raise RuntimeError(f"Camera rejected the command: {result['error_code']}")
    return mode


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/api/v1/cameras/{camera_name}/night-vision",
    response_model=NightModeResponse,
    dependencies=[Depends(authenticate)],
)
async def get_night_vision(camera_name: str) -> NightModeResponse:
    camera = get_camera(camera_name)
    try:
        mode = await run_in_threadpool(read_mode, camera)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return NightModeResponse(camera=camera_name, mode=mode)


@app.put(
    "/api/v1/cameras/{camera_name}/night-vision",
    response_model=NightModeResponse,
    dependencies=[Depends(authenticate)],
)
async def set_night_vision(
    camera_name: str, payload: NightModeRequest
) -> NightModeResponse:
    camera = get_camera(camera_name)
    try:
        mode = await run_in_threadpool(write_mode, camera, payload.mode)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return NightModeResponse(camera=camera_name, mode=mode)
