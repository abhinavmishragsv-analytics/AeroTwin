```
   AEROTWIN
```

> A true, bi-directional 3D digital twin of Vadodara Airport (VABO)
> status: RUNNABLE END-TO-END | domain: ITS x Aviation x Digital Twin

---

## About

AeroTwin is a closed-loop digital twin of ground operations at Vadodara
Airport (VABO) - not a flight tracker, not a 3D dashboard skinned over
static data. The "twin" is a live SimPy discrete-event simulation running
inside a FastAPI server: every aircraft moves through real gate -> pushback
-> taxi -> hold -> runway -> climb-out states, at exact WGS84 coordinates
for VABO's Runway 04/22 and Taxiway Alpha. The 3D frontend (React + Deck.GL
+ MapLibre satellite imagery) is strictly a visualization layer over that
live state.

It is **bi-directional**: inject a runway closure, a ground stop, fog, or a
crosswind event from the UI's ATC console, and the FastAPI layer mutates the
one running simulation - every in-progress aircraft reacts on its next
simulation step (holds short, queues, or climbs out late), and every
connected browser sees it within one WebSocket frame.

Five machine-learning modules - trained in Google Colab on public,
no-login-required datasets - feed real-time risk into that simulation:
delay forecasting, taxi-time prediction, congestion tiering, network
criticality, and weather ground-stop probability. None of them are required
to run the twin: `core/models.py` falls back to statistically-reasonable
synthetic predictions for any module you haven't trained yet, so the
simulation is fully playable from a fresh clone.

---

## Architecture

```
core/            FastAPI WebSocket server + SimPy simulation + ML inference
  main.py          - single persistent simulation, REST + WebSocket API
  twin_sim.py       - the SimPy engine: gate/pushback/taxi/hold/runway/climb
  models.py         - ML model registry (loads .pkl, falls back to synthetic)
  config.py         - VABO geometry + simulation constants, single source of truth
  models/           - drop trained .pkl artifacts here (gitignored)

ui/              Vite + React 19 + Deck.GL + MapLibre GL JS frontend
  src/App.jsx       - 3D scene, telemetry HUD, ATC disruption console

notebooks/       Google Colab training notebooks (generate via scripts/build_notebooks.py)
scripts/
  build_notebooks.py    - regenerates all notebooks/*.ipynb from scratch
  make_aircraft_glb.py  - procedurally generates a placeholder aircraft.glb
```

| module | function | technique | notebook |
|---|---|---|---|
| 01_forecast | macro delay-risk forecasting | Prophet (+ seasonal-naive fallback) | 01_forecast_macro.ipynb |
| 02_taxitime | taxi/ground-delay duration prediction | XGBoost | 02_taxitime_xgboost.ipynb |
| 03_cluster | congestion-risk tiering (LOW/MODERATE/HIGH) | K-Means | 03_cluster_kmeans.ipynb |
| 04_graph | route-network structural criticality | NetworkX (betweenness/PageRank) | 04_graph_networkx.ipynb |
| 05_twin | live simulation + disruption injection | SimPy (lives in core/twin_sim.py) | 05_twin_simpy.ipynb (eval harness only) |
| 07_weather | Cat III ground-stop probability | RandomForest | 07_weather_disruption.ipynb |

(Module 06 - predictive maintenance - is out of scope for this build.)

---

## Stack

```
core:  python 3.11+ | fastapi | uvicorn | simpy | pydantic | websockets
ml:    prophet | xgboost | scikit-learn | networkx | joblib | pandas
ui:    react 19 | vite | deck.gl | maplibre-gl | react-map-gl
```

---

## Data sources (all public, no login required)

| dataset | source | used by |
|---|---|---|
| BTS Airline Delay Cause (mirror) | github.com/YBI-Foundation/Dataset | Modules 01, 02 |
| OpenFlights airports/routes | github.com/jpatokal/openflights | Modules 03, 04 |
| IEM ASOS/METAR archive (IN__ASOS network) | mesonet.agron.iastate.edu | Module 07 |

Every notebook attempts the real, live download first and falls back to a
structurally-identical synthetic dataset if the source is ever unreachable
(rate-limited, moved, offline grading environment) - so every notebook
completes and produces a usable `.pkl` regardless of network conditions.

---

## Run

See the step-by-step guide provided alongside this repo for the full local +
Colab workflow. Short version:

```bash
# 1. Backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn core.main:app --reload --port 8000

# 2. Frontend (separate terminal)
cd ui
npm install
npm run dev
```

Then open the printed Vite URL (typically http://localhost:5173). The twin
runs immediately with synthetic ML fallbacks - train the notebooks in
`notebooks/` on Google Colab and drop the resulting `.pkl` files into
`core/models/` whenever you want real trained predictions instead.

---

## License

Code in this repository is released under the MIT License - see LICENSE.
Datasets referenced above are not covered by this license and remain under
their original terms (BTS/US Government open data, OpenFlights' attribution
terms, IEM's open METAR archive terms).

---

## Author

Abhinav Mishra
B.Tech, AI & Data Science - Gati Shakti Vishwavidyalaya (GSV)
Head, TechnoCrats - ex-DFCCIL, ex-Indian Railways (DRM Office, S&T)
