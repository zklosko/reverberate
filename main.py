"""
FastAPI control layer for the mock lighting controller.

Run with:
    uvicorn app.main:app --reload --port 8000

The UDP listener starts in the same event loop as FastAPI (via lifespan),
so both share the same FixtureState with no extra IPC needed.

Endpoints:
    GET  /state                 -> current fixture/channel state snapshot
    GET  /log?n=50              -> recent packet log (rx + tx)
    POST /config/port           -> stop and restart the UDP listener on a new port
    GET  /config/port           -> current UDP port
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.state import fixture_state
from src.udp_server import start_udp_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
logger = logging.getLogger("main")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 4703  # change to your controller's real default port

_udp_handle = {"transport": None, "protocol": None, "host": DEFAULT_HOST, "port": DEFAULT_PORT}


@asynccontextmanager
async def lifespan(app: FastAPI):
    transport, protocol = await start_udp_server(_udp_handle["host"], _udp_handle["port"])
    _udp_handle["transport"] = transport
    _udp_handle["protocol"] = protocol
    yield
    transport.close()


app = FastAPI(title="Mock Lighting Controller", lifespan=lifespan)


# ---------- inspection ----------

@app.get("/state")
async def get_state():
    return await fixture_state.snapshot()


@app.get("/log")
async def get_log(n: int = 50):
    entries = await fixture_state.recent_log(n)
    return [
        {
            "direction": e.direction,
            "timestamp": e.timestamp,
            "addr": e.addr,
            "raw_ascii": e.raw.decode("ascii", errors="replace"),
            "raw_hex": e.raw.hex(),
            "parsed": e.parsed,
            # "note": e.note,
        }
        for e in entries
    ]

# ---------- runtime config ----------

class PortConfig(BaseModel):
    port: int = Field(..., ge=1, le=65535)
    host: Optional[str] = None


@app.get("/config/port")
async def get_port():
    return {"host": _udp_handle["host"], "port": _udp_handle["port"]}


@app.post("/config/port")
async def set_port(cfg: PortConfig):
    """Stop the current UDP listener and start a new one on the given port."""
    old_transport = _udp_handle["transport"]
    if old_transport is not None:
        old_transport.close()

    host = cfg.host or _udp_handle["host"]
    transport, protocol = await start_udp_server(host, cfg.port)
    _udp_handle.update({"transport": transport, "protocol": protocol, "host": host, "port": cfg.port})
    return {"ok": True, "host": host, "port": cfg.port}

# ---------- dashboard ----------
templates = Jinja2Templates(directory="src/templates/")

@app.get("/dashboard")
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")
