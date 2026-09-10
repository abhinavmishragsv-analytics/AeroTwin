"""
AeroTwin Digital Twin Engine - VABO Runway 04/22 Ground & Departure Simulation
================================================================================
This is the "twin" half of the bi-directional digital twin: a SimPy
discrete-event model of every aircraft moving from Stand 1 -> pushback ->
taxi -> hold -> runway -> climb-out. Positions are exact WGS84 coordinates
for Vadodara Airport (VABO) so the 3D frontend can render them directly.

Bi-directionality: `AirportState.inject_disruption()` lets the FastAPI layer
(driven by the UI) mutate live simulation state - closing the runway,
lowering visibility, or forcing a ground stop - and every in-flight SimPy
process reacts to that mutation on its next yield, exactly like a real ATC
instruction would interrupt a real aircraft's taxi clearance.
"""
import math
import time

import simpy

from core.config import (
    RUNWAY_04_HOLD,
    RUNWAY_04_THRESHOLD,
    STAND_1,
    TAXIWAY_ENTRY,
)
from core.models import registry


class VadodaraAirport:
    def __init__(self, env: simpy.Environment):
        self.env = env
        self.runway = simpy.Resource(env, capacity=1)
        self.flights = {}

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
            # Shorter, localised hold: treated the same as a runway closure but a distinct label
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
        """How many aircraft are currently taxiing/holding/lining-up - feeds ML taxi-time model."""
        active_states = {"pushback", "taxi", "holding", "lineup"}
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

    # ------------------------------------------------------------------
    def pushback_and_depart(self, flight_id, risk_score=None):
        """
        Simulates exact real-world WGS84 coordinates for Vadodara Airport (VABO):
        - Terminal Apron Stand 1: (Lat: 22.33550, Lng: 73.22600, Alt: 0m), Heading: 180 deg
        - Pushback to Taxiway Alpha: (Lat: 22.33470, Lng: 73.22520, Alt: 0m), Heading: 224 deg
        - Taxi along Taxiway Alpha curve to Runway 04 Hold-Short: (Lat: 22.33020, Lng: 73.22010, Alt: 0m)
        - Lineup on Runway 04 Threshold: (Lat: 22.32970, Lng: 73.21930, Alt: 0m), Heading: 044 deg
        - Takeoff Roll down Runway 04 Centerline (Heading 044 deg) to (Lat: 22.34120, Lng: 73.23150, Alt: 0m)
        - Rotation (Pitch up 14 deg) & Climb into 3D Sky: Altitude 0m -> 450m (approx 1,500 ft AGL)

        If `risk_score` is None, the live ML model registry computes a composite
        risk from current weather + queue depth (Modules 01/02/07) instead of a
        purely random value.
        """
        # 1. Parked at VABO Terminal Apron Stand 1
        lat, lng = STAND_1
        alt = 0.0
        heading = 180.0
        pitch = 0.0
        roll = 0.0
        speed = 0

        if risk_score is None:
            risk_score = registry.compute_flight_risk(
                hour_of_day=self.hour_of_day,
                wind_kt=self.weather["wind_kt"],
                visibility_m=self.weather["visibility_m"],
                ceiling_ft=self.weather["ceiling_ft"],
                queue_depth=self.queue_depth(),
            )

        self.flights[flight_id] = {
            "id": flight_id,
            "lat": lat,
            "lng": lng,
            "altitude": alt,
            "heading": heading,
            "pitch": pitch,
            "roll": roll,
            "speed": speed,
            "status": "gate",
            "risk": risk_score,
        }
        yield self.env.timeout(2.5)

        # Ground stop: hold at the gate indefinitely until lifted (checked every 2s)
        while self.ground_stop:
            self.flights[flight_id]["status"] = "ground_stop"
            yield self.env.timeout(2.0)

        # 2. Pushback from Stand 1 onto Taxiway Alpha
        self.flights[flight_id]["status"] = "pushback"
        self.flights[flight_id]["speed"] = 5
        pushback_steps = 15
        target_lat, target_lng = TAXIWAY_ENTRY
        for i in range(pushback_steps):
            t = (i + 1) / pushback_steps
            self.flights[flight_id]["lat"] = lat + (target_lat - lat) * t
            self.flights[flight_id]["lng"] = lng + (target_lng - lng) * t
            self.flights[flight_id]["heading"] = 180.0 + 44.0 * t  # Swing tail towards 224 deg
            yield self.env.timeout(0.2)

        lat, lng = target_lat, target_lng
        yield self.env.timeout(1.0)

        # 3. Taxi along Taxiway Alpha toward Runway 04 Holding Point
        # Taxi duration is ML-modulated: Module 02 (XGBoost taxi-time) reacts to queue depth,
        # time of day and wind - a busier queue means a visibly longer, slower taxi.
        self.flights[flight_id]["status"] = "taxi"
        self.flights[flight_id]["speed"] = 18
        self.flights[flight_id]["heading"] = 224.0  # Taxiing southwest

        predicted_taxi_s = registry.predict_taxi_time_seconds(
            queue_depth=self.queue_depth(),
            hour_of_day=self.hour_of_day,
            wind_kt=self.weather["wind_kt"],
        )
        taxi_steps = max(12, min(60, int(predicted_taxi_s / 0.2)))
        target_lat, target_lng = RUNWAY_04_HOLD
        for i in range(taxi_steps):
            t = (i + 1) / taxi_steps
            self.flights[flight_id]["lat"] = lat + (target_lat - lat) * t
            self.flights[flight_id]["lng"] = lng + (target_lng - lng) * t
            yield self.env.timeout(0.2)

        lat, lng = target_lat, target_lng

        # 4. Holding Short of Runway 04 - reacts live to runway closures / ground stops
        self.flights[flight_id]["status"] = "holding"
        self.flights[flight_id]["speed"] = 0
        yield self.env.timeout(1.2)

        while self.env.now < self.runway_closed_until or self.ground_stop:
            self.flights[flight_id]["status"] = "holding"
            yield self.env.timeout(2.0)

        # 5. Enter & Line Up on Runway 04 Threshold (Heading 044 deg)
        with self.runway.request() as req:
            yield req

            # Re-check after acquiring the resource - a disruption may have landed while queued
            while self.env.now < self.runway_closed_until or self.ground_stop:
                self.flights[flight_id]["status"] = "holding"
                yield self.env.timeout(2.0)

            self.flights[flight_id]["status"] = "lineup"
            self.flights[flight_id]["speed"] = 8
            target_lat, target_lng = RUNWAY_04_THRESHOLD
            self.flights[flight_id]["lat"] = target_lat
            self.flights[flight_id]["lng"] = target_lng
            self.flights[flight_id]["heading"] = 44.0  # Runway 04 alignment
            yield self.env.timeout(1.5)

            # 6. Takeoff Roll along Runway 04 Centerline (2,469m asphalt)
            self.flights[flight_id]["status"] = "takeoff_roll"
            roll_steps = 40
            start_lat, start_lng = target_lat, target_lng
            end_roll_lat = 22.34120
            end_roll_lng = 73.23150

            for i in range(roll_steps):
                t = (i + 1) / roll_steps
                accel_t = t ** 1.6  # Realistic acceleration curve
                self.flights[flight_id]["lat"] = start_lat + (end_roll_lat - start_lat) * accel_t
                self.flights[flight_id]["lng"] = start_lng + (end_roll_lng - start_lng) * accel_t
                self.flights[flight_id]["speed"] = int(20 + 130 * t)  # 20 to 150 kts
                yield self.env.timeout(0.12)

            # 7. Rotation (Pitch up 12-14 deg) & Positive Rate of Climb into 3D Sky
            self.flights[flight_id]["status"] = "climb"
            climb_steps = 65
            climb_end_lat = 22.35650
            climb_end_lng = 73.24750

            for i in range(climb_steps):
                t = (i + 1) / climb_steps
                self.flights[flight_id]["lat"] = end_roll_lat + (climb_end_lat - end_roll_lat) * t
                self.flights[flight_id]["lng"] = end_roll_lng + (climb_end_lng - end_roll_lng) * t
                # Climb altitude smoothly from 0 to 420 meters (approx 1,400 ft AGL)
                self.flights[flight_id]["altitude"] = round(420.0 * (t ** 1.3), 1)
                self.flights[flight_id]["pitch"] = 13.0 if t < 0.65 else 10.0
                # Slight right bank on climb corridor
                if t > 0.3:
                    self.flights[flight_id]["heading"] = 44.0 + 3.0 * (t - 0.3)
                    self.flights[flight_id]["roll"] = 5.0
                self.flights[flight_id]["speed"] = int(150 + 90 * t)
                yield self.env.timeout(0.12)

        self.flights[flight_id]["status"] = "airborne"
