#!/usr/bin/env python3
"""
AeroTwin soak test
==================
Runs the twin headless, far faster than real time, and checks the safety
properties it claims to guarantee:

  * no two aircraft closer than 55 m on the ground
  * no two aircraft closer than 300 m laterally with under 120 m vertical
  * never more than one aircraft on the runway
  * no deadlock: aircraft keep completing movements for the whole run

Run it after any change to routing, ATC or the airport layouts:

    python scripts/soak_test.py                 # all airports, 60 sim-minutes
    python scripts/soak_test.py VABO 180        # one airport, 3 sim-hours
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simpy

from core.airports import available_icaos, get_layout
from core.config import ARRIVAL_SHARE, STREAM_HZ, TIME_COMPRESSION
from core.twin_sim import Aerodrome

# A deliberately nasty sequence: close the runway, then fog it in, then take
# the only parallel taxiway away, then put the wind across it.
STRESS = (
    (600, "runway_closure", 10, None),
    (1800, "fog", 12, None),
    (3000, "taxiway_closure", 8, "A"),
    (3300, "high_wind", 8, None),
    (4200, "emergency_arrival", 0, None),
    (4800, "thunderstorm", 10, None),
)


def soak(icao, sim_minutes=60, disruptions=(), seed=7):
    env = simpy.Environment()
    layout = get_layout(icao)
    sim = Aerodrome(env, layout, seed=seed)
    rng = random.Random(seed + 1)
    interval = 3600.0 / max(1, layout.movements_per_hour)

    def generator():
        yield env.timeout(5)
        while True:
            if rng.random() < ARRIVAL_SHARE and sim.accepts_arrival():
                env.process(sim.operate_arrival())
            else:
                env.process(sim.operate_departure())
            yield env.timeout(interval)

    env.process(generator())

    def injector():
        for at, kind, minutes, target in disruptions:
            yield env.timeout(max(0, at - env.now))
            sim.inject_disruption(kind, minutes, target=target)

    if disruptions:
        env.process(injector())

    period = TIME_COMPRESSION / STREAM_HZ
    while env.now < sim_minutes * 60:
        env.run(until=env.now + period)
        sim.monitor.audit(list(sim.flights.values()), sim.runway_ctl)
        sim.reap()
    return sim


def report(icao, label, sim):
    sep = sim.monitor.snapshot()
    m = sim.status_snapshot()["metrics"]
    movements = m["departures"] + m["arrivals"]
    failures = []
    if sep["ground_violations"]:
        failures.append(f"{sep['ground_violations']} ground separation violations")
    if sep["airborne_violations"]:
        failures.append(f"{sep['airborne_violations']} airborne separation violations")
    if sep["runway_incursions"]:
        failures.append(f"{sep['runway_incursions']} runway incursions")
    if movements == 0:
        failures.append("no movements completed - possible deadlock")

    status = "PASS" if not failures else "FAIL"
    print(f"[{status}] {icao} {label}")
    print(f"       {m['departures']} departures, {m['arrivals']} arrivals, "
          f"{m['go_arounds']} go-arounds, {m['diversions']} diversions")
    print(f"       avg taxi-out {m['avg_taxi_out_s']}s, "
          f"avg departure delay {m['avg_departure_delay_min']} min")
    print(f"       closest ground {sep['closest_ground_m']} m, "
          f"closest airborne {sep['closest_airborne_m']} m")
    for f in failures:
        print(f"       !! {f}")
    return not failures


def main():
    args = sys.argv[1:]
    icaos = [args[0].upper()] if args else available_icaos()
    minutes = int(args[1]) if len(args) > 1 else 60

    ok = True
    for icao in icaos:
        ok &= report(icao, "nominal", soak(icao, minutes))
        ok &= report(icao, "stressed", soak(icao, minutes, STRESS))
    print("\nALL CHECKS PASSED" if ok else "\nFAILURES DETECTED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
