"""
AeroTwin Server
===============
FastAPI front door for the digital twin.

Multi-airport from here down: each aerodrome gets its own SimPy environment,
its own ATC and its own WebSocket audience, created lazily the first time
someone connects to it. `/ws/twin/VABO` and `/ws/twin/VIDP` are two independent,
simultaneously-running twins, which is what makes the planned `/delhi`,
`/mumbai` URLs a routing concern in the frontend rather than a rebuild here.

The REST endpoints are the write side of the bi-directional twin: posting a
disruption mutates the one live simulation for that airport, and every browser
watching it sees the consequence within a frame - aircraft holding short,
arrivals going around, traffic re-routing around a closed taxiway.
"""
import asyncio
import logging
import time

import simpy
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core import airports
from core.aircraft import FLEET
from core.config import ARRIVAL_SHARE, DISRUPTION_MAX_MINUTES, STREAM_HZ, TIME_COMPRESSION
from core.models import registry
from core.twin_sim import Aerodrome

logger = logging.getLogger("aerotwin.main")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="AeroTwin",
    description="Bi-directional 3D digital twin of Indian airport ground operations",
    version="2.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_DISRUPTIONS = {
    "runway_closure", "maintenance_delay", "ground_stop", "fog", "low_visibility",
    "high_wind", "wind_shift", "thunderstorm", "taxiway_closure", "emergency_arrival", "clear",
}


class AirportTwin:
    """One airport: its SimPy environment, its simulation, its clients."""

    def __init__(self, icao: str):
        self.icao = icao
        self.layout = airports.get_layout(icao)
        self.env = simpy.Environment()
        self.sim = Aerodrome(self.env, self.layout)
        self.clients: set[WebSocket] = set()
        self._tasks = []
        self._started = False
        self._wall_start = time.monotonic()

    async def start(self):
        if self._started:
            return
        self._started = True
        self._tasks = [
            asyncio.create_task(self._traffic_generator()),
            asyncio.create_task(self._clock()),
        ]
        logger.info("AeroTwin: %s simulation started", self.icao)

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        self._tasks = []
        self._started = False

    # -- traffic -----------------------------------------------------------
    async def _traffic_generator(self):
        """Spawn arrivals and departures at the airport's real movement rate.

        Departures mostly come from aircraft already on stand that have turned
        around; this generator adds arrivals, and tops up departures only when
        the apron has aircraft sitting idle.
        """
        interval_s = 3600.0 / max(1, self.layout.movements_per_hour) / TIME_COMPRESSION
        await asyncio.sleep(2.0)
        while True:
            try:
                want_arrival = self.sim.rng.random() < ARRIVAL_SHARE
                if want_arrival and self.sim.accepts_arrival():
                    self.env.process(self.sim.operate_arrival())
                elif self.sim.accepts_departure():
                    # If approach control would not release another inbound
                    # (spacing, approach saturation, or no stand to park it on),
                    # the slot goes to a departure instead of manufacturing an
                    # arrival that will only have to go around - but only if the
                    # departure queue can actually absorb one. Otherwise the
                    # slot is simply skipped: an aircraft that would sit on a
                    # stand for an hour waiting to push back is not traffic,
                    # it is just a stand taken out of service.
                    self.env.process(self.sim.operate_departure())
            except Exception:  # noqa: BLE001
                logger.exception("traffic generator tick failed")
            await asyncio.sleep(interval_s)

    # -- clock -------------------------------------------------------------
    async def _clock(self):
        """Advance the SimPy clock in real time and broadcast each frame.

        The clock advances TIME_COMPRESSION simulated seconds per wall second,
        so every duration inside the model stays a real-world number.
        """
        period = 1.0 / STREAM_HZ
        last_reap = time.monotonic()
        while True:
            try:
                self.env.run(until=self.env.now + period * TIME_COMPRESSION)
                self.sim.monitor.audit(list(self.sim.flights.values()), self.sim.runway_ctl)
                await self._broadcast()
                if time.monotonic() - last_reap > 5.0:
                    self.sim.reap()
                    last_reap = time.monotonic()
            except Exception:  # noqa: BLE001
                # The twin must never die on one bad tick: an uncaught error
                # here would freeze the airport for every connected client with
                # no visible symptom beyond a stopped picture.
                logger.exception("%s simulation tick failed; continuing", self.icao)
            await asyncio.sleep(period)

    def frame(self):
        visible = [f for f in self.sim.flights.values() if f["status"] != "despawned"]
        return {
            "airport": self.icao,
            "time": round(self.env.now, 1),
            "wall_elapsed_s": round(time.monotonic() - self._wall_start, 1),
            "time_compression": TIME_COMPRESSION,
            "flights": [{k: v for k, v in f.items() if not k.startswith("_")} for f in visible],
            "twin": self.sim.status_snapshot(),
        }

    async def _broadcast(self):
        if not self.clients:
            return
        payload = self.frame()
        dead = set()
        # Snapshot the client set: a new connection can join mid-await, and
        # iterating the live set raises "changed size during iteration".
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001 - client vanished mid-send
                dead.add(ws)
        self.clients -= dead


class TwinRegistry:
    """Twins keyed by airport AND session.

    A page load is its own simulation, starting at T+0. Sharing one long-lived
    twin per airport meant a reload dropped you into a simulation that had
    been running for hours - the clock read T+40000s and the apron was already
    mid-turnaround, which is not what "open the page" should look like.

    A session keeps its twin for as long as the page lives, including while
    the tab is in the background: the simulation runs server-side, so hidden
    tabs and throttled browser timers do not pause it, and coming back shows
    the airport where it actually got to rather than where it was left.

    Abandoned twins are swept after a grace period, so a reload does not leak
    a simulation per page load, and a brief network blip does not destroy one.
    """

    GRACE_S = 90.0

    def __init__(self):
        self._twins: dict[str, AirportTwin] = {}
        self._empty_since: dict[str, float] = {}

    @staticmethod
    def _key(icao: str, session: str | None) -> str:
        return f"{icao.upper()}:{session}" if session else icao.upper()

    async def get(self, icao: str, session: str | None = None) -> AirportTwin:
        key = self._key(icao, session)
        if key not in self._twins:
            self._twins[key] = AirportTwin(icao.upper())
            await self._twins[key].start()
        self._empty_since.pop(key, None)
        return self._twins[key]

    def note_disconnect(self, icao: str, session: str | None):
        key = self._key(icao, session)
        twin = self._twins.get(key)
        if twin is not None and not twin.clients:
            self._empty_since[key] = time.monotonic()

    async def sweep(self):
        """Stop and drop twins whose last client left more than GRACE_S ago."""
        now = time.monotonic()
        for key, since in list(self._empty_since.items()):
            twin = self._twins.get(key)
            if twin is None:
                self._empty_since.pop(key, None)
                continue
            if twin.clients:
                self._empty_since.pop(key, None)
                continue
            if now - since >= self.GRACE_S:
                await twin.stop()
                self._twins.pop(key, None)
                self._empty_since.pop(key, None)
                logger.info("AeroTwin: swept idle twin %s", key)

    def peek(self, icao: str, session: str | None = None):
        return self._twins.get(self._key(icao, session))

    def live(self):
        return {k: len(v.clients) for k, v in self._twins.items()}


twins = TwinRegistry()


async def _sweeper():
    while True:
        await asyncio.sleep(30)
        try:
            await twins.sweep()
        except Exception:  # noqa: BLE001
            logger.exception("twin sweep failed")


@app.on_event("startup")
async def _startup():
    # The default airport is always warm, so the first page load is instant.
    await twins.get(airports.DEFAULT_ICAO)
    asyncio.create_task(_sweeper())


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "AeroTwin",
        "version": app.version,
        "default_airport": airports.DEFAULT_ICAO,
        "airports": airports.available_icaos(),
        "live_twins": twins.live(),
        "time_compression": TIME_COMPRESSION,
    }


@app.get("/api/airports")
async def list_airports():
    """Directory used by the frontend to resolve /delhi, /mumbai, ... to ICAO."""
    return {"airports": airports.directory(), "default": airports.DEFAULT_ICAO}


@app.get("/api/airports/{identifier}/layout")
async def airport_layout(identifier: str):
    """Full airfield: runways, taxi graph, stands, and all generated geometry.

    The client draws the airport from this and nothing else, so the picture can
    never drift from what the simulation believes the airport looks like.
    """
    try:
        icao = airports.resolve(identifier)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown airport {identifier!r}")
    return airports.layout_to_dict(airports.get_layout(icao))


@app.get("/api/airports/{identifier}/status")
async def airport_status(identifier: str, session: str | None = None):
    try:
        icao = airports.resolve(identifier)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown airport {identifier!r}")
    twin = await twins.get(icao, session)
    return twin.sim.status_snapshot()


@app.get("/api/fleet")
async def fleet():
    return {code: {
        "name": t.name, "wake": t.wake, "category": t.category,
        "wingspan_m": t.wingspan_m, "length_m": t.length_m, "seats": t.seats,
        "todr_m": t.todr_m, "approach_speed_kt": t.approach_speed_kt,
    } for code, t in FLEET.items()}


# ---------------------------------------------------------------------------
# ML model registry
# ---------------------------------------------------------------------------
@app.get("/api/models")
async def models_status():
    return registry.summary()


@app.post("/api/models/reload")
async def models_reload():
    """Hot-reload .pkl artifacts dropped into core/models/ after a Colab run."""
    return registry.reload()


# ---------------------------------------------------------------------------
# Disruption injection - the write side of the twin
# ---------------------------------------------------------------------------
class DisruptionRequest(BaseModel):
    type: str
    duration_minutes: float = 15.0
    label: str | None = None
    target: str | None = None       # e.g. taxiway name for taxiway_closure
    # Which page's simulation to mutate. Twins are per-session (see
    # TwinRegistry), so without this a disruption would land on a different
    # simulation than the one the person is looking at.
    session: str | None = None


@app.post("/api/airports/{identifier}/disrupt")
async def disrupt(identifier: str, req: DisruptionRequest):
    try:
        icao = airports.resolve(identifier)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown airport {identifier!r}")
    if req.type not in VALID_DISRUPTIONS:
        raise HTTPException(status_code=400, detail=f"type must be one of {sorted(VALID_DISRUPTIONS)}")
    if not (0 <= req.duration_minutes <= DISRUPTION_MAX_MINUTES):
        raise HTTPException(
            status_code=400,
            detail=f"duration_minutes must be between 0 and {DISRUPTION_MAX_MINUTES}",
        )
    twin = await twins.get(icao, req.session)
    entry = twin.sim.inject_disruption(req.type, req.duration_minutes, req.label, req.target)
    return {"ok": True, "disruption": entry, "twin": twin.sim.status_snapshot()}


@app.post("/api/disrupt")
async def disrupt_default(req: DisruptionRequest):
    """Kept so the older single-airport client keeps working."""
    return await disrupt(airports.DEFAULT_ICAO, req)


# ---------------------------------------------------------------------------
# Live stream
# ---------------------------------------------------------------------------
async def _stream(websocket: WebSocket, icao: str, session: str | None = None):
    twin = await twins.get(icao, session)
    await websocket.accept()
    twin.clients.add(websocket)
    try:
        # Send the layout first so the client can draw the airfield before the
        # first traffic frame arrives.
        await websocket.send_json({
            "kind": "layout",
            "layout": airports.layout_to_dict(twin.layout),
        })
        await websocket.send_json(twin.frame())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.info("%s client disconnected: %s", icao, exc)
    finally:
        twin.clients.discard(websocket)
        twins.note_disconnect(icao, session)


@app.websocket("/ws/twin/{identifier}")
async def twin_stream(websocket: WebSocket, identifier: str, session: str | None = None):
    try:
        icao = airports.resolve(identifier)
    except KeyError:
        await websocket.close(code=4004)
        return
    await _stream(websocket, icao, session)


@app.websocket("/ws/twin")
async def twin_stream_default(websocket: WebSocket, session: str | None = None):
    await _stream(websocket, airports.DEFAULT_ICAO, session)
