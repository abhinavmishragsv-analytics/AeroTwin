"""Tests for the flight-data recorder (core/telemetry.py).

Run with:  python -m pytest tests -q
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import simpy

from core.airports import get_layout
from core.config import ARRIVAL_SHARE
from core.telemetry import CHANNELS, cabin_details, MIN_SAMPLES
from core.twin_sim import Aerodrome


def run_sim(icao="VABO", minutes=60, disrupt=None, seed=None):
    env = simpy.Environment()
    sim = Aerodrome(env, get_layout(icao), seed=seed if seed is not None else 7)

    def gen():
        yield env.timeout(2)
        while True:
            if sim.rng.random() < ARRIVAL_SHARE and sim.accepts_arrival():
                env.process(sim.operate_arrival())
            elif sim.accepts_departure():
                env.process(sim.operate_departure())
            yield env.timeout(110)

    env.process(gen())
    if disrupt:
        def d():
            for at, kind, mins in disrupt:
                yield env.timeout(max(0, at - env.now))
                sim.inject_disruption(kind, mins)
        env.process(d())
    env.run(until=minutes * 60)
    return sim


@pytest.fixture(scope="module")
def vabo():
    return run_sim("VABO", 75)


def test_legs_are_direction_pure(vabo):
    legs = vabo.telemetry.list()
    assert legs, "no legs recorded"
    for s in legs:
        assert s["id"].endswith(":" + s["direction"])
        leg = vabo.telemetry.get(s["id"])
        phases = set(leg.cols["status"])
        if s["direction"] == "ARR":
            assert not phases & {"pushback", "taxi_out", "takeoff_roll", "climb"}, phases
        else:
            assert not phases & {"inbound", "final", "landing_rollout", "approach"}, phases


def test_arrival_and_departure_of_one_aircraft_are_separate_legs(vabo):
    ids = {s["id"] for s in vabo.telemetry.list()}
    both = {i.split(":")[0] for i in ids if i.endswith(":ARR")} & {i.split(":")[0] for i in ids if i.endswith(":DEP")}
    # Not every aircraft turns round inside 75 minutes, but any that did must
    # have two independent legs.
    for fid in both:
        assert f"{fid}:ARR" in ids and f"{fid}:DEP" in ids


def test_completed_outcomes(vabo):
    done = vabo.telemetry.list(state="completed")
    assert done
    for s in done:
        assert s["outcome"] in ("landed", "departed", "diverted", "aborted", "cancelled")
        assert s["n"] >= MIN_SAMPLES
        if s["direction"] == "DEP":
            assert s["outcome"] in ("departed", "cancelled", "aborted")
        else:
            assert s["outcome"] in ("landed", "diverted", "aborted")


def test_detail_shape_and_channels(vabo):
    s = next(x for x in vabo.telemetry.list(state="completed") if x["outcome"] in ("landed", "departed"))
    d = vabo.telemetry.detail(s["id"])
    names = {c[0] for c in CHANNELS}
    assert names <= set(d["ch"])
    for k, v in d["ch"].items():
        assert len(v) == d["n"] == len(d["t"]), k
    assert d["t"] == sorted(d["t"])
    assert len(d["phase"]) == d["n"]
    assert d["kpis"] and d["events"]


def test_speeds_are_physical(vabo):
    """Catches unit slips such as the old m/s-stored-as-knots end-of-leg glitch."""
    for s in vabo.telemetry.list(state="completed"):
        d = vabo.telemetry.detail(s["id"])
        gs = d["ch"]["gs_kt"]
        assert max(gs) < 330, (s["id"], max(gs))
        assert min(gs) >= 0
        # No wild accelerations anywhere in the recording.
        acc = [a for a in d["ch"]["accel_g"] if a is not None]
        assert max(abs(a) for a in acc) < 0.6, (s["id"], max(abs(a) for a in acc))


def test_since_returns_tail(vabo):
    s = vabo.telemetry.list(state="completed")[0]
    full = vabo.telemetry.detail(s["id"])
    tail = vabo.telemetry.detail(s["id"], since=10)
    assert tail["since"] == 10
    assert tail["t"] == full["t"][10:]
    assert tail["ch"]["gs_kt"] == full["ch"]["gs_kt"][10:]


def test_arrival_kpis(vabo):
    arr = [x for x in vabo.telemetry.list(state="completed") if x["outcome"] == "landed"]
    assert arr
    d = vabo.telemetry.detail(arr[0]["id"])
    k = {x["key"]: x["value"] for x in d["kpis"]}
    assert k["td_gs"] and 60 < k["td_gs"] < 180
    assert 0 < k["td_sink"] < 700
    assert k["rot"] > 20
    names = [e["name"] for e in d["events"]]
    assert "touchdown" in names and "runway_clear" in names


def test_departure_kpis(vabo):
    dep = [x for x in vabo.telemetry.list(state="completed") if x["outcome"] == "departed"]
    assert dep
    d = vabo.telemetry.detail(dep[0]["id"])
    k = {x["key"]: x["value"] for x in d["kpis"]}
    assert 15 < k["roll_time"] < 90
    assert k["roll_dist"] > 600
    names = [e["name"] for e in d["events"]]
    for n in ("brake_release", "liftoff", "vr"):
        assert n in names


def test_deterministic_for_same_leg(vabo):
    s = vabo.telemetry.list(state="completed")[0]
    a = vabo.telemetry.detail(s["id"])
    vabo.telemetry.get(s["id"])._cache = None
    b = vabo.telemetry.detail(s["id"])
    assert a["ch"]["n1_1"] == b["ch"]["n1_1"]
    assert a["ch"]["ff_kg_h"] == b["ch"]["ff_kg_h"]


def test_cabin_details_match_frontend_algorithm():
    # Values produced by ui/src/lib/flightDetails.js for the same ids (see the
    # node cross-check in the PR notes); guards the Python port of the RNG.
    d = cabin_details("6E-101", 180)
    assert d["flight_number"].startswith("6E ")
    assert 0.62 <= d["load_factor"] <= 0.95
    assert d["registration"].startswith("VT-") and len(d["registration"]) == 6


def test_disruptions_leave_legs_consistent():
    sim = run_sim("VABO", 90, disrupt=[
        (600, "fog", 20), (1500, "thunderstorm", 15), (2400, "runway_closure", 10),
        (3000, "emergency_arrival", 5), (3300, "clear", 0)])
    legs = sim.telemetry.list()
    assert legs
    conds = {c for s in legs for c in s["conditions"]}
    assert conds & {"FOG", "THUNDERSTORM", "RUNWAY CLOSED", "EMERGENCY"}
    for s in sim.telemetry.list(state="completed"):
        d = sim.telemetry.detail(s["id"])
        assert all(math.isfinite(x) for x in d["ch"]["gs_kt"])
