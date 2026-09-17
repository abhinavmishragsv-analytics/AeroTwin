"""
AeroTwin Core Configuration
Shared constants for the VABO digital twin: airport geometry, model paths,
and simulation tuning knobs. Centralised so core/main.py, core/twin_sim.py
and core/models.py never disagree on where things are.
"""
import os

# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(CORE_DIR, "models")

# Expected artifact filenames produced by notebooks/*.ipynb (see scripts/build_notebooks.py)
MODEL_FILES = {
    "macro_forecast": "01_macro_forecast.pkl",      # Prophet
    "taxi_time": "02_taxi_time.pkl",                # XGBoost
    "congestion_tier": "03_congestion_tier.pkl",    # KMeans (+ scaler)
    "network_criticality": "04_network_criticality.pkl",  # NetworkX centrality scores (dict)
    "weather_ground_stop": "07_weather_ground_stop.pkl",  # RandomForest
}

# ---------------------------------------------------------------------------
# VABO (Vadodara Airport) geometry - single source of truth
# ---------------------------------------------------------------------------
AIRPORT_ICAO = "VABO"
AIRPORT_IATA = "BDQ"

STAND_1 = (22.33550, 73.22600)
TAXIWAY_ENTRY = (22.33470, 73.22520)
RUNWAY_04_HOLD = (22.33020, 73.22010)
RUNWAY_04_THRESHOLD = (22.32970, 73.21930)
RUNWAY_22_THRESHOLD = (22.34560, 73.23610)
ATC_TOWER = (22.3362, 73.2250)

RUNWAY_HEADING_DEG = 44.0
RUNWAY_LENGTH_M = 2469

# ---------------------------------------------------------------------------
# Simulation tuning
# ---------------------------------------------------------------------------
BASE_FLIGHT_SPAWN_INTERVAL_S = 12.0     # seconds between new departures (sim time)
STREAM_HZ = 15.0                        # websocket push rate to the 3D frontend
DISRUPTION_MAX_MINUTES = 120            # sanity clamp for user-injected disruptions

AIRLINE_CODES = ["6E", "AI", "SG", "QP"]
