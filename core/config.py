"""
AeroTwin Core Configuration
===========================
Tuning knobs only. Airport *geometry* no longer lives here - it moved to
`core/airports/`, where each aerodrome owns its own thresholds, taxi graph and
stands, so the twin can run Vadodara today and Delhi tomorrow without a single
constant in this file changing.

Time model
----------
The simulation clock is in real-world seconds. Every duration in the codebase -
a 35 minute turnaround, 90 seconds of wake separation, a 70 second taxi at 15
knots - is the real number, not a made-up one scaled to look good. Compression
happens in exactly one place: the server advances the clock `TIME_COMPRESSION`
seconds per wall-clock second. Set it to 1 and the twin runs in real time; the
default of 16 (4x the original 4.0) keeps a fast-paced twin - aircraft cover
real ground at four times the wall-clock rate - without distorting any of the
physics: every lock, separation check and wake-turbulence timer downstream
still operates in simulated seconds, which this knob never touches. Only
`asyncio.sleep(period)` in core/main.py's broadcast loop cares about wall time.
"""
import os

# ---------------------------------------------------------------------------
# Filesystem / trained model artifacts
# ---------------------------------------------------------------------------
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(CORE_DIR, "models")

MODEL_FILES = {
    "macro_forecast": "01_macro_forecast.pkl",            # Prophet
    "taxi_time": "02_taxi_time.pkl",                      # XGBoost
    "congestion_tier": "03_congestion_tier.pkl",          # KMeans (+ scaler)
    "network_criticality": "04_network_criticality.pkl",  # NetworkX centrality
    "weather_ground_stop": "07_weather_ground_stop.pkl",  # RandomForest
}

# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
TIME_COMPRESSION = float(os.getenv("AEROTWIN_TIME_COMPRESSION", "16.0"))
STREAM_HZ = float(os.getenv("AEROTWIN_STREAM_HZ", "15.0"))   # WebSocket frames/sec
STEP_DT = 0.25              # simulation-seconds per motion integration step

# Turnarounds are the one duration that is additionally shortened: a real 35
# minute turn would park an aircraft for nearly nine minutes of viewing time at
# the default compression, which is accurate and extremely boring.
TURNAROUND_SCALE = float(os.getenv("AEROTWIN_TURNAROUND_SCALE", "0.25"))

# ---------------------------------------------------------------------------
# Traffic generation
# ---------------------------------------------------------------------------
# Share of movements that are arrivals. The rest of the departures come from
# aircraft that arrived earlier and turned around, so the apron population is
# self-consistent rather than aircraft appearing from nowhere.
ARRIVAL_SHARE = 0.52
INITIAL_PARKED_FRACTION = 0.45   # how full the apron is at t=0
DESPAWN_AFTER_S = 90.0           # how long a finished flight lingers before cleanup

# ---------------------------------------------------------------------------
# Airspace geometry (relative to the landing threshold, metres)
# ---------------------------------------------------------------------------
INITIAL_APPROACH_FIX_M = 14000.0   # where arrivals appear on final
FINAL_APPROACH_FIX_M = 7400.0      # ~4 NM, glideslope intercept
DECISION_RANGE_M = 1500.0          # commit-or-go-around point
GLIDESLOPE_DEG = 3.0
HOLD_RADIUS_M = 2200.0             # airborne holding pattern radius
HOLD_ALTITUDE_M = 1050.0
MISSED_APPROACH_ALT_M = 900.0
DEPARTURE_FIX_M = 12000.0          # where departures leave the twin
DEPARTURE_ALT_M = 1800.0
MAX_APPROACH_ATTEMPTS = 2          # go-arounds before diverting

# ---------------------------------------------------------------------------
# Disruptions
# ---------------------------------------------------------------------------
DISRUPTION_MAX_MINUTES = 180
DISRUPTION_LOG_LIMIT = 25

CLEAR_WEATHER = {
    "visibility_m": 8000,
    "ceiling_ft": 3000,
    "wind_kt": 9,
    "wind_dir_deg": 250,
    "temperature_c": 31,
    "qnh_hpa": 1011,
    "condition": "CLEAR",
    "wet": False,
}

# Backwards compatibility: a couple of notebooks and the older README refer to
# these names. The authoritative geometry is core/airports/vabo.py.
AIRPORT_ICAO = "VABO"
AIRPORT_IATA = "BDQ"
AIRLINE_CODES = ["6E", "AI", "SG", "QP", "IX", "UK"]
