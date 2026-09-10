# core/models/

This directory is intentionally empty in git (see `.gitignore` -
`core/models/*.pkl`). Drop the `.pkl` files produced by the notebooks in
`notebooks/` here to activate each ML module in the live twin:

| File                          | Produced by notebook                    | Module |
|--------------------------------|------------------------------------------|--------|
| `01_macro_forecast.pkl`        | `01_forecast_macro.ipynb`                 | Macro delay forecasting (Prophet) |
| `02_taxi_time.pkl`             | `02_taxitime_xgboost.ipynb`                | Taxi/ground-delay time (XGBoost) |
| `03_congestion_tier.pkl`       | `03_cluster_kmeans.ipynb`                  | Congestion risk tiering (K-Means) |
| `04_network_criticality.pkl`   | `04_graph_networkx.ipynb`                  | Delay propagation graph (NetworkX) |
| `07_weather_ground_stop.pkl`   | `07_weather_disruption.ipynb`              | Weather ground-stop classifier (RandomForest) |

You do **not** need any of these files to run the twin - `core/models.py`
falls back to statistically-reasonable synthetic predictions for any module
whose `.pkl` is missing, so the simulation is fully playable out of the box.
As you train and drop in real artifacts, call `POST /api/models/reload` (or
just restart the server) to hot-swap that module from "fallback" to "online"
- check `GET /api/models` to see the live status of each one.
