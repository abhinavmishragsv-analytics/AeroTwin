"""
AeroTwin VABO Digital Twin - FastAPI Server
=============================================
Runs a single, continuous SimPy simulation of Vadodara Airport (VABO) as a
background task and streams it to any number of connected 3D frontend
clients over WebSocket. The REST endpoints below are the "write" side of the
bi-directional twin: posting a disruption here mutates the *one* live
simulation, and every connected browser sees the effect within one frame.
"""
import asyncio
import logging
import random
import time

import simpy
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.config import AIRLINE_CODES, AIRPORT_ICAO, BASE_FLIGHT_SPAWN_INTERVAL_S, STREAM_HZ
from core.models import registry
from core.twin_sim import VadodaraAirport

logger = logging.getLogger("aerotwin.main")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="AeroTwin VABO Digital Twin",
    description="Vadodara Airport 3D Digital Twin Engine - bi-directional SimPy + ML simulation",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SimulationHub:
    """Owns the single, always-running SimPy environment and its WebSocket audience."""

    def __init__(self):
        self.env = simpy.Environment()
        self.airport = VadodaraAirport(self.env)
        self.clients: set[WebSocket] = set()
        self._flight_counter = 101
        self._tasks_started = False

    async def start(self):
        if self._tasks_started:
            return
        self._tasks_started = True
        asyncio.create_task(self._flight_generator())
        asyncio.create_task(self._simulation_loop())
        logger.info("AeroTwin simulation hub started for %s", AIRPORT_ICAO)

    async def _flight_generator(self):
        # Seed the apron with one aircraft immediately so the twin isn't empty on first connect
        self.env.process(self.airport.pushback_and_depart(f"6E-{self._flight_counter}"))
        self._flight_counter += 1

        while True:
            await asyncio.sleep(BASE_FLIGHT_SPAWN_INTERVAL_S)
            airline_code = random.choice(AIRLINE_CODES)
            self.env.process(self.airport.pushback_and_depart(f"{airline_code}-{self._flight_counter}"))
            self._flight_counter += 1

    async def _simulation_loop(self):
        period = 1.0 / STREAM_HZ
        while True:
            if self.env.peek() != float("inf"):
                self.env.step()
            await self._broadcast()
            await asyncio.sleep(period)

    async def _broadcast(self):
        if not self.clients:
            return
        active_flights = [f for f in self.airport.flights.values() if f["status"] != "airborne"]
        payload = {
            "flights": active_flights,
            "time": round(self.env.now, 1),
            "airport": AIRPORT_ICAO,
            "twin": self.airport.status_snapshot(),
        }
        dead = set()
        for ws in self.clients:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001 - client disconnected mid-broadcast
                dead.add(ws)
        self.clients -= dead


hub = SimulationHub()


@app.on_event("startup")
async def _on_startup():
    await hub.start()


@app.get("/")
async def root():
    return {
        "status": "online",
        "airport": AIRPORT_ICAO,
        "name": "Vadodara Airport 3D Twin",
        "sim_time_s": round(hub.env.now, 1),
        "connected_clients": len(hub.clients),
    }


@app.get("/api/status")
async def status():
    return hub.airport.status_snapshot()


@app.get("/api/models")
async def models_status():
    return registry.summary()


@app.post("/api/models/reload")
async def models_reload():
    """Hot-reload .pkl artifacts dropped into core/models/ (e.g. after a Colab training run)."""
    return registry.reload()


class DisruptionRequest(BaseModel):
    type: str  # runway_closure | maintenance_delay | ground_stop | fog | high_wind | clear
    duration_minutes: float = 15.0
    label: str | None = None


VALID_DISRUPTIONS = {"runway_closure", "maintenance_delay", "ground_stop", "fog", "high_wind", "clear"}


@app.post("/api/disrupt")
async def disrupt(req: DisruptionRequest):
    if req.type not in VALID_DISRUPTIONS:
        raise HTTPException(status_code=400, detail=f"type must be one of {sorted(VALID_DISRUPTIONS)}")
    if not (0 <= req.duration_minutes <= 180):
        raise HTTPException(status_code=400, detail="duration_minutes must be between 0 and 180")
    entry = hub.airport.inject_disruption(req.type, req.duration_minutes, req.label)
    return {"ok": True, "disruption": entry, "twin": hub.airport.status_snapshot()}


@app.websocket("/ws/twin")
async def twin_stream(websocket: WebSocket):
    await websocket.accept()
    hub.clients.add(websocket)
    try:
        while True:
            # We don't expect inbound messages, but keep the socket alive and detect disconnects
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.info("Twin WebSocket client disconnected: %s", exc)
    finally:
        hub.clients.discard(websocket)
