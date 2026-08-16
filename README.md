```
   ▄▄▄       ▓█████  ██▀███   ▒█████      ▄▄▄█████▓ █     █░ ██▓ ███▄    █
  ▒████▄     ▓█   ▀ ▓██ ▒ ██▒▒██▒  ██▒    ▓  ██▒ ▓▒▓█░ █ ░█░▓██▒ ██ ▀█   █
  ▒██  ▀█▄   ▒███   ▓██ ░▄█ ▒▒██░  ██▒    ▒ ▓██░ ▒░▒█░ █ ░█ ▒██▒▓██  ▀█ ██▒
  ░██▄▄▄▄██  ▒▓█  ▄  ▒██▀▀█▄  ▒██   ██░    ░ ▓██▓ ░ ░█░ █ ░█ ░██░▓██▒  ▐▌██▒
   ▓█   ▓██▒ ░▒████▒ ░██▓ ▒██▒░ ████▓▒░      ▒██▒ ░ ░░██▒██▓ ░██░▒██░   ▓██░
   ▒▒   ▓▒█░ ░░ ▒░ ░ ░ ▒▓ ░▒▓░░ ▒░▒░▒░       ▒ ░░   ░ ▓░▒ ▒  ░▓  ░ ▒░   ▒ ▒
```

> `AI Digital Twin for Airport Ground & Network Delay Management`
> `status: [ IN_DEVELOPMENT ]` `domain: ITS × Aviation × Digital Twin`

---

## `> about`

AeroTwin is an AI-powered digital twin for airport ground operations and
flight-network delay dynamics. It predicts delay risk, models how
disruption cascades across a flight network, and lets you simulate
"what-if" interventions — a runway closure, a fog event, a schedule
shock — before they happen in the real world.

Built as a course deliverable, scoped for real-world honesty: India does
not publish flight-level delay records the way the US does, so this
project uses a **hybrid data strategy** — global flight-level trajectory
data to power the twin, Indian government aggregate data to ground the
causal analysis, and a benchmark dataset to validate the modelling
approach at scale.

```
data > assumptions
decisions, not dashboards
```

---

## `> problem`

| # | issue | impact |
|---|---|---|
| 01 | Delay propagation | one late aircraft cascades delay across its network |
| 02 | Taxi-time unpredictability | fuel waste, runway queuing |
| 03 | Gate/stand allocation inefficiency | longer turnaround, apron congestion |
| 04 | Fog & weather disruption (esp. North India) | reactive, not model-driven response |
| 05 | No accessible what-if simulation tooling | disruptions are handled live, not pre-tested |

---

## `> architecture`

```
[ raw data ] → [ forecasting ] → [ clustering ] → [ graph analysis ] → [ CARI index ] → [ digital twin sim ]
```

| module | function | technique |
|---|---|---|
| `01_forecast` | delay-risk prediction by airport/airline/month | Prophet |
| `02_taxitime` | per-flight taxi-out/in duration prediction | XGBoost / Random Forest |
| `03_cluster` | congestion-risk grouping by airport/time-slot | K-Means |
| `04_graph` | delay-propagation & route criticality | NetworkX |
| `05_twin` | live simulation + disruption injection | SimPy + Streamlit |
| `06_maintenance` *(optional)* | engine remaining-useful-life estimation | LSTM / Random Forest |

**CARI — Composite Airport Resilience Index**
a single explainable 0–100 score per airport, combining delay risk,
weather exposure, congestion, and network criticality. Same weighted-index
methodology used in the author's DFCCIL GCT-DSS project (115 stations,
scored 92/100), applied here to Indian airports (DEL / BOM / BLR).

---

## `> stack`

```
python 3.11 · prophet · xgboost · scikit-learn
networkx · simpy · shap · streamlit · pandas · geopandas
```

---

## `> data_sources`

| dataset | source | use |
|---|---|---|
| OpenSky Network | opensky-network.org | flight-level trajectory → twin + taxi-time |
| DGCA delay-by-reason | dataful.in / data.gov.in | causal delay grounding (India) |
| india-aviation-traffic | github.com/Vonter (ODbL) | traffic volume cross-check |
| BTS On-Time Performance | transtats.bts.gov | methodology benchmark (US, flight-level) |
| IMD / Iowa Mesonet METAR | mesonet.agron.iastate.edu | weather exposure scoring |
| OurAirports | ourairports.com | runway/gate geometry |
| NASA C-MAPSS *(optional)* | data.nasa.gov | engine RUL, Module 06 |

> ⚠ datasets retain their own original licenses — see below.

---

## `> run`

```bash
git clone https://github.com/<your-username>/aerotwin.git
cd aerotwin
python -m venv venv && source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt
streamlit run app.py
```

---

## `> roadmap`

- [x] project proposal & architecture design
- [ ] data acquisition — OpenSky, DGCA, METAR (DEL/BOM/BLR)
- [ ] Module 01–02 — forecasting + taxi-time models
- [ ] Module 03–04 — clustering + propagation graph
- [ ] CARI composite index
- [ ] Module 05 — digital twin + simulation dashboard
- [ ] optional Module 06 — predictive maintenance
- [ ] deployment (Streamlit Cloud)

---

## `> license`

Code in this repository is released under the **MIT License** — see
[`LICENSE`](./LICENSE). Datasets used by this project are **not**
covered by this license and remain under their original terms
(OpenSky Network terms of use, ODbL for `india-aviation-traffic`,
US Government Open Data / public domain for BTS and NASA C-MAPSS).

---

## `> author`

**Abhinav Mishra**
B.Tech, AI & Data Science · Gati Shakti Vishwavidyalaya (GSV)
Head, TechnoCrats · ex-DFCCIL, ex-Indian Railways (DRM Office, S&T)

```
[ EOF ]
```
