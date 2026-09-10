"""
AeroTwin Model Registry
========================
Loads the .pkl artifacts produced by the Colab notebooks (see notebooks/ and
scripts/build_notebooks.py) and exposes a single, simple prediction API to
the SimPy digital twin engine and the FastAPI layer.

Design principle: the twin must run *before* any model has been trained.
Every predict_* method below has a deterministic-but-randomised statistical
fallback so the simulation is fully playable out of the box. As soon as a
.pkl file is dropped into core/models/, that specific module "comes online"
and the corresponding fallback is bypassed - no restart-time crashes, no
required files.
"""
import glob
import logging
import math
import os
import random
import time

import joblib

from core.config import MODELS_DIR, MODEL_FILES

logger = logging.getLogger("aerotwin.models")
logging.basicConfig(level=logging.INFO)


class ModelRegistry:
    """Lazily loads whichever trained artifacts exist and reports status."""

    def __init__(self, models_dir: str = MODELS_DIR):
        self.models_dir = models_dir
        self.loaded = {}
        self.status = {}
        self._load_all()

    # ------------------------------------------------------------------
    def _path(self, key: str) -> str:
        return os.path.join(self.models_dir, MODEL_FILES[key])

    def _load_all(self):
        os.makedirs(self.models_dir, exist_ok=True)
        for key in MODEL_FILES:
            path = self._path(key)
            if os.path.exists(path):
                try:
                    self.loaded[key] = joblib.load(path)
                    self.status[key] = "online"
                    logger.info("Loaded model '%s' from %s", key, path)
                except Exception as exc:  # noqa: BLE001 - defensive, must never crash boot
                    self.loaded[key] = None
                    self.status[key] = f"error: {exc}"
                    logger.warning("Failed to load '%s': %s", key, exc)
            else:
                self.loaded[key] = None
                self.status[key] = "fallback (synthetic - drop .pkl in core/models/ to activate)"

    def reload(self):
        """Hot-reload models without restarting the server (e.g. after uploading new .pkl files)."""
        self._load_all()
        return self.status

    def summary(self):
        return {
            "models_dir": self.models_dir,
            "status": self.status,
        }

    # ------------------------------------------------------------------
    # Module 07: Weather Ground-Stop Classifier (RandomForest)
    # ------------------------------------------------------------------
    def predict_ground_stop_probability(self, visibility_m=8000, ceiling_ft=2500, wind_kt=8):
        model_bundle = self.loaded.get("weather_ground_stop")
        if model_bundle is not None:
            try:
                import pandas as pd

                clf = model_bundle["model"]
                cols = model_bundle.get("features", ["visibility_m", "ceiling_ft", "wind_kt"])
                features = pd.DataFrame([[visibility_m, ceiling_ft, wind_kt]], columns=cols)
                proba = clf.predict_proba(features)[0]
                return float(proba[1]) if len(proba) > 1 else float(proba[0])
            except Exception as exc:  # noqa: BLE001
                logger.warning("weather_ground_stop inference failed, using fallback: %s", exc)
        # Fallback heuristic: low visibility / low ceiling / high wind -> higher ground-stop risk
        vis_risk = max(0.0, 1.0 - visibility_m / 8000.0)
        ceil_risk = max(0.0, 1.0 - ceiling_ft / 3000.0)
        wind_risk = min(1.0, max(0.0, (wind_kt - 15) / 20.0))
        risk = min(0.97, 0.05 + 0.5 * vis_risk + 0.35 * ceil_risk + 0.2 * wind_risk)
        return round(risk, 3)

    # ------------------------------------------------------------------
    # Module 02: Taxi-Time Prediction (XGBoost)
    # ------------------------------------------------------------------
    def predict_taxi_time_seconds(self, queue_depth=0, hour_of_day=12, wind_kt=8):
        model_bundle = self.loaded.get("taxi_time")
        base_taxi_s = 8.0  # matches twin_sim's nominal taxi duration at 30 steps * 0.2s + holds
        if model_bundle is not None:
            try:
                import pandas as pd

                model = model_bundle["model"]
                cols = model_bundle.get("features", ["queue_depth", "hour_of_day", "wind_kt"])
                features = pd.DataFrame([[queue_depth, hour_of_day, wind_kt]], columns=cols)
                predicted_minutes = float(model.predict(features)[0])
                return max(4.0, predicted_minutes * 60.0 / 10.0)  # scaled into sim-time seconds
            except Exception as exc:  # noqa: BLE001
                logger.warning("taxi_time inference failed, using fallback: %s", exc)
        # Fallback: linearly scale with queue depth (more aircraft ahead -> longer taxi/hold)
        return base_taxi_s + queue_depth * 1.8

    # ------------------------------------------------------------------
    # Module 01: Macro Delay Forecasting (Prophet)
    # ------------------------------------------------------------------
    def predict_macro_delay_risk(self, hours_ahead=1):
        model_bundle = self.loaded.get("macro_forecast")
        if model_bundle is not None:
            try:
                kind = model_bundle.get("model_kind", "prophet")
                if kind == "prophet":
                    import pandas as pd  # local import - only needed on this path

                    model = model_bundle["model"]
                    future = model.make_future_dataframe(periods=int(hours_ahead), freq="h")
                    forecast = model.predict(future)
                    yhat = float(forecast.iloc[-1]["yhat"])
                else:
                    # seasonal_naive bundle: reconstruct the forecast from plain dicts,
                    # no custom class / no prophet import required at all.
                    import datetime as _dt

                    target = _dt.datetime.fromisoformat(str(model_bundle["last_date"])) + _dt.timedelta(
                        hours=hours_ahead
                    )
                    dow = target.weekday()
                    doy_bucket = target.timetuple().tm_yday // 14
                    yhat = (
                        model_bundle["overall_mean"]
                        + model_bundle["dow_effect"].get(dow, 0.0)
                        + model_bundle["season_effect"].get(doy_bucket, 0.0)
                    )
                # Normalise the forecasted avg delay minutes-per-flight into a 0-1 risk score
                return max(0.0, min(1.0, float(yhat) / 45.0))
            except Exception as exc:  # noqa: BLE001
                logger.warning("macro_forecast inference failed, using fallback: %s", exc)
        # Fallback: gentle sinusoidal daily pattern + noise, peaks at evening rush
        t = time.time() / 3600.0
        seasonal = 0.5 + 0.3 * math.sin((t % 24) / 24.0 * 2 * math.pi - math.pi / 2)
        return round(max(0.05, min(0.95, seasonal + random.uniform(-0.1, 0.1))), 3)

    # ------------------------------------------------------------------
    # Module 03: Congestion Risk Tiering (KMeans)
    # ------------------------------------------------------------------
    def congestion_tier(self, active_flights=0, avg_risk=0.3):
        model_bundle = self.loaded.get("congestion_tier")
        if model_bundle is not None:
            try:
                import pandas as pd

                kmeans = model_bundle["model"]
                scaler = model_bundle.get("scaler")
                features = pd.DataFrame([[active_flights, avg_risk]], columns=["active_flights", "avg_risk"])
                if scaler is not None:
                    features = scaler.transform(features)
                cluster = int(kmeans.predict(features)[0])
                tier_names = model_bundle.get("tier_names", {0: "LOW", 1: "MODERATE", 2: "HIGH"})
                return tier_names.get(cluster, f"CLUSTER_{cluster}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("congestion_tier inference failed, using fallback: %s", exc)
        # Fallback heuristic thresholds
        score = active_flights * 0.15 + avg_risk
        if score < 0.6:
            return "LOW"
        if score < 1.2:
            return "MODERATE"
        return "HIGH"

    # ------------------------------------------------------------------
    # Module 04: Delay Propagation Graph (NetworkX betweenness/PageRank)
    # ------------------------------------------------------------------
    def network_criticality(self, node="VABO"):
        model_bundle = self.loaded.get("network_criticality")
        if model_bundle is not None:
            try:
                scores = model_bundle["betweenness"]
                return float(scores.get(node, scores.get(node.upper(), 0.15)))
            except Exception as exc:  # noqa: BLE001
                logger.warning("network_criticality lookup failed, using fallback: %s", exc)
        return 0.15  # neutral fallback criticality score

    # ------------------------------------------------------------------
    def compute_flight_risk(self, hour_of_day=12, wind_kt=8, visibility_m=8000, ceiling_ft=2500, queue_depth=0):
        """Composite real-time risk score blending whichever modules are online.
        This is what core/twin_sim.py calls per spawned flight instead of pure random.uniform.
        """
        ground_stop_p = self.predict_ground_stop_probability(visibility_m, ceiling_ft, wind_kt)
        macro_risk = self.predict_macro_delay_risk()
        congestion_penalty = min(0.3, queue_depth * 0.05)
        composite = 0.45 * ground_stop_p + 0.35 * macro_risk + 0.20 * congestion_penalty
        composite += random.uniform(-0.05, 0.05)
        return round(max(0.02, min(0.98, composite)), 3)


# Module-level singleton - imported by core/main.py and core/twin_sim.py
registry = ModelRegistry()
