# Tapo Control Bridge

Small, local-only HTTP bridge for TP-Link Tapo camera settings that are not
exposed by Frigate. The first supported setting is **Night Vision Switching**.

## Security

- Keep this service on the trusted LAN; do not publish it through Traefik.
- Every camera endpoint requires a bearer token.
- Camera credentials are supplied at runtime and are never stored in the image.
- Do not commit `.env`, Unraid templates containing secrets, or real credentials.

## Configuration

The service requires two environment variables:

- `API_TOKEN`: a long random token used by Home Assistant.
- `CAMERAS_JSON`: a JSON object keyed by the local camera name.

```json
{
  "cuisine": {
    "host": "192.168.100.80",
    "username": "camera-local-user",
    "password": "replace-me"
  }
}
```

Optional camera fields are `cloud_password`, `child_id`, and `control_port`.

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

## Unraid

Use `ghcr.io/maxhugit/tapo-control-bridge:latest`, expose container port `8080`
only on the LAN, and add `API_TOKEN` plus `CAMERAS_JSON` as environment
variables. See `docker-compose.example.yml` for an example.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```
