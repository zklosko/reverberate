# Reverberate

A fake UDP "fixture" for testing lighting-control plugins for ETC's Echo (get it?) Integration Interface locally,
with a FastAPI control layer for inspecting traffic.

## Getting started

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

This starts two things in one process/event loop:
- A UDP listener on `0.0.0.0:8043` (change the default in `main.py`, or
  override at runtime via `POST /config/port`)
- An HTTP control API on `http://localhost:8000` — Swagger docs at
  `http://localhost:8000/docs`
  - In addition, a live dashboard is available at `http://localhost:8000/dashboard`

Point your plugin at `127.0.0.1:8043` instead of the real controller.

## HTTP endpoints

| Method | Path                    | Purpose                                      |
|--------|-------------------------|-----------------------------------------------|
| GET    | `/state`                | Current fixture/channel state snapshot        |
| GET    | `/log?n=50`             | Recent packet log (rx + tx, with parsed data) |
| GET/POST | `/config/port`        | Read or change the UDP listen port at runtime |

Example — change the UDP port at runtime:

```bash
curl -X POST http://localhost:8000/config/port -H "Content-Type: application/json" -d '{"port": 7000}'
```

## Notes

- The packet log keeps the last 500 entries (both directions) in memory;
  bump `maxlen` in `FixtureState.log` if you want more history.
- Since UDP is connectionless, "port can be changed by the user" is
  handled by tearing down and recreating the `asyncio` datagram endpoint
  via `/config/port` — no server restart needed.
