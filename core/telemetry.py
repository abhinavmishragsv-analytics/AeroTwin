"""
AeroTwin Flight-Data Recorder
=============================
Records what every aircraft does, once per simulated second, and turns each
recording into the kind of analysis you would pull off a flight-data monitoring
system: speed, altitude, vertical speed, g-loads, approach deviations, engine
and brake behaviour, and a set of per-leg KPIs.

Legs, not flights
-----------------
The simulation reuses one flight record for arrival -> turnaround -> departure.
Those are very different things to analyse (an approach and a take-off roll
share almost no channels worth comparing), so the recorder splits them into two
independent *legs*: ``6E-142:ARR`` and ``6E-142:DEP``. A leg is "completed" when
the aircraft is parked on stand (arrival) or has left the twin's airspace
(departure). Diverted and cancelled legs are kept and tagged.

Where each number comes from
----------------------------
Every channel carries a provenance tag, shown in the UI, so nobody mistakes a
modelled engine parameter for something the simulation actually computed:

  sim      - read straight from the simulation (position, speed, altitude,
             heading, pitch, roll, phase, risk score)
  derived  - computed from the simulated motion with ordinary physics
             (vertical speed, accelerations, airspeed from ground speed and
             wind, glideslope deviation, distance along the runway)
  model    - plausible, deterministic engineering values that the simulation
             does not model itself (N1, EGT, fuel flow, weights, flap/gear
             configuration, brake temperature). They follow the simulated
             phase and speed, are seeded from the leg id so they are stable
             between requests, and are representative rather than
             type-certified numbers.

Only raw samples are stored (about 12 numbers per second per aircraft).
Everything else is computed on request, so recording stays cheap.
"""
from __future__ import annotations

import logging
import math
import zlib
from collections import OrderedDict

import numpy as np

from core import aircraft as fleet

logger = logging.getLogger("aerotwin.telemetry")

KT = 0.514444          # knots -> m/s
FT = 3.28084           # metres -> feet
FPM = 0.00508          # feet/min -> m/s
G = 9.80665
M_PER_DEG_LAT = 111320.0

SAMPLE_DT = 1.0        # simulated seconds between samples
MAX_LEGS = 400         # completed legs kept per twin (oldest dropped first)
MAX_SAMPLES = 6000     # hard cap per leg (~100 sim-minutes)
MIN_SAMPLES = 5        # shorter recordings are discarded as noise

# ---------------------------------------------------------------------------
# Channel catalogue - served to the UI so labels, units and provenance live in
# exactly one place.
# ---------------------------------------------------------------------------
CHANNELS = [
    # name,        label,                    unit,   source,    group
    ("gs_kt",      "Ground speed",           "kt",   "sim",     "speed"),
    ("ias_kt",     "Indicated airspeed",     "kt",   "derived", "speed"),
    ("tas_kt",     "True airspeed",          "kt",   "derived", "speed"),
    ("mach",       "Mach",                   "",     "derived", "speed"),
    ("alt_ft",     "Altitude (AGL)",         "ft",   "sim",     "path"),
    ("vs_fpm",     "Vertical speed",         "fpm",  "derived", "path"),
    ("hdg",        "Heading",                "deg",  "sim",     "path"),
    ("x_rwy_m",    "Distance along runway",  "m",    "derived", "path"),
    ("xtk_m",      "Cross-track offset",     "m",    "derived", "path"),
    ("dist_m",     "Distance travelled",     "m",    "derived", "path"),
    ("pitch",      "Pitch",                  "deg",  "sim",     "attitude"),
    ("roll",       "Bank angle",             "deg",  "sim",     "attitude"),
    ("turn_rate",  "Turn rate",              "deg/s", "derived", "attitude"),
    ("accel_g",    "Longitudinal accel.",    "g",    "derived", "loads"),
    ("lat_g",      "Lateral accel.",         "g",    "derived", "loads"),
    ("g_vert",     "Vertical load factor",   "g",    "model",   "loads"),
    ("gs_dev",     "Glideslope deviation",   "dots", "derived", "approach"),
    ("loc_dev",    "Localiser deviation",    "dots", "derived", "approach"),
    ("headwind_kt", "Headwind component",    "kt",   "derived", "wind"),
    ("crosswind_kt", "Crosswind component",  "kt",   "derived", "wind"),
    ("thrust_pct", "Thrust setting",         "%",    "model",   "engines"),
    ("n1_1",       "Engine 1 N1",            "%",    "model",   "engines"),
    ("n1_2",       "Engine 2 N1",            "%",    "model",   "engines"),
    ("egt_c",      "Exhaust gas temp.",      "C",    "model",   "engines"),
    ("ff_kg_h",    "Fuel flow (total)",      "kg/h", "model",   "fuel"),
    ("fuel_kg",    "Fuel on board",          "kg",   "model",   "fuel"),
    ("fuel_used_kg", "Fuel burned (leg)",    "kg",   "model",   "fuel"),
    ("weight_kg",  "Gross weight",           "kg",   "model",   "fuel"),
    ("flaps_pct",  "Flap setting",           "%",    "model",   "config"),
    ("gear",       "Landing gear (1=down)",  "",     "model",   "config"),
    ("spoilers_pct", "Ground spoilers",      "%",    "model",   "config"),
    ("reverse",    "Thrust reverser (1=on)", "",     "model",   "config"),
    ("brake_pct",  "Wheel braking",          "%",    "model",   "brakes"),
    ("brake_temp_c", "Brake temperature",    "C",    "model",   "brakes"),
    ("risk",       "Flight risk score",      "",     "sim",     "risk"),
]

# ---------------------------------------------------------------------------
# Per-type engineering profile used only by the modelled channels. Figures are
# representative (public order-of-magnitude values), not manual data.
# ---------------------------------------------------------------------------
_P = lambda **k: k  # noqa: E731
TYPE_PROFILE = {
    "A20N": _P(oew=44300, mtow=79000, engines=2, burn_km=2.5, ff_to=3900, egt_to=880, n1_idle=22, n1_to=100, cruise_kmh=830, prop=False),
    "A321": _P(oew=50000, mtow=97000, engines=2, burn_km=3.1, ff_to=4700, egt_to=890, n1_idle=22, n1_to=100, cruise_kmh=830, prop=False),
    "B738": _P(oew=41400, mtow=79000, engines=2, burn_km=3.0, ff_to=3700, egt_to=900, n1_idle=22, n1_to=100, cruise_kmh=830, prop=False),
    "B38M": _P(oew=45100, mtow=82200, engines=2, burn_km=2.7, ff_to=3600, egt_to=880, n1_idle=22, n1_to=100, cruise_kmh=830, prop=False),
    "AT76": _P(oew=13500, mtow=23000, engines=2, burn_km=1.3, ff_to=520, egt_to=790, n1_idle=60, n1_to=100, cruise_kmh=510, prop=True),
    "Q400": _P(oew=17800, mtow=29260, engines=2, burn_km=1.9, ff_to=700, egt_to=800, n1_idle=60, n1_to=100, cruise_kmh=620, prop=True),
    "B78X": _P(oew=128800, mtow=254000, engines=2, burn_km=6.0, ff_to=9800, egt_to=900, n1_idle=20, n1_to=100, cruise_kmh=900, prop=False),
    "B77W": _P(oew=167800, mtow=351500, engines=2, burn_km=8.3, ff_to=12600, egt_to=950, n1_idle=20, n1_to=100, cruise_kmh=900, prop=False),
}
_DEFAULT_PROFILE = TYPE_PROFILE["A20N"]

# Lat/lng of the destinations the twin can send flights to (route distance only).
DEST_COORDS = {
    "VIDP": (28.5562, 77.1000), "VABB": (19.0887, 72.8679), "VOBL": (13.1979, 77.7063),
    "VOMM": (12.9941, 80.1709), "VOHS": (17.2403, 78.4294), "VECC": (22.6547, 88.4467),
    "VAAH": (23.0772, 72.6347), "VOGO": (15.3808, 73.8314), "VOCI": (10.1520, 76.4019),
    "VIJP": (26.8242, 75.8122), "VABO": (22.3362, 73.2263), "VAPO": (18.5821, 73.9197),
    "VASU": (21.1141, 72.7418), "VEGT": (26.1061, 91.5859),
}

# Sim statuses grouped by what the aircraft is physically doing.
AIRBORNE_ARR = {"inbound", "holding", "approach", "final", "go_around"}
ON_RUNWAY_ARR = {"landing_rollout"}
GROUND_STATUSES = {"pushback", "taxi_out", "hold_short", "lineup", "takeoff_roll",
                   "landing_rollout", "runway_vacate", "taxi_in", "turnaround", "parked", "scheduled"}


# ---------------------------------------------------------------------------
# Deterministic RNG shared with the frontend (ui/src/lib/flightDetails.js), so
# the passenger count / registration the telemetry page shows is the one the
# flight-detail panel shows. FNV-1a seed + mulberry32, same call order.
# ---------------------------------------------------------------------------
def _hash_seed(s: str) -> int:
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _mulberry32(seed: int):
    a = seed & 0xFFFFFFFF

    def nxt():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = ((t ^ (t >> 15)) * (1 | t)) & 0xFFFFFFFF
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF)) ^ t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return nxt


def cabin_details(flight_id: str, seats: int) -> dict:
    """Same numbers buildFlightDetails() derives in the browser."""
    rng = _mulberry32(_hash_seed(flight_id))
    airline = flight_id.split("-")[0]
    number = 100 + int(rng() * 899)
    load_factor = 0.62 + rng() * 0.33
    pax = max(4, round((seats or 150) * load_factor))
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    reg = "VT-" + "".join(letters[int(rng() * 26)] for _ in range(3))
    return {"flight_number": f"{airline} {number}", "load_factor": load_factor,
            "pax": pax, "registration": reg}


def _gc_km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------
# A recorded leg
# ---------------------------------------------------------------------------
COLS = ("t", "lat", "lng", "alt", "gs", "hdg", "pitch", "roll", "status",
        "wind_kt", "wind_dir", "risk")


class Leg:
    __slots__ = ("id", "fid", "direction", "meta", "cols", "start_t", "end_t",
                 "outcome", "_cache", "_last_status", "_ga_active")

    def __init__(self, leg_id, fid, direction, meta, start_t):
        self.id = leg_id
        self.fid = fid
        self.direction = direction
        self.meta = meta
        self.cols = {c: [] for c in COLS}
        self.start_t = start_t
        self.end_t = None
        self.outcome = None          # None while live
        self._cache = None
        self._last_status = None
        self._ga_active = False

    @property
    def live(self):
        return self.outcome is None

    def __len__(self):
        return len(self.cols["t"])

    def summary(self):
        n = len(self)
        last_t = self.cols["t"][-1] if n else self.start_t
        return {
            "id": self.id, "flight": self.fid, "direction": self.direction,
            "type": self.meta["type"], "type_name": self.meta["type_name"],
            "wake": self.meta["wake"], "airline": self.meta["airline"],
            "flight_number": self.meta["flight_number"],
            "other_airport": self.meta["other_airport"],
            "runway": self.meta["runway"], "runway_name": self.meta["runway_name"],
            "stand": self.meta["stand"], "start_t": round(self.start_t, 1),
            "end_t": round(self.end_t if self.end_t is not None else last_t, 1),
            "duration_s": round((self.end_t if self.end_t is not None else last_t) - self.start_t, 1),
            "outcome": self.outcome or "live", "live": self.live,
            "go_arounds": self.meta["go_arounds"], "hold_s": round(self.meta["hold_s"], 1),
            "conditions": sorted(self.meta["conditions"]), "n": n,
        }


class TelemetryRecorder:
    """Samples every flight of one Aerodrome and keeps the per-leg logs."""

    def __init__(self, env, sim):
        self.env = env
        self.sim = sim
        self.active: dict[str, Leg] = {}
        self.done: "OrderedDict[str, Leg]" = OrderedDict()
        env.process(self._run())

    # -- sampling ----------------------------------------------------------
    def _run(self):
        while True:
            yield self.env.timeout(SAMPLE_DT)
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - recording must never stop the sim
                logger.exception("telemetry tick failed")

    def _tick(self):
        sim = self.sim
        now = self.env.now
        seen = set()
        for fid, f in list(sim.flights.items()):
            d = f.get("direction")
            st = f.get("status")
            finished = fid in sim._finished_at
            arr_key, dep_key = f"{fid}:ARR", f"{fid}:DEP"
            if d == "ARR":
                leg = self.active.get(arr_key) or self._open(f, "ARR", now)
                seen.add(arr_key)
                if not finished:       # _finish() zeroes speed; keep the last real sample
                    self._sample(leg, f, now)
                if finished:
                    self._close(leg, "diverted" if st == "diverted" else
                                "aborted" if st == "despawned" else "landed", now)
            elif d == "TURN" or (d == "DEP" and arr_key in self.active):
                leg = self.active.get(arr_key)
                if leg is not None:
                    self._close(leg, "landed", now)
            if d == "DEP":
                if st == "scheduled" and not finished:
                    continue
                if st == "scheduled" and finished and dep_key not in self.active:
                    continue
                leg = self.active.get(dep_key) or self._open(f, "DEP", now)
                seen.add(dep_key)
                if not finished:
                    self._sample(leg, f, now)
                if finished:
                    self._close(leg, "departed" if st == "airborne" else "cancelled", now)
        # Flights reaped from the sim while a leg was still open.
        for key in [k for k in self.active if k not in seen]:
            fid = key.split(":")[0]
            if fid not in sim.flights:
                self._close(self.active[key], "aborted", now)

    def _open(self, f, direction, now):
        sim = self.sim
        fid = f["id"]
        cab = cabin_details(fid, f.get("seats") or 150)
        ctl = f.get("_ctl")
        meta = {
            "type": f["type"], "type_name": f["type_name"], "wake": f["wake"],
            "category": f["category"], "seats": f.get("seats") or 150,
            "airline": fid.split("-")[0], "other_airport": f.get("other_airport"),
            "runway": f.get("runway"), "runway_name": f.get("runway_name"),
            "stand": f.get("stand_name"), "go_arounds": 0, "hold_s": 0.0,
            "conditions": set(), "exit_via": None,
            "temp_c": float(sim.weather.get("temperature_c", 31)),
            "qnh": sim.weather.get("qnh_hpa", 1013),
            "elevation_m": float(sim.layout.elevation_m),
            "icao": sim.layout.icao,
            **cab,
        }
        leg = Leg(f"{fid}:{direction}", fid, direction, meta, now)
        self.active[leg.id] = leg
        return leg

    def _sample(self, leg: Leg, f, now):
        if len(leg) >= MAX_SAMPLES:
            return
        sim = self.sim
        w = sim.weather
        c = leg.cols
        speed = f.get("speed", 0) or 0
        gs = f.get("_gs", speed)
        if abs(gs - speed) > 1.5:
            gs = speed                 # a hold zeroed `speed` after the last traverse step
        st = f["status"]
        c["t"].append(now)
        c["lat"].append(f["lat"])
        c["lng"].append(f["lng"])
        c["alt"].append(f.get("altitude", 0.0) or 0.0)
        c["gs"].append(float(gs))
        c["hdg"].append(f.get("heading", 0.0) or 0.0)
        c["pitch"].append(f.get("pitch", 0.0) or 0.0)
        c["roll"].append(f.get("roll", 0.0) or 0.0)
        c["status"].append(st)
        c["wind_kt"].append(float(w.get("wind_kt", 0)))
        c["wind_dir"].append(float(w.get("wind_dir_deg", 0)))
        c["risk"].append(float(f.get("risk", 0.0) or 0.0))
        m = leg.meta
        if st == "go_around" and leg._last_status != "go_around":
            m["go_arounds"] += 1
        if st == "holding":
            m["hold_s"] += SAMPLE_DT
        leg._last_status = st
        m["runway"] = f.get("runway") or m["runway"]
        m["runway_name"] = f.get("runway_name") or m["runway_name"]
        if f.get("exit_via"):
            m["exit_via"] = f["exit_via"]
        if f.get("stand_name"):
            m["stand"] = f["stand_name"]
        cond = w.get("condition")
        if cond and cond != "CLEAR":
            m["conditions"].add(cond)
        if sim.ground_stop:
            m["conditions"].add("GROUND STOP")
        ctl = f.get("_ctl")
        if ctl is not None and ctl.is_closed():
            m["conditions"].add("RUNWAY CLOSED")
        if f.get("emergency"):
            m["conditions"].add("EMERGENCY")
        leg._cache = None

    def _close(self, leg: Leg, outcome, now):
        self.active.pop(leg.id, None)
        if len(leg) < MIN_SAMPLES:
            return
        leg.outcome = outcome
        leg.end_t = leg.cols["t"][-1]
        leg._cache = None
        self.done[leg.id] = leg
        while len(self.done) > MAX_LEGS:
            self.done.popitem(last=False)

    # -- queries -----------------------------------------------------------
    def get(self, leg_id):
        return self.active.get(leg_id) or self.done.get(leg_id)

    def list(self, direction=None, state="all"):
        legs = list(self.done.values()) + list(self.active.values())
        out = []
        for leg in legs:
            if len(leg) < MIN_SAMPLES:
                continue
            if direction and leg.direction != direction:
                continue
            if state == "completed" and leg.live:
                continue
            if state == "live" and not leg.live:
                continue
            out.append(leg.summary())
        out.sort(key=lambda s: s["start_t"], reverse=True)
        return out

    def detail(self, leg_id, since=0):
        leg = self.get(leg_id)
        if leg is None or len(leg) < 2:
            return None
        return analyse(leg, self.sim.layout, since)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def _smooth(x, k=3):
    if len(x) < k:
        return x
    w = np.ones(k) / k
    num = np.convolve(np.nan_to_num(x), w, mode="same")
    den = np.convolve(np.ones(len(x)), w, mode="same")
    return num / den


def _clean(arr, nd=2):
    out = []
    for v in np.asarray(arr, dtype=float):
        out.append(None if not math.isfinite(v) else round(float(v), nd))
    return out


def _runway_end(layout, ident):
    for rwy in layout.runways:
        for e in rwy.ends:
            if e.ident == ident:
                return e, rwy
    rwy = layout.runways[0]
    return rwy.ends[0], rwy


def _isa(h_m, temp_c_surface, elev_m):
    """Density ratio and speed of sound at a height, ISA shape with the
    surface temperature the weather reports."""
    h = np.asarray(h_m, dtype=float)
    d_t = temp_c_surface - (15.0 - 0.0065 * elev_m)
    t_k = 288.15 - 0.0065 * h + d_t
    p_ratio = np.clip(1 - 2.25577e-5 * h, 0.2, 1.2) ** 5.25588
    sigma = p_ratio / (t_k / 288.15)
    a = 340.294 * np.sqrt(t_k / 288.15)
    return sigma, a


def _blend_handoffs(gs, alt_m, jump_kt=8.0, half=4):
    """Blend the speed steps the simulation makes between airborne manoeuvres.

    Each leg of a flight path (join, descend, final, go-around, ...) is driven
    by its own speed profile that starts from a fixed entry speed, so ground
    speed steps by 20-60 kt in a single tick where one leg hands over to the
    next. A real aircraft cannot do that, and unblended it would show up as
    spikes of several tenths of a g in the derived acceleration. The steps are
    replaced by a short linear ramp (about 2*half seconds); everything else,
    including all ground movement, is left exactly as simulated.
    """
    out = gs.copy()
    n = len(gs)
    for i in range(1, n):
        if abs(gs[i] - gs[i - 1]) > jump_kt and alt_m[i] > 3.0 and alt_m[i - 1] > 3.0:
            a, b = max(0, i - 1 - half), min(n - 1, i + half)
            for k in range(a, b + 1):
                f = (k - a) / max(1, b - a)
                out[k] = gs[a] + (gs[b] - gs[a]) * f
    return out


def analyse(leg: Leg, layout, since=0):
    full = _analyse_full(leg, layout)
    if since <= 0:
        return full
    s = max(0, min(int(since), full["n"]))
    out = dict(full)
    out["since"] = s
    out["t"] = full["t"][s:]
    out["lat"] = full["lat"][s:]
    out["lng"] = full["lng"][s:]
    out["phase"] = full["phase"][s:]
    out["ch"] = {k: v[s:] for k, v in full["ch"].items()}
    return out


def _analyse_full(leg: Leg, layout):
    n = len(leg)
    if leg._cache and leg._cache[0] == n and leg._cache[1] == leg.outcome:
        return leg._cache[2]
    res = _compute(leg, layout)
    leg._cache = (n, leg.outcome, res)
    return res


def _compute(leg: Leg, layout):
    c = leg.cols
    m = leg.meta
    arr = leg.direction == "ARR"
    ac = fleet.get(m["type"])
    prof = TYPE_PROFILE.get(m["type"], _DEFAULT_PROFILE)
    rng = np.random.default_rng(zlib.crc32(leg.id.encode()))

    t_abs = np.array(c["t"], dtype=float)
    t = t_abs - t_abs[0]
    n = len(t)
    lat = np.array(c["lat"]); lng = np.array(c["lng"])
    alt_m = np.array(c["alt"], dtype=float)
    gs = np.array(c["gs"], dtype=float)
    hdg = np.array(c["hdg"], dtype=float)
    pitch = np.array(c["pitch"], dtype=float)
    roll = np.array(c["roll"], dtype=float)
    status = list(c["status"])
    wind_kt = np.array(c["wind_kt"]); wind_dir = np.array(c["wind_dir"])
    risk = np.array(c["risk"])
    dt = np.gradient(t) if n > 1 else np.ones(1)
    dt = np.where(dt <= 0, 1.0, dt)
    gs = _blend_handoffs(gs, alt_m)
    gs_ms = gs * KT

    st_arr = np.array(status)
    def is_(*names):
        return np.isin(st_arr, names)

    # ---- geometry relative to the runway end this leg used ---------------
    end, rwy = _runway_end(layout, m["runway"])
    lat0, lng0 = end.threshold
    hd = math.radians(end.heading_deg)
    m_lng = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    dx = (lng - lng0) * m_lng
    dy = (lat - lat0) * M_PER_DEG_LAT
    along = dx * math.sin(hd) + dy * math.cos(hd)
    xtk = dx * math.cos(hd) - dy * math.sin(hd)

    # distance travelled along the actual path
    step = np.zeros(n)
    if n > 1:
        step[1:] = np.hypot(np.diff(lng) * m_lng, np.diff(lat) * M_PER_DEG_LAT)
    dist = np.cumsum(step)

    # ---- key indices -----------------------------------------------------
    def first(mask):
        idx = np.flatnonzero(mask)
        return int(idx[0]) if idx.size else None

    i_td = first(is_("landing_rollout")) if arr else None
    # First sample after touchdown that is no longer on the runway: taxiing, or
    # holding short of a second runway the exit taxiway crosses.
    i_clear = (first(is_("taxi_in", "hold_short") & (np.arange(n) > (i_td or 0))) if arr else None)
    i_release = first(is_("takeoff_roll")) if not arr else None
    i_liftoff = None
    if not arr:
        base = i_release if i_release is not None else 0
        after = np.flatnonzero((alt_m > 0.3) & (np.arange(n) >= base))
        i_liftoff = int(after[0]) if after.size else None

    x_rwy = along.copy()
    if not arr and i_release is not None:
        x_rwy = along - along[i_release]

    # ---- wind and airspeed ----------------------------------------------
    rel = np.radians(wind_dir - hdg)
    headwind = wind_kt * np.cos(rel)
    crosswind = wind_kt * np.sin(rel)           # + = from the right
    air_kt = np.maximum(0.0, gs + headwind * np.where(alt_m > 0.3, 1.0, 0.6))
    # Taxiing/hold: pitot reads roughly ground speed
    air_kt = np.where(is_("pushback", "taxi_out", "hold_short", "lineup", "taxi_in", "runway_vacate"),
                      gs, air_kt)
    msl = alt_m + m["elevation_m"]
    sigma, a_ms = _isa(msl, m["temp_c"], m["elevation_m"])
    tas_kt = air_kt
    ias_kt = tas_kt * np.sqrt(sigma)
    mach = tas_kt * KT / a_ms

    # ---- vertical speed / accelerations ---------------------------------
    vs_ms = _smooth(np.gradient(alt_m, t), 3) if n > 2 else np.zeros(n)
    vs_fpm = vs_ms / FPM
    vs_fpm = np.where(alt_m < 0.3, np.where(np.roll(alt_m, 1) > 0.3, vs_fpm, 0.0), vs_fpm)
    accel = _smooth(np.gradient(gs_ms, t), 3) / G if n > 2 else np.zeros(n)
    h_rad = np.unwrap(np.radians(hdg))
    turn = _smooth(np.gradient(h_rad, t), 3) if n > 2 else np.zeros(n)
    lat_g = np.clip(gs_ms * turn / G, -0.6, 0.6)
    turn_deg = np.degrees(turn)

    # ---- approach deviations (arrivals on the extended centreline) -------
    gs_dev = np.full(n, np.nan); loc_dev = np.full(n, np.nan)
    if arr:
        ok = is_("approach", "final") & (along < -250) & (along > -12000) & (np.abs(xtk) < 2500) & (alt_m > 3)
        ang = np.degrees(np.arctan2(alt_m, np.maximum(1.0, -along)))
        gs_dev = np.where(ok, (ang - 3.0) / 0.35, np.nan)
        loc_ang = np.degrees(np.arctan2(xtk, np.maximum(1.0, -along + rwy.length_m)))
        loc_dev = np.where(ok, loc_ang / 0.5, np.nan)

    # ---- vertical load factor (model): vertical accel + touchdown spike --
    g_vert = 1.0 + _smooth(np.gradient(vs_ms, t), 3) / G if n > 2 else np.ones(n)
    ground_noise = rng.normal(0, 1, n) * 0.012 * np.clip(gs / 40.0, 0, 1)
    g_vert = np.clip(g_vert + ground_noise, 0.6, 2.2)
    sink_td_fpm = None
    if arr and i_td is not None and i_td >= 2:
        # Descent rate over the last second before the wheels touch: the last
        # airborne sample is often already on the runway (0 ft), so the rate
        # is taken between it and the one before.
        k = i_td - 1
        sink_td_fpm = float(max(0.0, alt_m[k - 1] - alt_m[k]) / max(0.5, t[k] - t[k - 1]) / FPM)
        g_td = 1.05 + sink_td_fpm / 1100.0
        g_vert[i_td] = max(g_vert[i_td], g_td)
        if i_td + 1 < n:
            g_vert[i_td + 1] = max(g_vert[i_td + 1], 1.0 + (g_td - 1.0) * 0.45)

    # ---- weights and fuel (model) ---------------------------------------
    home = (layout.runways[0].ends[0].threshold)
    other = DEST_COORDS.get(m["other_airport"], home)
    trip_km = max(150.0, _gc_km(home, other) * 1.05)
    payload = m["pax"] * 100.0 + (0.0 if prof["prop"] else m["pax"] * 12.0)
    reserve = prof["burn_km"] * (0.75 * prof["cruise_kmh"] + 250.0)
    zfw = prof["oew"] + payload
    block = trip_km * prof["burn_km"] + reserve
    block = min(block, prof["mtow"] - zfw)
    landing_fuel = reserve + 0.05 * trip_km * prof["burn_km"]
    landing_fuel = min(landing_fuel, block)

    # ---- thrust (model) --------------------------------------------------
    idle = 0.21
    thr = np.full(n, idle)
    to_thr = 0.86 + 0.14 * min(1.0, (zfw + block) / prof["mtow"])
    for i in range(n):
        s = status[i]
        if s in ("pushback", "scheduled"):
            thr[i] = 0.19
        elif s in ("taxi_out", "taxi_in", "runway_vacate", "lineup", "hold_short"):
            thr[i] = idle + 0.07 * min(1.0, gs[i] / 25.0) + 0.9 * max(0.0, accel[i])
        elif s == "takeoff_roll":
            thr[i] = to_thr
        elif s == "climb":
            thr[i] = (to_thr + 0.02) - 0.14 * min(1.0, alt_m[i] / 1500.0)
        elif s in ("inbound", "holding"):
            thr[i] = 0.40
        elif s == "approach":
            thr[i] = 0.35
        elif s == "final":
            thr[i] = 0.30 if alt_m[i] > 40 else 0.24
        elif s == "go_around":
            thr[i] = 0.96
        elif s == "diverted":
            thr[i] = 0.75
        elif s == "landing_rollout":
            thr[i] = idle
    reverse = np.zeros(n)
    if arr and i_td is not None:
        for i in range(i_td, n):
            if status[i] != "landing_rollout" or gs[i] < 70:
                break
            reverse[i] = 1.0
            thr[i] = 0.55
    # first-order spool lag
    tau = 2.5
    for i in range(1, n):
        k = min(1.0, dt[i] / tau)
        thr[i] = thr[i - 1] + (thr[i] - thr[i - 1]) * k
    thr = np.clip(thr, 0.15, 1.0)
    jit = rng.normal(0, 0.002, (2, n))
    n1_span = prof["n1_to"] - prof["n1_idle"]
    # N1 rises steeply off idle and flattens towards take-off power, unlike
    # thrust, which is closer to linear in the upper range.
    frac1 = np.clip((thr + 0.003 - 0.18) / 0.82, 0, 1)
    frac2 = np.clip((thr - 0.003 - 0.18) / 0.82, 0, 1)
    n1_1 = prof["n1_idle"] + n1_span * frac1 ** 0.55 + jit[0] * 100
    n1_2 = prof["n1_idle"] + n1_span * frac2 ** 0.55 + jit[1] * 100
    egt = 340 + (prof["egt_to"] - 340) * np.clip((thr - 0.15) / 0.85, 0, 1) ** 0.8 + rng.normal(0, 1.2, n)
    ff_idle = 0.10 * prof["ff_to"]
    ff = prof["engines"] * (ff_idle + (prof["ff_to"] - ff_idle) * thr ** 1.5)
    used = np.cumsum(ff / 3600.0 * dt)
    if arr:
        approach_est = prof["burn_km"] * 60.0
        fuel0 = landing_fuel + approach_est
    else:
        fuel0 = block
    fuel = np.maximum(0.0, fuel0 - used)
    weight = zfw + fuel

    # ---- configuration (model) ------------------------------------------
    vapp = ac.approach_speed_kt
    ladder = [0.0, 50.0, 100.0] if prof["prop"] else [0.0, 20.0, 40.0, 60.0, 100.0]
    flaps = np.zeros(n); gear = np.zeros(n); spoil = np.zeros(n)
    if arr:
        cur = 0.0; ga_t = None
        for i in range(n):
            s = status[i]
            if s == "go_around":
                ga_t = t[i] if ga_t is None else ga_t
            else:
                ga_t = None
            over = ias_kt[i] - vapp
            if s in ("approach", "final", "landing_rollout") or (s in ("inbound", "holding") and alt_m[i] < 700):
                if prof["prop"]:
                    want = 100.0 if over < 14 else 50.0 if over < 45 else 0.0
                else:
                    want = (100.0 if over < 14 else 60.0 if over < 26 else
                            40.0 if over < 42 else 20.0 if over < 62 else 0.0)
                cur = max(cur, want)
            elif s == "go_around":
                cur = min(cur, 50.0 if prof["prop"] else 40.0)
            elif s in ("taxi_in", "runway_vacate") and i_td is not None and t[i] - t[i_td] > 25:
                cur = 0.0
            flaps[i] = cur
            if s in ("final", "landing_rollout", "runway_vacate", "taxi_in"):
                gear[i] = 1.0
            elif s == "go_around":
                gear[i] = 1.0 if (t[i] - ga_t) < 6 else 0.0
            elif s == "approach" and along[i] > -9000 and alt_m[i] < 500:
                gear[i] = 1.0
        if i_td is not None:
            for i in range(i_td, n):
                if status[i] != "landing_rollout" or gs[i] < 60:
                    break
                ramp = min(1.0, (t[i] - t[i_td]) / 2.0)
                spoil[i] = 100.0 * ramp
    else:
        to_flap = ladder[1] if prof["prop"] else ladder[2]
        for i in range(n):
            s = status[i]
            if s in ("taxi_out", "hold_short", "lineup", "takeoff_roll"):
                flaps[i] = to_flap
                gear[i] = 1.0
            elif s == "pushback" or s == "scheduled":
                flaps[i] = 0.0
                gear[i] = 1.0
            elif s == "climb":
                a = alt_m[i]
                flaps[i] = to_flap if a < 450 else (to_flap * 0.5 if a < 750 else 0.0)
                gear[i] = 1.0 if (i_liftoff is not None and t[i] - t[i_liftoff] < 3.0) else 0.0

    # ---- braking (model) -------------------------------------------------
    decel = np.maximum(0.0, -accel * G)
    aero = np.where(spoil > 0, 0.35, 0.10)
    rev_dec = np.where(reverse > 0, 0.9, 0.0)
    wheel_dec = np.where(gs > 1.0, np.maximum(0.0, decel - aero - rev_dec), decel * 0.5)
    on_gnd = alt_m < 0.3
    brake_pct = np.where(on_gnd, np.clip(wheel_dec / 3.0, 0, 1) * 100.0, 0.0)
    mass = weight
    t_amb = m["temp_c"]
    bt = np.zeros(n)
    bt[0] = t_amb + (40.0 if arr else 70.0)
    cap = 9.5 * mass
    for i in range(1, n):
        heat = mass[i] * wheel_dec[i] * gs_ms[i] * dt[i] / max(1.0, cap[i]) if on_gnd[i] else 0.0
        cool = (bt[i - 1] - t_amb) * dt[i] / (700.0 if gs[i] < 5 else 420.0)
        bt[i] = bt[i - 1] + heat - cool

    # ---- events ----------------------------------------------------------
    events = []
    def ev(name, label, idx):
        if idx is not None and 0 <= idx < n:
            events.append({"name": name, "label": label, "i": int(idx), "t": round(float(t[idx]), 1),
                           "x_rwy": round(float(x_rwy[idx]), 1)})
    ev("start", "Leg start", 0)
    gate1 = gate5 = None
    if arr:
        ga = [i for i in range(1, n) if status[i] == "go_around" and status[i - 1] != "go_around"]
        for k, i in enumerate(ga):
            ev("go_around", f"Go-around {k + 1}", i)
        ev("final", "Established on final", first(is_("final")))
        for name, label, h_m in (("gate_1000", "1000 ft gate", 304.8), ("gate_500", "500 ft gate", 152.4)):
            cand = [i for i in range(1, n) if status[i] in ("final", "approach") and alt_m[i - 1] > h_m >= alt_m[i]]
            if cand:
                ev(name, label, cand[-1])
                if name == "gate_1000":
                    gate1 = cand[-1]
                else:
                    gate5 = cand[-1]
        ev("touchdown", "Touchdown", i_td)
        ev("vacating", "Leaving runway", first(is_("runway_vacate")))
        ev("runway_clear", "Runway vacated", i_clear)
        ev("on_stand", "Stopped on stand", n - 1 if leg.outcome == "landed" else None)
    else:
        ev("pushback", "Pushback", first(is_("pushback")))
        ev("taxi", "Taxi out", first(is_("taxi_out")))
        ev("hold_short", "Hold short", first(is_("hold_short")))
        ev("lineup", "Line up", first(is_("lineup")))
        ev("brake_release", "Brake release", i_release)
        if i_release is not None:
            vr = ac.v_rotate_kt
            i_v1 = first((gs >= vr - 3) & (np.arange(n) >= i_release))
            i_vr = first((gs >= vr - 0.5) & (np.arange(n) >= i_release))
            ev("v1", f"V1 (~{vr - 3:.0f} kt)", i_v1)
            ev("vr", f"Rotate ({vr:.0f} kt)", i_vr)
        ev("liftoff", "Lift-off", i_liftoff)
        if i_liftoff is not None:
            g_up = first((gear == 0) & (np.arange(n) >= i_liftoff))
            ev("gear_up", "Gear up", g_up)
            k1000 = first((alt_m * FT >= 1000) & (np.arange(n) >= i_liftoff))
            ev("alt_1000", "1000 ft", k1000)
        if leg.outcome == "departed":
            ev("left_area", "Left terminal area", n - 1)

    # ---- KPIs ------------------------------------------------------------
    kpis = []
    def kpi(key, label, unit, value, better=None, nd=1, note=None):
        if isinstance(value, str):
            v = value
        else:
            v = None if value is None or not math.isfinite(float(value)) else round(float(value), nd)
        kpis.append({"key": key, "label": label, "unit": unit, "value": v, "better": better, "note": note})

    def time_in(*names):
        return float(np.sum(dt[is_(*names)]))

    def path_len(i0, i1):
        if i0 is None or i1 is None or i1 <= i0:
            return None
        return float(dist[i1] - dist[i0])

    burn = float(used[-1]) if n else 0.0
    stable = {}
    if arr:
        i_exit = i_clear
        i_vac = first(is_("runway_vacate"))
        i_end_roll = i_vac if i_vac is not None else i_exit
        kpi("duration", "Leg duration", "s", t[-1], "low", 0)
        kpi("approach_time", "Time from first contact to touchdown", "s", t[i_td] if i_td is not None else None, "low", 0)
        kpi("holding", "Time in holding pattern", "s", time_in("holding"), "low", 0)
        kpi("go_arounds", "Go-arounds", "", m["go_arounds"], "low", 0)
        kpi("vapp", "Reference approach speed", "kt", vapp, None, 0)
        kpi("td_gs", "Touchdown ground speed", "kt", gs[i_td] if i_td is not None else None, None, 0)
        kpi("td_ias", "Touchdown indicated airspeed", "kt", ias_kt[i_td] if i_td is not None else None, None, 0)
        kpi("td_over_vref", "Touchdown IAS above Vapp", "kt", (ias_kt[i_td] - vapp) if i_td is not None else None, "low", 0)
        kpi("td_sink", "Touchdown sink rate", "fpm", sink_td_fpm, "low", 0)
        kpi("td_g", "Touchdown load factor", "g", g_vert[i_td] if i_td is not None else None, "low", 2,
            note="modelled from sink rate")
        kpi("rollout", "Rollout distance", "m", path_len(i_td, i_end_roll), "low", 0)
        if i_td is not None and i_exit is not None:
            kpi("rot", "Runway occupancy time", "s", t[i_exit] - t[i_td], "low", 0)
            i_dec = i_end_roll if i_end_roll is not None else i_exit
            kpi("decel", "Mean rollout deceleration", "m/s2",
                (gs[i_td] - gs[i_dec]) * KT / max(1.0, t[i_dec] - t[i_td]), None, 2)
            kpi("taxi_in", "Taxi-in time", "s", t[-1] - t[i_exit], "low", 0)
        kpi("peak_brake", "Peak brake temperature", "C", bt.max(), "low", 0, note="modelled")
        kpi("fuel_burn", "Fuel burned this leg", "kg", burn, "low", 0, note="modelled")
        kpi("land_weight", "Landing weight", "kg", weight[i_td] if i_td is not None else None, None, 0, note="modelled")
        for name, gi, label in (("stable_1000", gate1, "Stabilised at 1000 ft"), ("stable_500", gate5, "Stabilised at 500 ft")):
            if gi is None:
                continue
            fails = []
            if not (vapp - 5 <= ias_kt[gi] <= vapp + 20):
                fails.append(f"speed {ias_kt[gi]:.0f} kt vs Vapp {vapp:.0f}")
            if vs_fpm[gi] < -1000:
                fails.append(f"sink {abs(vs_fpm[gi]):.0f} fpm")
            if np.isfinite(gs_dev[gi]) and abs(gs_dev[gi]) > 1.0:
                fails.append(f"glideslope {gs_dev[gi]:+.1f} dots")
            if np.isfinite(loc_dev[gi]) and abs(loc_dev[gi]) > 1.0:
                fails.append(f"localiser {loc_dev[gi]:+.1f} dots")
            if gear[gi] < 1:
                fails.append("gear not down")
            if flaps[gi] < ladder[-1]:
                fails.append("not fully configured")
            stable[name] = not fails
            kpi(name, label, "", "YES" if not fails else "NO", None, 0, note="; ".join(fails) or None)
    else:
        i_hold = first(is_("hold_short"))
        i_line = first(is_("lineup"))
        i_taxi = first(is_("taxi_out"))
        i_push = first(is_("pushback"))
        kpi("duration", "Leg duration", "s", t[-1], "low", 0)
        kpi("pushback", "Pushback time", "s", time_in("pushback"), "low", 0)
        i_first_stop = i_hold if i_hold is not None else i_line
        if i_taxi is not None and i_first_stop is not None:
            kpi("taxi_out", "Taxi-out time (to hold point)", "s", t[i_first_stop] - t[i_taxi], "low", 0)
        kpi("hold_short", "Time holding short", "s", time_in("hold_short"), "low", 0)
        kpi("lineup", "Time lined up", "s", time_in("lineup"), "low", 0)
        if i_release is not None:
            kpi("ground_time", "Pushback to brake release", "s", t[i_release] - t[0], "low", 0)
        if i_release is not None and i_liftoff is not None:
            kpi("roll_time", "Take-off roll time", "s", t[i_liftoff] - t[i_release], "low", 0)
            kpi("roll_dist", "Take-off roll distance", "m", path_len(i_release, i_liftoff), "low", 0)
            kpi("lo_speed", "Lift-off ground speed", "kt", gs[i_liftoff], None, 0)
            kpi("accel_mean", "Mean take-off acceleration", "m/s2",
                (gs[i_liftoff] - gs[i_release]) * KT / max(1.0, t[i_liftoff] - t[i_release]), None, 2)
            j = min(n - 1, i_liftoff + 30)
            if j > i_liftoff:
                kpi("climb_rate", "Mean climb rate (first 30 s)", "fpm",
                    (alt_m[j] - alt_m[i_liftoff]) / max(1.0, t[j] - t[i_liftoff]) / FPM, "high", 0)
            k1000 = first((alt_m * FT >= 1000) & (np.arange(n) >= i_liftoff))
            if k1000 is not None:
                kpi("t_1000", "Lift-off to 1000 ft", "s", t[k1000] - t[i_liftoff], "low", 0)
            kpi("runway_used", "Runway used before lift-off", "m", float(x_rwy[i_liftoff] - x_rwy[i_release]), "low", 0)
        kpi("max_alt", "Highest altitude recorded", "ft", alt_m.max() * FT, None, 0)
        kpi("to_weight", "Take-off weight", "kg", weight[0], None, 0, note="modelled")
        kpi("fuel_burn", "Fuel burned this leg", "kg", burn, "low", 0, note="modelled")

    refs = {"vapp": vapp} if arr else {"vr": ac.v_rotate_kt, "v2": ac.v2_kt, "climb": ac.climb_speed_kt}
    phases = []
    pidx = {}
    for s in status:
        if s not in pidx:
            pidx[s] = len(phases)
            phases.append(s)

    meta_out = {k: (sorted(v) if isinstance(v, set) else v) for k, v in m.items()}
    meta_out.update({
        "trip_km": round(trip_km), "payload_kg": round(payload), "block_fuel_kg": round(block),
        "oew_kg": prof["oew"], "mtow_kg": prof["mtow"], "engines": prof["engines"],
        "prop": prof["prop"], "refs": refs, "runway_length_m": round(rwy.length_m),
        "runway_heading": round(end.heading_deg, 1),
        "runway_threshold": [lat0, lng0],
    })

    ch = {
        "gs_kt": gs, "ias_kt": ias_kt, "tas_kt": tas_kt, "mach": mach,
        "alt_ft": alt_m * FT, "vs_fpm": vs_fpm, "hdg": hdg, "x_rwy_m": x_rwy, "xtk_m": xtk, "dist_m": dist,
        "pitch": pitch, "roll": roll, "turn_rate": turn_deg, "accel_g": accel, "lat_g": lat_g,
        "g_vert": g_vert, "gs_dev": gs_dev, "loc_dev": loc_dev,
        "headwind_kt": headwind, "crosswind_kt": crosswind,
        "thrust_pct": thr * 100.0, "n1_1": n1_1, "n1_2": n1_2, "egt_c": egt,
        "ff_kg_h": ff, "fuel_kg": fuel, "fuel_used_kg": used, "weight_kg": weight,
        "flaps_pct": flaps, "gear": gear, "spoilers_pct": spoil, "reverse": reverse,
        "brake_pct": brake_pct, "brake_temp_c": bt, "risk": risk,
    }
    nd = {"mach": 3, "accel_g": 3, "lat_g": 3, "g_vert": 3, "gs_dev": 2, "loc_dev": 2, "risk": 3}
    return {
        "id": leg.id, "flight": leg.fid, "direction": leg.direction,
        "live": leg.live, "outcome": leg.outcome or "live", "n": n, "since": 0,
        "meta": meta_out, "t": _clean(t, 1),
        "lat": _clean(lat, 6), "lng": _clean(lng, 6),
        "phases": phases, "phase": [pidx[s] for s in status],
        "ch": {k: _clean(v, nd.get(k, 1)) for k, v in ch.items()},
        "events": events, "kpis": kpis,
    }
