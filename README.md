# Tapo Control Bridge

Small, local-only HTTP bridge for TP-Link Tapo camera controls that are not
exposed by Frigate. It is designed to let Home Assistant keep the Frigate
camera entities while replacing the separate Tapo camera integration.

Supported controls:

- Night vision (`auto`, `on`, `off`)
- PTZ movement (left, right, up, down)
- Automatic preset discovery and move-to-preset by ID or name
- Privacy mode
- Status LED
- Automatic motion tracking
- Alarm configuration and manual siren start/stop
- Speaker, microphone, noise cancellation and audio recording settings
- Camera reboot

Availability depends on each camera model and firmware. An unsupported command
returns HTTP `502` with the error reported by the camera.

## Security

- Keep this service on the trusted LAN; do not publish it through Traefik.
- Every camera endpoint requires a bearer token.
- Camera credentials are supplied at runtime and are never stored in the image.
- Do not commit `.env`, Unraid templates containing secrets, or real credentials.

## Configuration

The service requires one environment variable:

- `CONFIG_FILE`: the path of the JSON configuration inside the container,
  normally `/config/config.json`.

The API token and all camera settings are stored in that JSON file:

```json
{
  "api_token": "replace-with-a-long-random-token",
  "cameras": {
    "cuisine": {
      "host": "192.168.100.80",
      "username": "admin",
      "password": "replace-me",
      "cloud_password": "replace-me",
      "control_port": 443
    }
  }
}
```

`api_token` plus each camera's `host`, `username`, and `password` are required.
Optional camera fields are `cloud_password`, `child_id`, and `control_port`
(defaults to `443`). Mount the file read-only and restrict its host permissions
because it contains all service secrets. See `config.example.json`.

## API

Health check (no authentication):

```text
GET /health
```

Read Night Vision Switching:

```text
GET /api/v1/cameras/{camera}/night-vision
Authorization: Bearer <API_TOKEN>
```

Change the mode:

```text
PUT /api/v1/cameras/{camera}/night-vision
Authorization: Bearer <API_TOKEN>
Content-Type: application/json

{"mode":"auto"}
```

Accepted values are `auto`, `on`, and `off`.

All endpoints below require `Authorization: Bearer <API_TOKEN>`.

| Method | Endpoint | JSON body |
|---|---|---|
| `GET` | `/api/v1/cameras` | — |
| `POST` | `/api/v1/cameras/{camera}/ptz` | `{"direction":"left","steps":1}` |
| `GET` | `/api/v1/cameras/{camera}/presets` | — |
| `POST` | `/api/v1/cameras/{camera}/presets/goto` | `{"preset":"Canapé"}` |
| `GET/PUT` | `/api/v1/cameras/{camera}/privacy` | `{"enabled":true}` for PUT |
| `GET/PUT` | `/api/v1/cameras/{camera}/led` | `{"enabled":false}` for PUT |
| `GET/PUT` | `/api/v1/cameras/{camera}/auto-track` | `{"enabled":true}` for PUT |
| `GET/PUT` | `/api/v1/cameras/{camera}/alarm` | See alarm example below |
| `POST` | `/api/v1/cameras/{camera}/alarm/manual` | `{"action":"start"}` or `stop` |
| `GET/PUT` | `/api/v1/cameras/{camera}/audio` | See audio example below |
| `POST` | `/api/v1/cameras/{camera}/reboot` | — |

Alarm configuration example:

```json
{
  "enabled": true,
  "sound": true,
  "light": false,
  "volume": 40,
  "duration": 10
}
```

Audio configuration example (every field is optional, but at least one is
required):

```json
{
  "speaker_volume": 70,
  "microphone_volume": 50,
  "microphone_muted": false,
  "noise_cancelling": true,
  "record_audio": true
}
```

PTZ `steps` accepts values from 1 to 10. A step is the camera firmware's native
movement increment and is not guaranteed to represent an exact number of
degrees.

Interactive OpenAPI documentation is available locally at `/docs`.

## Deliberately excluded

SD-card formatting, firmware updates and recording-plan changes are not
exposed. These operations are destructive or overlap with Frigate's recording
role.

## Unraid

Use `ghcr.io/maxhugit/tapo-control-bridge:latest`, expose container port `8080`
only on the LAN, mount the host JSON file as `/config/config.json:ro`, and set
`CONFIG_FILE=/config/config.json`. See `docker-compose.example.yml` for an
example.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```
