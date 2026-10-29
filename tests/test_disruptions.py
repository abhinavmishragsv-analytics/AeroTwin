"""Disruption behaviour: each ATC disruption must do what it says, and undo it.

These run a short, seeded simulation per disruption and assert the rule on the
recorded status transitions, so they catch regressions in the ATC layer, not
just crashes. Run with:  python -m pytest tests -q
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import simpy

from core.airports import get_layout
from core.config import ARRIVAL_SHARE
from core.twin_sim import Aerodrome

RUNWAY_STATES = {"takeoff_roll", "landing_rollout"}


def run(icao, kind, at, minutes, total_min=70, seed=11):
    env = simpy.Environment()
    sim = Aerodrome(env, get_layout(icao), seed=seed)
    rng = random.Random(seed + 1)

    def gen():
        yield env.timeout(5)
        while True:
            if rng.random() < ARRIVAL_SHARE and sim.accepts_arrival():
                env.process(sim.operate_arrival())
            elif sim.accepts_departure():
                env.process(sim.operate_departure())
            yield env.timeout(110)

    def inj():
        yield env.timeout(at)
        sim.inject_disruption(kind, minutes)

    env.process(gen())
    env.process(inj())
    events, prev = [], {}
    while env.now < total_min * 60:
        env.run(until=env.now + 1.0)
        for fid, f in sim.flights.items():
            if prev.get(fid) != f["status"]:
                events.append((env.now, fid, f["status"], sim.weather["wind_kt"], sim.weather["visibility_m"]))
                prev[fid] = f["status"]
    return sim, events


@pytest.fixture(params=["VABO", "VIDP"])
def icao(request):
    return request.param


def test_runway_closure_blocks_then_resumes(icao):
    _, ev = run(icao, "runway_closure", 600, 15)
    assert not [e for e in ev if 690 < e[0] < 1500 and e[2] in RUNWAY_STATES]
    assert [e for e in ev if e[0] > 1500 and e[2] in RUNWAY_STATES]


def test_fog_stops_landings_below_minima(icao):
    _, ev = run(icao, "fog", 600, 20)
    assert not [e for e in ev if e[2] == "landing_rollout" and e[4] < 1200]


def test_ground_stop_holds_pushbacks(icao):
    _, ev = run(icao, "ground_stop", 600, 12)
    assert not [e for e in ev if 605 < e[0] < 600 + 12 * 60 and e[2] == "pushback"]


def test_high_wind_applies_and_clears(icao):
    sim, ev = run(icao, "high_wind", 600, 10)
    assert max(e[3] for e in ev if 650 < e[0] < 1100) >= 25
    assert sim.weather["wind_kt"] < 20


def test_thunderstorm_clears(icao):
    sim, _ = run(icao, "thunderstorm", 600, 10)
    assert sim.weather["condition"] == "CLEAR"


def test_emergency_arrival_lands(icao):
    _, ev = run(icao, "emergency_arrival", 600, 0)
    assert any(e[2] == "landing_rollout" for e in ev if e[0] > 600)
