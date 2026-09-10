"""
AeroTwin Digital Twin Engine - VABO Runway 04/22 Ground & Flight Simulation
================================================================================
This is the "twin" half of the bi-directional digital twin: a SimPy
discrete-event model of every aircraft moving through real gate -> pushback
-> taxi -> hold -> runway -> climb-out (departures) and approach -> touchdown
-> rollout -> taxi-in -> parked (arrivals) states, at exact WGS84 coordinates
for Vadodara Airport (VABO) Runway 04/22 and Taxiway Alpha.

Bi-directionality: `VadodaraAirport.inject_disruption()` lets the FastAPI
layer (driven by the UI) mutate live simulation state - closing the runway,
lowering visibility, or forcing a ground stop - and every in-flight SimPy
process reacts to that mutation on its next yield, exactly like a real ATC
instruction would interrupt a real aircraft's clearance.

All headings are computed from real great-circle bearings between the
airport's surveyed waypoints (see `_bearing_deg`) rather than hard-coded
guesses, and every heading change is interpolated along the *shortest*
angular path (see `_shortest_heading`) so the 3D model never spins the
"long way around" during a turn.
"""
import math
import time

import simpy

from core.config import (
    RUNWAY_04_HOLD,
    RUNWAY_04_THRESHOLD,
    RUNWAY_22_THRESHOLD,
    RUNWAY_HEADING_DEG,
    STAND_1,
    STREAM_HZ,
    TAXIWAY_ENTRY,
)
from core.models import registry

# Every animation segment below is stepped at this interval, matching the
# WebSocket broadcast rate exactly - this is what makes multi-aircraft motion
# read as continuous rather than "stepped": the twin's own source-of-truth
# state changes every broadcast frame, so the frontend is never interpolating
# across a gap wider than one frame.
STEP_DT = 1.0 / STREAM_HZ


def _steps_for(duration_s):
    return max(1, round(duration_s / STEP_DT))

# Climb-out / final-approach fix, shared by both directions of flight -
# departures climb toward this point, arrivals descend from it.
CLIMB_APPROACH_FIX = (22.35650, 73.24750)
CLIMB_APPROACH_ALT_M = 420.0

# Takeoff-roll / landing-rollout midpoint (end of the accelerate/decelerate run)
RUNWAY_ROLL_POINT = (22.34120, 73.23150)


def _bearing_deg(p1, p2):
    """Great-circle initial bearing from p1=(lat,lng) to p2=(lat,lng), in degrees [0, 360)."""
    lat1, lng1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lng2 = math.radians(p2[0]), math.radians(p2[1])
    dlng = lng2 - lng1
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _shortest_heading(start_heading, target_heading, t):
    """Interpolate from start_heading to target_heading via the shorter angular
    path (never more than 180 degrees of turn), at fraction t in [0, 1]."""
    delta = ((target_heading - start_heading + 180.0) % 360.0) - 180.0
    return (start_heading + delta * t) % 360.0


class VadodaraAirport:
    def __init__(self, env: simpy.Environment):
        self.env = env
        self.runway = simpy.Resource(env, capacity=1)
        self.flights = {}
        self._terminal_since = {}  # flight_id -> sim-time it reached airborne/parked, for cleanup

        # --- Live, mutable twin state (the "digital" half of the digital twin) ---
        self.runway_closed_until = 0.0     # sim-time (seconds) until which the runway is closed
        self.ground_stop = False           # hard stop: nobody may line up, regardless of runway state
        self.weather = {
            "visibility_m": 8000,
            "ceiling_ft": 2500,
            "wind_kt": 8,
            "condition": "CLEAR",
        }
        self.active_disruptions = []       # human-readable log of injected events, most recent first
        self.hour_of_day = time.localtime().tm_hour

    # ------------------------------------------------------------------
    # Bi-directional control surface - called from FastAPI /api/disrupt
    # ------------------------------------------------------------------
    def inject_disruption(self, disruption_type: str, duration_minutes: float = 15.0, label: str = None):
        """Mutate live sim state; every in-progress SimPy process observes this immediately."""
        duration_s = max(0.0, float(duration_minutes)) * 60.0
        now = self.env.now

        if disruption_type == "runway_closure":
            self.runway_closed_until = max(self.runway_closed_until, now + duration_s)
            msg = f"Runway 04/22 CLOSED for {duration_minutes:.0f} min (maintenance)"

        elif disruption_type == "maintenance_delay":
            self.runway_closed_until = max(self.runway_closed_until, now + duration_s)
            msg = f"Maintenance delay: runway hold for {duration_minutes:.0f} min"

        elif disruption_type == "ground_stop":
            self.ground_stop = True
            self.env.process(self._auto_lift_ground_stop(duration_s))
            msg = f"Ground stop issued for {duration_minutes:.0f} min"

        elif disruption_type == "fog":
            self.weather.update({"visibility_m": 800, "ceiling_ft": 300, "condition": "FOG"})
            self.env.process(self._auto_clear_weather(duration_s))
            msg = f"Fog / Cat III conditions injected for {duration_minutes:.0f} min"

        elif disruption_type == "high_wind":
            self.weather.update({"wind_kt": 32, "condition": "HIGH_WIND"})
            self.env.process(self._auto_clear_weather(duration_s))
            msg = f"High crosswind event injected for {duration_minutes:.0f} min"

        elif disruption_type == "clear":
            self.runway_closed_until = 0.0
            self.ground_stop = False
            self.weather.update({"visibility_m": 8000, "ceiling_ft": 2500, "wind_kt": 8, "condition": "CLEAR"})
            msg = "All disruptions cleared - normal operations resumed"

        else:
            msg = f"Unknown disruption type '{disruption_type}' ignored"

        entry = {"time": round(now, 1), "type": disruption_type, "label": label or msg}
        self.active_disruptions.insert(0, entry)
        self.active_disruptions = self.active_disruptions[:20]
        return entry

    def _auto_lift_ground_stop(self, duration_s):
        yield self.env.timeout(duration_s)
        self.ground_stop = False

    def _auto_clear_weather(self, duration_s):
        yield self.env.timeout(duration_s)
        self.weather.update({"visibility_m": 8000, "ceiling_ft": 2500, "wind_kt": 8, "condition": "CLEAR"})

    # ------------------------------------------------------------------
    def queue_depth(self):
        """How many aircraft are currently occupying the runway/taxiway system - feeds ML taxi-time model."""
        active_states = {"pushback", "taxi", "holding", "lineup", "landing_rollout", "taxi_in"}
        return sum(1 for f in self.flights.values() if f["status"] in active_states)

    def status_snapshot(self):
        return {
            "runway_closed": self.env.now < self.runway_closed_until,
            "runway_closed_remaining_s": max(0.0, round(self.runway_closed_until - self.env.now, 1)),
            "ground_stop": self.ground_stop,
            "weather": self.weather,
            "queue_depth": self.queue_depth(),
            "disruptions": self.active_disruptions,
        }

    def reap_terminal_flights(self, max_age_s=45.0):
        """Drop aircraft that have been airborne/parked for a while, so long-running
        servers don't accumulate an ever-growing flights dict. Called periodically
        from core/main.py's broadcast loop - purely a memory-hygiene housekeeping
        pass, has no effect on anything currently visible in the UI."""
        now = self.env.now
        stale = [fid for fid, since in self._terminal_since.items() if now - since > max_age_s]
        for fid in stale:
            self.flights.pop(fid, None)
            self._terminal_since.pop(fid, None)

    def _mark_terminal(self, flight_id):
        self._terminal_since[flight_id] = self.env.now

    def _taxi_steps(self):
        """Live queue-depth-aware step count for a taxi-speed leg, shared by
        departure taxi-out and arrival taxi-in so both react to Module 02."""
        predicted_s = registry.predict_taxi_time_seconds(
            queue_depth=self.queue_depth(), hour_of_day=self.hour_of_day, wind_kt=self.weather["wind_kt"],
        )
        clamped_s = max(2.4, min(12.0, predicted_s))
        return _steps_for(clamped_s)

    # ------------------------------------------------------------------
    # Shared low-level motion primitive - every taxi/roll/climb/descent segment
    # in this file is built out of this one interpolation generator, so every
    # segment moves and turns exactly the same smooth, physically-consistent way.
    # ------------------------------------------------------------------
    def _advance(self, flight_id, start, end, steps, step_dt, target_heading=None,
                 speed_fn=None, altitude_fn=None, pitch_fn=None, roll_fn=None):
        """Linearly interpolate lat/lng from start to end over `steps` yields of
        `step_dt` sim-seconds each. If target_heading is given, the aircraft's
        heading turns toward it along the shortest angular path over the same
        duration. speed_fn/altitude_fn/pitch_fn/roll_fn are optional callables
        of the progress fraction t in [0, 1] used to drive those fields."""
        lat0, lng0 = start
        lat1, lng1 = end
        start_heading = self.flights[flight_id]["heading"]
        for i in range(steps):
            t = (i + 1) / steps
            f = self.flights[flight_id]
            f["lat"] = lat0 + (lat1 - lat0) * t
            f["lng"] = lng0 + (lng1 - lng0) * t
            if target_heading is not None:
                f["heading"] = _shortest_heading(start_heading, target_heading, t)
            if speed_fn is not None:
                f["speed"] = speed_fn(t)
            if altitude_fn is not None:
                f["altitude"] = altitude_fn(t)
            if pitch_fn is not None:
                f["pitch"] = pitch_fn(t)
            if roll_fn is not None:
                f["roll"] = roll_fn(t)
            yield self.env.timeout(step_dt)

    # ------------------------------------------------------------------
    def pushback_and_depart(self, flight_id, risk_score=None):
        """
        Departure sequence, at exact WGS84 coordinates for VABO:
          gate (Stand 1) -> pushback onto Taxiway Alpha -> taxi to Runway 04
          hold-short -> line up on Runway 04 threshold -> takeoff roll ->
          rotate & climb out toward the departure corridor.

        If `risk_score` is None, the live ML model registry computes a
        composite risk from current weather + queue depth (Modules 01/02/07)
        instead of a purely random value.
        """
        if risk_score is None:
            risk_score = registry.compute_flight_risk(
                hour_of_day=self.hour_of_day,
                wind_kt=self.weather["wind_kt"],
                visibility_m=self.weather["visibility_m"],
                ceiling_ft=self.weather["ceiling_ft"],
                queue_depth=self.queue_depth(),
            )

        # 1. Parked at VABO Terminal Apron Stand 1
        self.flights[flight_id] = {
            "id": flight_id,
            "lat": STAND_1[0],
            "lng": STAND_1[1],
            "altitude": 0.0,
            "heading": 180.0,
            "pitch": 0.0,
            "roll": 0.0,
            "speed": 0,
            "status": "gate",
            "risk": risk_score,
            "direction": "DEP",
        }
        yield self.env.timeout(2.5)

        while self.ground_stop:
            self.flights[flight_id]["status"] = "ground_stop"
            yield self.env.timeout(2.0)

        # 2. Pushback from Stand 1 onto Taxiway Alpha - real surveyed bearing, not a guess
        self.flights[flight_id]["status"] = "pushback"
        pushback_heading = _bearing_deg(STAND_1, TAXIWAY_ENTRY)
        yield from self._advance(
            flight_id, STAND_1, TAXIWAY_ENTRY, steps=_steps_for(3.0), step_dt=STEP_DT,
            target_heading=pushback_heading, speed_fn=lambda t: 5,
        )
        yield self.env.timeout(1.0)

        # 3. Taxi along Taxiway Alpha toward Runway 04 Holding Point.
        # Taxi duration is ML-modulated: Module 02 (XGBoost taxi-time) reacts to
        # queue depth, time of day and wind - a busier queue visibly slows every aircraft.
        self.flights[flight_id]["status"] = "taxi"
        taxi_heading = _bearing_deg(TAXIWAY_ENTRY, RUNWAY_04_HOLD)
        yield from self._advance(
            flight_id, TAXIWAY_ENTRY, RUNWAY_04_HOLD, steps=self._taxi_steps(), step_dt=STEP_DT,
            target_heading=taxi_heading, speed_fn=lambda t: 18,
        )

        # 4. Holding Short of Runway 04 - reacts live to runway closures / ground stops
        self.flights[flight_id]["status"] = "holding"
        self.flights[flight_id]["speed"] = 0
        yield self.env.timeout(1.2)

        while self.env.now < self.runway_closed_until or self.ground_stop:
            self.flights[flight_id]["status"] = "holding"
            yield self.env.timeout(2.0)

        # 5. Enter & Line Up on Runway 04 Threshold (smooth turn onto the runway
        # centerline heading, not an instant teleport+snap-rotate)
        with self.runway.request() as req:
            yield req

            while self.env.now < self.runway_closed_until or self.ground_stop:
                self.flights[flight_id]["status"] = "holding"
                yield self.env.timeout(2.0)

            self.flights[flight_id]["status"] = "lineup"
            yield from self._advance(
                flight_id, RUNWAY_04_HOLD, RUNWAY_04_THRESHOLD, steps=_steps_for(1.5), step_dt=STEP_DT,
                target_heading=RUNWAY_HEADING_DEG, speed_fn=lambda t: 8,
            )
            yield self.env.timeout(0.8)

            # 6. Takeoff Roll along Runway 04 Centerline (2,469m asphalt)
            self.flights[flight_id]["status"] = "takeoff_roll"
            yield from self._advance(
                flight_id, RUNWAY_04_THRESHOLD, RUNWAY_ROLL_POINT, steps=_steps_for(4.8), step_dt=STEP_DT,
                speed_fn=lambda t: int(20 + 130 * (t ** 1.6)),  # realistic acceleration curve
            )

            # 7. Rotation (pitch up) & positive rate of climb into 3D sky
            self.flights[flight_id]["status"] = "climb"
            yield from self._advance(
                flight_id, RUNWAY_ROLL_POINT, CLIMB_APPROACH_FIX, steps=_steps_for(7.8), step_dt=STEP_DT,
                target_heading=RUNWAY_HEADING_DEG + 3.0,  # gentle right turn onto departure corridor
                speed_fn=lambda t: int(150 + 90 * t),
                altitude_fn=lambda t: round(CLIMB_APPROACH_ALT_M * (t ** 1.3), 1),
                pitch_fn=lambda t: 13.0 if t < 0.65 else 10.0,
                roll_fn=lambda t: 5.0 if t > 0.3 else 0.0,
            )

        self.flights[flight_id]["status"] = "airborne"
        self.flights[flight_id]["pitch"] = 0.0
        self.flights[flight_id]["roll"] = 0.0
        self._mark_terminal(flight_id)

    # ------------------------------------------------------------------
    def land_and_taxi_in(self, flight_id, risk_score=None):
        """
        Arrival sequence, the mirror image of pushback_and_depart:
          final approach descent -> touchdown & landing rollout on Runway 22 ->
          exit runway -> taxi in via Taxiway Alpha -> park at Stand 1.

        Shares the same runway Resource as departures, so an arrival and a
        departure can never occupy Runway 04/22 at the same instant - exactly
        like real single-runway ATC separation.
        """
        if risk_score is None:
            risk_score = registry.compute_flight_risk(
                hour_of_day=self.hour_of_day,
                wind_kt=self.weather["wind_kt"],
                visibility_m=self.weather["visibility_m"],
                ceiling_ft=self.weather["ceiling_ft"],
                queue_depth=self.queue_depth(),
            )

        approach_heading = _bearing_deg(CLIMB_APPROACH_FIX, RUNWAY_22_THRESHOLD)

        # 1. On final approach, descending toward Runway 22 threshold
        self.flights[flight_id] = {
            "id": flight_id,
            "lat": CLIMB_APPROACH_FIX[0],
            "lng": CLIMB_APPROACH_FIX[1],
            "altitude": CLIMB_APPROACH_ALT_M,
            "heading": approach_heading,
            "pitch": -3.0,
            "roll": 0.0,
            "speed": 160,
            "status": "approach",
            "risk": risk_score,
            "direction": "ARR",
        }
        yield from self._advance(
            flight_id, CLIMB_APPROACH_FIX, RUNWAY_22_THRESHOLD, steps=_steps_for(6.6), step_dt=STEP_DT,
            target_heading=approach_heading,
            speed_fn=lambda t: int(160 - 20 * t),
            altitude_fn=lambda t: round(CLIMB_APPROACH_ALT_M * ((1 - t) ** 1.3), 1),
            pitch_fn=lambda t: -3.0 if t < 0.85 else -1.0,
        )
        self.flights[flight_id]["altitude"] = 0.0
        self.flights[flight_id]["pitch"] = 0.0

        # 2. A runway closure/ground stop on short final would be a go-around in
        # real ATC; here we simply hold position at the threshold until clear,
        # which is visually equivalent for a slow-taxi-speed twin.
        with self.runway.request() as req:
            yield req
            while self.env.now < self.runway_closed_until or self.ground_stop:
                self.flights[flight_id]["status"] = "holding"
                yield self.env.timeout(2.0)

            # 3. Touchdown & landing rollout, decelerating along the runway centerline
            self.flights[flight_id]["status"] = "landing_rollout"
            yield from self._advance(
                flight_id, RUNWAY_22_THRESHOLD, RUNWAY_ROLL_POINT, steps=_steps_for(4.9), step_dt=STEP_DT,
                target_heading=approach_heading,
                speed_fn=lambda t: int(140 - 100 * (t ** 1.4)),
            )
            yield from self._advance(
                flight_id, RUNWAY_ROLL_POINT, RUNWAY_04_HOLD, steps=_steps_for(3.0), step_dt=STEP_DT,
                speed_fn=lambda t: int(40 - 25 * t),
            )

        # 4. Exit the runway and taxi in via Taxiway Alpha (reverse of the departure path)
        self.flights[flight_id]["status"] = "taxi_in"
        taxi_in_heading = _bearing_deg(RUNWAY_04_HOLD, TAXIWAY_ENTRY)
        yield from self._advance(
            flight_id, RUNWAY_04_HOLD, TAXIWAY_ENTRY, steps=self._taxi_steps(), step_dt=STEP_DT,
            target_heading=taxi_in_heading, speed_fn=lambda t: 15,
        )
        yield self.env.timeout(0.5)

        gate_heading = _bearing_deg(TAXIWAY_ENTRY, STAND_1)
        yield from self._advance(
            flight_id, TAXIWAY_ENTRY, STAND_1, steps=_steps_for(3.0), step_dt=STEP_DT,
            target_heading=gate_heading, speed_fn=lambda t: int(10 * (1 - t)),
        )

        # 5. Parked on stand
        self.flights[flight_id]["status"] = "parked"
        self.flights[flight_id]["speed"] = 0
        self._mark_terminal(flight_id)
