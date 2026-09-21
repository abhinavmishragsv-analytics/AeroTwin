# AeroTwin

A bi-directional 3D digital twin of Indian airport ground and terminal-area
operations, built around a real, surveyed model of **Vadodara Airport (VABO)**
and a generic airport builder that extends the same simulation to Delhi,
Mumbai, Ahmedabad, Pune and Surat.

"Bi-directional" means the browser is not just a viewer: posting a disruption
(`POST /api/airports/{icao}/disrupt`) mutates the live SimPy simulation, and
every connected client sees the consequence within a frame - aircraft holding
short, arrivals going around, ground traffic re-routing around a closed
taxiway.

## What's here

- **A real ATC layer**, not a timer. Every taxiway segment and every taxiway
  junction is a single-occupancy resource; a taxi clearance acquires them all
  in one canonical order, which makes ground deadlock structurally impossible
  and two-aircraft-in-the-same-place structurally impossible. The runway is a
  priority resource with wake-turbulence separation, crosswind/tailwind
  limits, and CAT I/none low-visibility minima. See `core/atc.py`.
- **A procedurally generated airfield.** `core/airports/geometry.py` turns a
  short structural description (runway thresholds, a taxi graph, stand
  positions) into every piece of drawable geometry - pavement, piano keys,
  touchdown-zone bars, ICAO hold-position markings, edge lights, stand stop
  bars, extruded buildings - in WGS84, server-side. The frontend draws exactly
  this and nothing else, so the picture can never drift from what the
  simulation believes the airport looks like.
- **A real taxi router.** `core/routing.py` runs Dijkstra over the taxi graph,
  preferring taxiways to taxilanes and rapid exits to right-angle turn-offs -
  the shape of clearance a real ground controller would give.
- **A real fleet.** `core/aircraft.py` carries published performance for eight
  aircraft types (A320neo, A321neo, 737-800, 737 MAX 8, ATR 72-600, Dash 8
  Q400, 787-9, 777-300ER): takeoff/landing distance, rotation speed, climb
  rate, wake category. An intersection departure is only offered when the
  runway remaining is actually enough for that aircraft.
- **Multi-airport from one engine.** Each airport gets its own SimPy
  environment and its own WebSocket audience
  (`ws://.../ws/twin/{icao-or-slug}`), created lazily on first connection.
  `/vadodara`, `/delhi`, `/mumbai`, `/ahmedabad`, `/pune`, `/surat` are all the
  same code running different data.
- **Multi-runway operations.** Every runway has its own parallel taxiway,
  holding points, runway entries and rapid exits, and its own connections to
  the apron - Delhi's three and Mumbai's two are flown, not painted. Traffic
  is allocated across runways by wind, length and queue depth. Runways whose
  centrelines physically intersect (Mumbai's 09/27 and 14/32) share one
  occupancy resource and are sequenced as a single runway. Where a taxiway
  crosses a runway to reach the apron, the aircraft holds short and takes
  that runway's clearance before crossing.
- **A page load is its own simulation.** Twins are keyed by airport and by a
  session id generated per page load, so a reload starts a fresh airport at
  T+0 rather than joining one that has been running for hours. The simulation
  runs server-side, so backgrounding the tab does not pause it.
- **ML model integration.** `core/models.py` loads whatever `.pkl` artifacts
  exist in `core/models/` (macro delay forecast, taxi-time regression,
  congestion-tier clustering, network criticality, weather ground-stop
  probability) and the simulation calls them for taxi-time prediction and risk
  scoring; the notebooks that train them are in `notebooks/`. With no `.pkl`
  present the registry falls back to a documented heuristic, so the twin runs
  standalone.

## Why it doesn't collide

Ground and runway conflicts are prevented by construction, not by tuning:
every piece of pavement an aircraft could occupy is a capacity-1 resource, and
a route is only granted once every resource along it is acquired. That claim
is checked, not just asserted - `scripts/soak_test.py` runs each airport
headless, far faster than real time, under both nominal traffic and a
deliberately hostile disruption sequence (runway closure, fog, taxiway
closure, high wind, an emergency arrival, a thunderstorm), and audits actual
inter-aircraft distances every frame:

```bash
python scripts/soak_test.py            # all six airports, 60 sim-minutes each
python scripts/soak_test.py VABO 180   # one airport, 3 sim-hours
python scripts/soak_test.py --leak-check   # 10 sim-hours, throughput over time
```

`--leak-check` exists because the 60-minute run could not see a slow
resource leak: throughput looks healthy right up until whatever is being
leaked (a stand, a taxiway lock) runs out. It compares movements in the first
third of a long run against the last third.

A `PASS` means zero ground separation violations (55 m standard), zero
airborne separation violations (300 m / 120 ft standard), and zero runway
incursions, for the whole run. Run this after any change to `core/atc.py`,
`core/routing.py`, or an airport layout.

## Architecture

```
core/
  geo.py              spherical + local-flat geodesy shared by everything
  airports/
    schema.py          the structural description: runways, taxi graph, stands, buildings
    geometry.py         schema -> drawable visuals (pavement, paint, lights, signs)
    vabo.py              the surveyed VABO layout
    generic.py            builds a structurally identical airport from thresholds + apron params
    __init__.py             registry: ICAO / IATA / slug / city -> layout
  aircraft.py         fleet performance data, wake separation tables
  routing.py          Dijkstra taxi-route planning
  atc.py              GroundNetwork (locking), RunwayController, StandManager, SeparationMonitor
  twin_sim.py         the SimPy flight lifecycle: arrival, hold, go-around, divert,
                       taxi-in, turnaround, pushback, taxi-out, departure
  main.py             FastAPI: REST + WebSocket, one AirportTwin per ICAO
  models.py           ML model registry (unchanged - loads core/models/*.pkl)
scripts/
  soak_test.py        headless safety audit (see above)
ui/
  src/lib/api.js               API base + URL-slug resolution
  src/lib/airfieldLayers.js    layout.visuals -> Deck.GL layers
  src/lib/aircraftLayers.js    live flight frames -> Deck.GL layers
  src/components/              HUD, flight strips, ATC console, camera bar, weather, airport switcher
  src/App.jsx                  ties it together: WebSocket in, Deck.GL + MapLibre out
```

## Running it

Backend:

```bash
pip install -r requirements.txt
uvicorn core.main:app --reload
```

Frontend:

```bash
cd ui
npm install
npm run dev
```

Open `http://localhost:5173/` for Vadodara, or `http://localhost:5173/delhi`,
`/mumbai`, `/ahmedabad`, `/pune`, `/surat` for the other airports. The dev
server's SPA fallback means any of these paths load the same app; `App.jsx`
reads the path once on load to pick the airport.

Set `AEROTWIN_TIME_COMPRESSION` (default `36.0`) to change how many simulated
seconds pass per wall-clock second; `1.0` runs in real time.

## What's real vs representative

VABO's runway thresholds, dimensions, and CAT I status are surveyed from
public sources and drive every other measurement on the field (taxiway
offset, hold-short distance, stand spacing). The other five airports use real
runway thresholds with a representative, not charted, apron and taxiway
arrangement - flagged as `"detail": "representative"` in `GET /api/airports`.
This is a simulation and training tool, not a navigation reference.

## Extending to another airport

Add one function to `core/airports/__init__.py` that calls
`core.airports.generic.build_airport(...)` with the new airport's runway
thresholds and apron parameters, and register it in `_BUILDERS`. Everything
else - routing, locking, separation, the frontend - works unchanged, because
none of it knows it isn't looking at VABO.
