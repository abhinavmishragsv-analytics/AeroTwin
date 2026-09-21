"""
AeroTwin Digital Twin Engine
============================
The SimPy model of an aerodrome's ground and terminal-area operations.

What changed from the first build, and why
------------------------------------------
The demo version animated each aircraft along a straight line between five
hard-coded points, with no notion of who owned which piece of pavement. That is
why aircraft overlapped on the taxiway, why the taxiway did not connect to the
apron, and why "runway closed" could not do anything more interesting than
pause a timer.

This engine works the other way round: an aircraft asks ATC for permission, and
its position is a *consequence* of what it was cleared to do.

  arrival:   inbound -> approach -> (hold / go-around / divert) -> final ->
             touchdown -> rollout -> vacate via a named turn-off -> taxi in
             along a real route -> park on an allocated stand
  turnaround: stand occupied, aircraft becomes the next departure
  departure: pushback -> taxi out via a real route -> hold short at a named
             holding point -> line up -> roll -> rotate -> climb out

Every ground movement is a walk through the taxi graph whose edges were locked
in advance (see core.atc.GroundNetwork), so aircraft follow taxiway centrelines
and cannot occupy the same stretch of pavement. Every runway movement holds the
runway resource, so a landing and a departure cannot overlap. Motion itself is
kinematic - acceleration, deceleration into turns, a 3 degree glideslope, a
rotation speed that depends on the aircraft type - rather than a fixed number
of interpolation steps.
"""
from __future__ import annotations

import math
import random

import simpy

from core import aircraft as fleet
from core import atc as atc_mod
from core import routing
from core.config import (
    ARRIVAL_SHARE,
    CLEAR_WEATHER,
    DECISION_RANGE_M,
    DEPARTURE_ALT_M,
    DEPARTURE_FIX_M,
    DESPAWN_AFTER_S,
    DISRUPTION_LOG_LIMIT,
    FINAL_APPROACH_FIX_M,
    GLIDESLOPE_DEG,
    HOLD_ALTITUDE_M,
    HOLD_RADIUS_M,
    INITIAL_APPROACH_FIX_M,
    INITIAL_PARKED_FRACTION,
    MAX_APPROACH_ATTEMPTS,
    MISSED_APPROACH_ALT_M,
    STEP_DT,
    TURNAROUND_SCALE,
)
from core.geo import (
    bearing_deg,
    destination,
    distance_m,
    heading_delta,
    interpolate,
    lerp_heading,
    path_length_m,
    point_along_path,
    smooth_path,
)
from core.models import registry

KT = 0.514444          # knots -> m/s
FPM = 0.00508          # feet/min -> m/s
MAX_TURN_RATE_DEG_S = 12.0

DESTINATIONS = ["VIDP", "VABB", "VOBL", "VOMM", "VOHS", "VECC", "VAAH", "VOGO", "VOCI", "VIJP"]


class Aerodrome:
    """One airport's live simulation. Owns its ATC, its aircraft and its weather."""

    def __init__(self, env: simpy.Environment, layout, seed=None):
        self.env = env
        self.layout = layout
        self.rng = random.Random(seed if seed is not None else hash(layout.icao) & 0xFFFF)

        self.ground = atc_mod.GroundNetwork(env, layout)
        self.stands = atc_mod.StandManager(env, layout)
        # The twin operates one runway at a time; extra runways at multi-runway
        # airports are drawn but not yet independently sequenced.
        # One controller per runway. Runways whose centrelines physically
        # intersect cannot be used independently - a departure on one and a
        # landing on the other would meet at the crossing - so they share a
        # single occupancy resource and are sequenced as one runway, which is
        # what Mumbai actually does with 09/27 and 14/32.
        self.runway_ctls = {}
        for rwy in layout.runways:
            ctl = atc_mod.RunwayController(env, layout, rwy)
            for other_name, other in self.runway_ctls.items():
                if self._runways_intersect(rwy, other.runway):
                    ctl.resource = other.resource
                    break
            self.runway_ctls[rwy.name] = ctl
        # The primary runway remains the default for anything that has not
        # been assigned one yet (snapshots, seeding, back-compatible callers).
        self.runway_ctl = self.runway_ctls[layout.runways[0].name]
        self.monitor = atc_mod.SeparationMonitor()

        self.flights = {}
        self._finished_at = {}
        self._counter = 100

        self.weather = dict(CLEAR_WEATHER)
        self.weather["wind_dir_deg"] = layout.default_wind_dir_deg
        self.weather["wind_kt"] = layout.default_wind_kt
        # Independent, simultaneously-active weather effects (fog, crosswind,
        # a thunderstorm, ...), keyed by disruption kind - see
        # `_set_weather_effect`/`_recompute_weather` for how these combine
        # into `self.weather` above without one effect's expiry wiping out
        # every other effect still running.
        self.active_weather_effects = {}
        self._weather_effect_tokens = {}
        self._weather_effect_seq = 0
        self.ground_stop = False
        self.ground_stop_reason = None
        self.active_disruptions = []

        # Arrival sequencing state. Real arrivals are spaced by approach control
        # long before they reach the aerodrome, so the twin does the same rather
        # than letting inbounds pile onto the same point in space.
        self._last_arrival_spawn_t = -1e9
        self._hold_stack = set()
        self._final_claim = None

        self.metrics = {
            "departures": 0,
            "arrivals": 0,
            "go_arounds": 0,
            "diversions": 0,
            "cancelled_departures": 0,
            "total_departure_delay_min": 0.0,
            "total_taxi_out_s": 0.0,
            "taxi_out_samples": 0,
            "total_hold_s": 0.0,
        }

        for _c in self.runway_ctls.values():
            _c.select_active_end(self.weather["wind_dir_deg"], self.weather["wind_kt"])
        self._seed_apron()

    # =====================================================================
    # Helpers
    # =====================================================================
    def _next_callsign(self):
        self._counter += 1
        return f"{self.rng.choice(self.layout.airlines)}-{self._counter}"

    def local_hour(self):
        """Aerodrome local hour, advancing with the simulation clock. Feeds the
        ML models, which are time-of-day sensitive."""
        import time as _time
        base = _time.localtime().tm_hour + _time.localtime().tm_min / 60.0
        return (base + self.env.now / 3600.0) % 24

    def queue_depth(self):
        moving = {"pushback", "taxi_out", "hold_short", "lineup", "landing_rollout",
                  "runway_vacate", "taxi_in", "takeoff_roll"}
        return sum(1 for f in self.flights.values() if f["status"] in moving)

    def airborne_count(self):
        airborne = {"inbound", "approach", "final", "holding", "go_around", "climb", "rotate"}
        return sum(1 for f in self.flights.values() if f["status"] in airborne)

    def accepts_arrival(self, ac_type=None):
        """Whether approach control would release another inbound right now.

        Three gates, all of which are real: in-trail spacing behind the last
        aircraft released, the number already established on the approach, and
        whether the apron has anywhere to put it. An aerodrome that fails these
        does not get a stream of aircraft that then all go around - it gets
        fewer aircraft, because they are held or delayed upstream.
        """
        # The gap has to reflect the full time a single arrival occupies the
        # final approach corridor - join, descend, any clearance wait, wake
        # separation, short final, rollout and vacate - not just wake-turbulence
        # spacing. Offering arrivals faster than that just fills the approach
        # queue with aircraft that will time out and divert; a real approach
        # control unit would not release them in the first place.
        # Spacing is driven by how long one aircraft owns the final approach
        # corridor (_claim_final serialises it), which is roughly the descent
        # from the final approach fix plus rollout and vacate. The old 260 s
        # floor was tuned when arrivals frequently timed out and diverted; now
        # that they reliably land, it throttled arrivals so hard that a busy
        # airport ran ~5 departures per arrival and the approach looked empty.
        base = 110.0 if ac_type is None else fleet.arrival_separation_s(ac_type, ac_type) * 1.3
        gap = max(base, 260.0)
        if self.env.now - self._last_arrival_spawn_t < gap:
            return False
        inbound = sum(1 for f in self.flights.values()
                      if f["status"] in ("inbound", "approach", "final", "holding", "go_around"))
        if inbound >= 3:
            return False
        # Apron headroom, not just "is there one stand left". Accepting
        # arrivals until the last stand is taken fills the apron to 100% and
        # holds it there: every later arrival then has to hold or divert, and
        # every departure is competing for taxiways with a parked-solid apron.
        # Real aerodromes keep spare stands for turnarounds, towing and
        # irregular operations, so the twin reserves a small margin too - the
        # apron ends up busy but workable, which is both more realistic and
        # far better to look at than a permanently full one.
        want = ac_type or fleet.get("A20N")
        if self.stands.free_stand(want) is None:
            return False
        total = len(self.stands.resources)
        free = sum(1 for v in self.stands.occupant.values() if v is None)
        reserve = max(1, int(total * 0.15))
        if free <= reserve:
            return False
        return True

    @staticmethod
    def _runways_intersect(r1, r2):
        from core.geo import segments_intersect
        return segments_intersect(r1.ends[0].threshold, r1.ends[1].threshold,
                                  r2.ends[0].threshold, r2.ends[1].threshold,
                                  r1.ends[0].threshold)

    def assign_runway(self, ac, role):
        """Pick a runway for this aircraft.

        Filters on what the runway can physically do for this type - enough
        length for its takeoff or landing distance, and an end the wind
        actually allows - then balances across whatever is left, so a
        multi-runway airport spreads its traffic instead of queueing
        everything onto the first runway in the list.
        """
        usable = []
        for ctl in self.runway_ctls.values():
            if ctl.is_closed():
                continue
            ok = (ctl.takeoff_allowed(self.weather)[0] if role == "DEP"
                  else ctl.landing_allowed(self.weather)[0])
            if not ok:
                continue
            need = ac.todr_m * 1.05 if role == "DEP" else ac.ldr_m * 1.15
            if ctl.runway.length_m < need:
                continue
            usable.append(ctl)
        if not usable:
            return self.runway_ctl
        # Least-loaded first: queued departures plus sequenced arrivals.
        return min(usable, key=lambda c: len(c.departure_queue) + len(c.arrival_sequence)
                   + len(c.resource.queue))

    def controller_for(self, f):
        """The runway controller this flight is operating on."""
        return f.get("_ctl") or self.runway_ctl

    def accepts_departure(self):
        """Whether to push another aircraft onto stand as a fresh departure.

        Departures were generated on a fixed timer with no regard for whether
        the runway could absorb them, so at a busy airport they simply
        accumulated on stands: VIDP ended a 10-hour run with 29 aircraft
        parked waiting to push back and exactly one actually taxiing, which
        filled every stand and looked like an apron-capacity problem when it
        was really an unmetered-queue problem. A departure that cannot get
        airborne for an hour should never have been given a stand in the
        first place.
        """
        waiting = sum(1 for f in self.flights.values()
                      if f["direction"] == "DEP"
                      and f["status"] in ("scheduled", "pushback", "taxi_out", "hold_short"))
        # Roughly a runway's worth of queue: beyond this, another aircraft on
        # stand adds delay and apron congestion, not throughput.
        return waiting < 6

    def _claim_final(self, fid):
        """Take the final approach segment. A plain single-owner claim: no one
        else may hold it until the owner explicitly releases it.

        This deliberately does NOT try to detect a "stale" holder by inspecting
        its flight status - an earlier version guessed that a holder whose
        status was not one of a specific busy list must have gone away, and
        stole the claim out from under it. But "holding" is a status an
        aircraft can be in either before it has claimed final (queued,
        sequencing) or after (established, waiting on landing clearance) -
        indistinguishable from the status field alone - so that guess could and
        did steal the slot from an aircraft still actively established on
        final, putting two aircraft on the same approach. The claim is instead
        released explicitly, from exactly one place: the `finally` block in
        `_fly_approach` and from `_finish`, both of which run on every exit
        path (normal, go-around, divert, or the flight simply disappearing) -
        so a lost flight can never wedge the approach, and no live one can ever
        be stolen from.
        """
        if self._final_claim in (None, fid):
            self._final_claim = fid
            return True
        return False

    def _release_final(self, fid):
        if self._final_claim == fid:
            self._final_claim = None

    def _claim_hold_level(self):
        """Holding aircraft are stacked 1000 ft apart, not flown into each other."""
        for level in range(8):
            if level not in self._hold_stack:
                self._hold_stack.add(level)
                return level
        return 7

    def _release_hold_level(self, level):
        self._hold_stack.discard(level)

    def _risk(self):
        return registry.compute_flight_risk(
            hour_of_day=int(self.local_hour()),
            wind_kt=self.weather["wind_kt"],
            visibility_m=self.weather["visibility_m"],
            ceiling_ft=self.weather["ceiling_ft"],
            queue_depth=self.queue_depth(),
        )

    def _new_flight(self, direction, ac_type, stand=None, ctl=None):
        fid = self._next_callsign()
        ctl = ctl or self.runway_ctl
        self.flights[fid] = {
            "id": fid,
            "type": ac_type.code,
            "type_name": ac_type.name,
            "wake": ac_type.wake,
            "category": ac_type.category,
            "model_scale": ac_type.model_scale,
            "seats": ac_type.seats,
            "direction": direction,
            "status": "scheduled",
            "lat": 0.0, "lng": 0.0, "altitude": 0.0,
            "heading": 0.0, "pitch": 0.0, "roll": 0.0, "speed": 0,
            "stand": stand.id if stand else None,
            "stand_name": stand.name if stand else None,
            "route": None,
            "cleared_to": None,
            "hold_reason": None,
            "runway": ctl.active_end_ident,
            "runway_name": ctl.runway.name,
            "_ctl": ctl,
            "other_airport": self.rng.choice([d for d in DESTINATIONS if d != self.layout.icao]),
            "risk": self._risk(),
            "delay_min": 0.0,
            "approach_attempt": 0,
            "on_ground": True,
            # Set by _emergency_arrival - lets the frontend pick this aircraft
            # out of the traffic for a priority halo, instead of the map only
            # being able to show "an emergency was declared somewhere".
            "emergency": False,
        }
        return self.flights[fid]

    def _finish(self, fid, status):
        f = self.flights.get(fid)
        if f is None:
            return
        if f.get("hold_level") is not None:
            self._release_hold_level(f.pop("hold_level"))
        self._release_final(fid)
        f["status"] = status
        f["speed"] = 0
        self._finished_at[fid] = self.env.now
        self.ground.release_all(fid)

    def reap(self, max_age_s=DESPAWN_AFTER_S):
        stale = [fid for fid, t in self._finished_at.items() if self.env.now - t > max_age_s]
        for fid in stale:
            self.flights.pop(fid, None)
            self._finished_at.pop(fid, None)

    # =====================================================================
    # Motion primitives
    # =====================================================================
    def _traverse(self, f, points, v_entry_kt, v_max_kt, v_exit_kt,
                  accel=1.2, decel=1.5, alt_fn=None, pitch_fn=None, roll_fn=None,
                  on_progress=None):
        """Drive an aircraft along a polyline with a trapezoidal speed profile.

        Speeds are true (knots); the aircraft accelerates towards `v_max_kt` and
        begins braking early enough to arrive at `v_exit_kt`, which is what
        produces a believable rollout, a believable turn onto a taxiway and a
        believable stop on the stand. Heading follows the path but is rate
        limited, so nothing ever snaps round a corner.
        """
        points = [p for i, p in enumerate(points) if i == 0 or distance_m(p, points[i - 1]) > 0.2]
        if len(points) < 2:
            return
        # Round corners into a continuous curve before driving the kinematic
        # model along it - see smooth_path() for why the raw node-to-node
        # polyline is what made turns look blocky. This still passes through
        # every original waypoint, so nothing downstream (hold bars, runway
        # thresholds) moves.
        points = smooth_path(points)
        total = path_length_m(points)
        if total <= 0.5:
            return
        v = max(0.0, v_entry_kt * KT)
        v_max = max(0.6, v_max_kt * KT)
        v_exit = max(0.0, v_exit_kt * KT)
        s = 0.0
        while s < total - 0.05:
            remaining = total - s
            v_brake = math.sqrt(max(0.0, v_exit ** 2 + 2 * decel * remaining))
            target = min(v_max, v_brake)
            if v < target:
                v = min(target, v + accel * STEP_DT)
            else:
                v = max(target, v - decel * STEP_DT)
            v = max(v, 0.35)          # never fully stall mid-leg
            s = min(total, s + v * STEP_DT)
            pos, brg = point_along_path(points, s)
            f["lat"], f["lng"] = pos
            max_turn = MAX_TURN_RATE_DEG_S * STEP_DT
            delta = heading_delta(f["heading"], brg)
            f["heading"] = (f["heading"] + max(-max_turn, min(max_turn, delta))) % 360.0
            f["speed"] = int(round(v / KT))
            progress = s / total
            if alt_fn is not None:
                f["altitude"] = round(max(0.0, alt_fn(progress, s, total)), 1)
            if pitch_fn is not None:
                f["pitch"] = round(pitch_fn(progress), 1)
            if roll_fn is not None:
                f["roll"] = round(roll_fn(progress), 1)
            else:
                f["roll"] = round(max(-25.0, min(25.0, -delta * 2.2)), 1)
            if on_progress is not None:
                on_progress(progress, s, total)
            yield self.env.timeout(STEP_DT)
        f["speed"] = int(round(v_exit))

    def _hold_position(self, f, seconds, status=None, reason=None):
        """Stop where you are. Used for holding short, waiting on separation,
        and sitting on stand - all of which are real, observable states."""
        if status:
            f["status"] = status
        if reason is not None:
            f["hold_reason"] = reason
        f["speed"] = 0
        f["roll"] = 0.0
        yield self.env.timeout(seconds)

    def _fly_circuit(self, f, center, radius, altitude, turns=1.0, speed_kt=210):
        """Fly a holding orbit. Aircraft that cannot land yet do this instead of
        freezing mid-air, which is both correct and far better to look at."""
        start_brg = bearing_deg(center, (f["lat"], f["lng"]))
        steps = max(24, int(turns * 48))
        pts = []
        for i in range(steps + 1):
            ang = (start_brg + 360.0 * turns * i / steps) % 360.0
            pts.append(destination(center, ang, radius))
        yield from self._traverse(
            f, pts, speed_kt, speed_kt, speed_kt, accel=0.8, decel=0.8,
            alt_fn=lambda p, s, t: altitude,
            pitch_fn=lambda p: 0.0,
            roll_fn=lambda p: 22.0,
        )

    # =====================================================================
    # Ground clearance helpers
    # =====================================================================
    def _plan_departure_route(self, f, stand):
        """Choose a holding point that gives enough runway, then route to it."""
        ac = fleet.get(f["type"])
        ctl = self.controller_for(f)
        candidates = []
        for node in self.layout.hold_short_nodes(ctl.active_end_ident):
            usable = ctl.runway.length_m - self.runway_along(node.pos, ctl)
            if usable < ac.todr_m * 1.05:
                continue            # intersection departure not legal for this type
            route = routing.plan(self.layout, stand.node_id, node.id)
            if route is None:
                continue
            candidates.append((route.length_m(), node, route, usable))
        if not candidates:
            return None, None
        candidates.sort(key=lambda c: c[0])
        _, node, route, usable = candidates[0]
        f["cleared_to"] = node.label or node.id
        f["route"] = route.describe()
        f["takeoff_run_m"] = round(usable)
        return node, route

    def runway_along(self, pos, ctl=None):
        """Along-track distance of a point from the active landing threshold.

        Taxiway nodes sit beside the runway, not on it, so a straight range is
        not the distance down the runway. Both ranges (from each threshold)
        together recover the along-track component exactly, which is what makes
        turn-off selection and intersection-departure length correct in either
        runway direction.
        """
        ctl = ctl or self.runway_ctl
        rwy = ctl.runway
        end = ctl.active_end()
        opp = rwy.opposite(end.ident)
        L = rwy.length_m
        d_near = distance_m(end.threshold, pos)
        d_far = distance_m(opp.threshold, pos)
        return max(0.0, min(L, (L * L + d_near ** 2 - d_far ** 2) / (2 * L)))

    def _exit_edge_for(self, node):
        """The taxiway edge that takes an aircraft off the runway at this node."""
        for kind in ("rapid_exit", "runway_link"):
            for edge in self.layout.edges.values():
                if edge.kind == kind and node.id in (edge.u, edge.v):
                    return edge
        return None

    def _plan_arrival_exit(self, f):
        """Pick the turn-off this aircraft can realistically make.

        An arrival cannot turn off before it has slowed down, so only exits
        beyond its landing distance are offered - a 787 rolls past the first
        turn-off an ATR would have taken, which is why they queue differently.
        A rapid exit is preferred; a right-angle link is the fallback.
        """
        ac = fleet.get(f["type"])
        ctl = self.controller_for(f)
        rwy = ctl.runway
        options = []
        for node in self.layout.runway_access_nodes(rwy.name):
            along = self.runway_along(node.pos, ctl)
            if along < ac.ldr_m * 0.8:
                continue                  # still too fast to turn off here
            if along > rwy.length_m - 60:
                continue                  # past the far end
            options.append((along, node))
        options.sort(key=lambda o: o[0])
        for rapid_first in (True, False):
            for along, node in options:
                edge = self._exit_edge_for(node)
                if edge is None or edge.closed:
                    continue
                is_rapid = edge.kind == "rapid_exit"
                if is_rapid != rapid_first:
                    continue
                if self.ground.free(self.ground.edge_keys(edge)):
                    node.exit_distance_m = along
                    return node, edge
        return None, None

    # =====================================================================
    # Flight lifecycle
    # =====================================================================
    def operate_arrival(self, ac_type=None, attempt_start=0, emergency=False):
        """Full arrival, ending either parked (and turned round) or diverted."""
        ac = ac_type or fleet.pick_type(self.layout.fleet_mix, self.rng)
        f = self._new_flight("ARR", ac, ctl=self.assign_runway(ac, "ARR"))
        f["emergency"] = emergency
        ctl = self.controller_for(f)
        fid = f["id"]
        f["on_ground"] = False
        f["status"] = "inbound"

        self._last_arrival_spawn_t = self.env.now
        end = ctl.active_end()
        approach_brg = (end.heading_deg + 180) % 360
        faf = destination(end.threshold, approach_brg, FINAL_APPROACH_FIX_M)
        # Inbounds join from different radials and ranges rather than all
        # appearing at one point on the extended centreline.
        join_range = INITIAL_APPROACH_FIX_M + self.rng.uniform(0, 9000)
        join_radial = (approach_brg + self.rng.uniform(-45, 45)) % 360
        iaf = destination(end.threshold, join_radial, join_range)
        f["lat"], f["lng"] = iaf
        f["heading"] = bearing_deg(iaf, faf)
        f["altitude"] = 1200 + self.rng.uniform(0, 500)
        f["speed"] = 240
        f["runway"] = end.ident

        try:
            while f["approach_attempt"] <= MAX_APPROACH_ATTEMPTS:
                landed = yield from self._fly_approach(f, ac, iaf, faf)
                if landed:
                    break
                f["approach_attempt"] += 1
                if f["approach_attempt"] > MAX_APPROACH_ATTEMPTS:
                    yield from self._divert(f)
                    return
                # _fly_approach already flew the go-around leg itself, while
                # still holding the final-approach claim, for any failure that
                # happened after the aircraft was established in the corridor.
                # Nothing further to fly here before retrying.
        except simpy.Interrupt:
            self._finish(fid, "despawned")
            return

        # --- on the ground, rolling out ----------------------------------
        yield from self._taxi_in(f, ac)
        if self.flights.get(fid, {}).get("status") == "parked":
            self.metrics["arrivals"] += 1
            yield from self._turnaround_and_depart(f, ac)

    def _fly_approach(self, f, ac, iaf, faf):
        """Fly one approach. Returns True if it landed, False for a go-around.

        Two rules keep the terminal area clean, and both are what approach
        control actually does rather than tricks to make the picture look right:

          1. One aircraft flies the final approach segment at a time. A joining
             inbound holds outside until the aircraft ahead has landed and
             vacated. Without this, traffic joining from different radials
             converges on the final approach fix, which is precisely how the
             previous build ended up with two aircraft in the same piece of sky.
          2. An aircraft is never frozen in mid-air waiting for something. If
             the aerodrome cannot take it - weather below minima, runway closed
             or occupied, no stand, no usable turn-off - it flies a holding
             pattern at its own level in the stack, and goes around only once it
             has run out of patience.
        """
        ctl = self.controller_for(f)
        fid = f["id"]
        end = ctl.active_end()
        approach_brg = (end.heading_deg + 180) % 360
        gs = math.tan(math.radians(GLIDESLOPE_DEG))
        faf_alt = FINAL_APPROACH_FIX_M * gs
        hold_center = destination(destination(faf, approach_brg, HOLD_RADIUS_M),
                                  (approach_brg + 90) % 360, HOLD_RADIUS_M * 0.8)

        level = None
        holds = 0
        req = None
        exit_node = exit_edge = None
        claimed_final = False

        def _hold_geometry():
            lvl = level if level is not None else 0
            return HOLD_RADIUS_M + lvl * 260, HOLD_ALTITUDE_M + lvl * 300

        try:
            # --- sequence onto the final approach ------------------------
            join_pos = (f["lat"], f["lng"])
            join_center = destination(join_pos, (bearing_deg(join_pos, faf) + 90) % 360, 2600)
            waits = 0
            while not self._claim_final(fid):
                if waits >= 14:
                    f["hold_reason"] = "unable to sequence for final"
                    return False
                if level is None:
                    level = self._claim_hold_level()
                    f["hold_level"] = level
                f["status"] = "holding"
                f["hold_reason"] = "sequencing for final approach"
                f["cleared_to"] = f"hold at the initial fix, level {level + 1}"
                yield from self._fly_circuit(
                    f, join_center, 2600 + level * 300,
                    max(f["altitude"], HOLD_ALTITUDE_M + level * 300), turns=0.5, speed_kt=235)
                waits += 1
            claimed_final = True

            # --- join and descend to the glideslope intercept ------------
            f["status"] = "inbound"
            f["hold_reason"] = None
            entry_alt = f["altitude"]
            yield from self._traverse(
                f, [(f["lat"], f["lng"]), faf], f["speed"], 230, ac.approach_speed_kt + 20,
                accel=0.7, decel=0.6,
                alt_fn=lambda p, s, t: entry_alt + (faf_alt - entry_alt) * min(1.0, p * 1.15),
                pitch_fn=lambda p: -2.0,
            )

            # --- can the aerodrome actually take us? ---------------------
            while True:
                blocked = None
                ok, reason = ctl.landing_allowed(self.weather)
                if not ok:
                    blocked = reason
                elif self.stands.free_stand(ac) is None:
                    blocked = "no stand available"
                else:
                    exit_node, exit_edge = self._plan_arrival_exit(f)
                    if exit_node is None:
                        blocked = "no usable runway exit"

                if blocked is None:
                    # Reserve the turn-off before committing to the landing, so
                    # the aircraft is guaranteed somewhere to vacate to.
                    if not self.ground.try_acquire(fid, self.ground.edge_keys(exit_edge)):
                        blocked = "runway exit occupied"

                if blocked is None:
                    req = ctl.request(fid, "ARR")
                    if fid not in ctl.arrival_sequence:
                        ctl.arrival_sequence.append(fid)
                    deadline = self.env.now + max(45.0, (FINAL_APPROACH_FIX_M - DECISION_RANGE_M) /
                                                  max(1.0, ac.approach_speed_kt * KT))
                    f["status"] = "approach"
                    f["cleared_to"] = f"number {len(ctl.arrival_sequence)} for {end.ident}"
                    radius, alt = _hold_geometry()
                    while not req.triggered and self.env.now < deadline:
                        # A quarter orbit at a time, so the decision to go
                        # around is never more than a few seconds late.
                        yield from self._fly_circuit(f, hold_center, radius, alt, turns=0.25,
                                                     speed_kt=max(180, ac.approach_speed_kt + 40))
                    if not req.triggered:
                        req.cancel()
                        ctl.resource.release(req)
                        req = None
                        self.ground.release_all(fid)
                        if fid in ctl.arrival_sequence:
                            ctl.arrival_sequence.remove(fid)
                        f["hold_reason"] = "runway not available at decision point"
                        yield from self._go_around_path(f, ac)
                        return False
                    break

                holds += 1
                if holds > 4:
                    f["hold_reason"] = blocked
                    # Already established in the approach corridor (past the
                    # join/descend leg) - fly the missed-approach climb-out
                    # before giving the corridor back, so a newly-sequenced
                    # inbound can never start descending into the same space
                    # this aircraft is still occupying on its way out.
                    yield from self._go_around_path(f, ac)
                    return False
                if level is None:
                    level = self._claim_hold_level()
                    f["hold_level"] = level
                f["status"] = "holding"
                f["hold_reason"] = blocked
                f["cleared_to"] = f"hold, level {level + 1}"
                self.metrics["total_hold_s"] += 120
                radius, alt = _hold_geometry()
                yield from self._fly_circuit(f, hold_center, radius, alt, turns=1.0,
                                             speed_kt=max(180, ac.approach_speed_kt + 40))

            # --- established, cleared, descending out of the hold --------
            if level is not None:
                self._release_hold_level(level)
                f.pop("hold_level", None)
                level = None
            if distance_m((f["lat"], f["lng"]), faf) > 400:
                f["status"] = "final"
                hold_alt = f["altitude"]
                yield from self._traverse(
                    f, [(f["lat"], f["lng"]), faf], 200, 210, ac.approach_speed_kt + 15,
                    accel=0.7, decel=0.7,
                    alt_fn=lambda p, s, t, a0=hold_alt: a0 + (faf_alt - a0) * p,
                    pitch_fn=lambda p: -1.5)

            # Wake separation behind the preceding movement.
            gap = ctl.separation_wait_s(ac, "ARR")
            if gap > 0:
                f["status"] = "final"
                f["hold_reason"] = f"spacing {int(gap)}s"
                yield self.env.timeout(min(gap, 75))

            ok, reason = ctl.landing_allowed(self.weather)
            if not ok:
                ctl.resource.release(req)
                req = None
                self.ground.release_all(fid)
                if fid in ctl.arrival_sequence:
                    ctl.arrival_sequence.remove(fid)
                f["hold_reason"] = reason
                yield from self._go_around_path(f, ac)
                return False

            ctl.occupy(fid, "ARR", ac)
            f["status"] = "final"
            f["hold_reason"] = None
            f["cleared_to"] = f"cleared to land {end.ident}"

            # --- final descent on the glideslope -------------------------
            yield from self._traverse(
                f, [(f["lat"], f["lng"]), end.threshold],
                ac.approach_speed_kt + 15, ac.approach_speed_kt + 10, ac.approach_speed_kt,
                accel=0.5, decel=0.5,
                alt_fn=lambda p, s, t: max(0.0, (t - s) * gs),
                pitch_fn=lambda p: -2.5 if p < 0.92 else 4.0,
                roll_fn=lambda p: 0.0,
            )

            # --- touchdown and rollout to the reserved turn-off ----------
            f["status"] = "landing_rollout"
            f["altitude"] = 0.0
            f["pitch"] = 3.0
            f["on_ground"] = True
            exit_speed = ac.exit_speed_kt if exit_node.rapid else 12
            yield from self._traverse(
                f, [end.threshold, exit_node.pos],
                ac.approach_speed_kt - 5, ac.approach_speed_kt - 5, exit_speed,
                accel=0.4, decel=1.8,
                alt_fn=lambda p, s, t: 0.0,
                pitch_fn=lambda p: 3.0 * max(0.0, 1 - p * 4),
                roll_fn=lambda p: 0.0,
            )

            # --- vacate: the runway is released only once fully clear ----
            f["status"] = "runway_vacate"
            f["cleared_to"] = f"vacate via {exit_node.label or exit_node.id}"
            exit_points = self.layout.edge_points(exit_edge, forward=(exit_edge.u == exit_node.id))
            yield from self._traverse(
                f, exit_points, max(8, exit_speed), max(10, exit_speed), 10,
                accel=0.8, decel=1.4, alt_fn=lambda p, s, t: 0.0, pitch_fn=lambda p: 0.0)

            ctl.vacate(fid, ac, "ARR")
            ctl.resource.release(req)
            req = None
            if fid in ctl.arrival_sequence:
                ctl.arrival_sequence.remove(fid)
            f["_exit_node"] = exit_edge.v if exit_edge.u == exit_node.id else exit_edge.u
            f["_exit_edge"] = exit_edge.id
            f["exit_via"] = exit_node.label or exit_node.id
            return True
        finally:
            if level is not None:
                self._release_hold_level(level)
                f.pop("hold_level", None)
            if claimed_final:
                self._release_final(fid)

    def _go_around_path(self, f, ac):
        """Missed approach: straight ahead, climb, then a circuit back to final.

        Each go-around takes its own level in the stack, so two aircraft that
        miss in quick succession fly separated circuits instead of the same
        circle at the same altitude - which is what a real missed approach
        procedure achieves with published altitudes and tracks.
        """
        ctl = self.controller_for(f)
        end = ctl.active_end()
        self.metrics["go_arounds"] += 1
        level = self._claim_hold_level()
        f["hold_level"] = level
        f["status"] = "go_around"
        f["cleared_to"] = f"going around, climb to {int(MISSED_APPROACH_ALT_M + level * 300)} m"
        f["on_ground"] = False
        circuit_alt = MISSED_APPROACH_ALT_M + level * 300
        ahead = destination((f["lat"], f["lng"]), end.heading_deg, 5200 + level * 700)
        yield from self._traverse(
            f, [(f["lat"], f["lng"]), ahead], ac.approach_speed_kt, 180, 190,
            accel=1.0, decel=0.8,
            alt_fn=lambda p, s, t, a0=f["altitude"], a1=circuit_alt: a0 + (a1 - a0) * p,
            pitch_fn=lambda p: 9.0,
        )
        # Rejoin downwind and come back to the initial approach fix
        approach_brg = (end.heading_deg + 180) % 360
        downwind = destination(destination((f["lat"], f["lng"]), (end.heading_deg + 90) % 360,
                                           3800 + level * 600),
                               approach_brg, 9000)
        iaf = destination(end.threshold, (approach_brg + 18 + level * 9) % 360,
                          INITIAL_APPROACH_FIX_M + level * 900)
        yield from self._traverse(
            f, [(f["lat"], f["lng"]), downwind, iaf], 190, 200, 200,
            accel=0.7, decel=0.7,
            alt_fn=lambda p, s, t, a1=circuit_alt: a1,
            pitch_fn=lambda p: 0.0,
        )
        self._release_hold_level(level)
        f.pop("hold_level", None)

    def _divert(self, f):
        ctl = self.controller_for(f)
        self.metrics["diversions"] += 1
        f["status"] = "diverted"
        f["cleared_to"] = f"diverting to {f['other_airport']}"
        end = ctl.active_end()
        away = destination((f["lat"], f["lng"]), (end.heading_deg + 120) % 360, 22000)
        yield from self._traverse(
            f, [(f["lat"], f["lng"]), away], 220, 260, 260,
            alt_fn=lambda p, s, t, a0=f["altitude"]: a0 + 2000 * p, pitch_fn=lambda p: 6.0)
        self._finish(f["id"], "diverted")

    def _taxi_whole_route(self, f, route, v_cruise, status_label,
                          v_entry=None, v_exit=2.0, skip_first_leg=False):
        """Drive a taxi route, holding the whole clearance for its duration.

        This is deliberately the simple, conservative design: acquire every
        edge and junction of the route atomically in GroundNetwork's canonical
        order, then drive it. That ordering is the entire proof that the
        ground network cannot deadlock, and two attempts at being cleverer
        both broke it in ways that took a 10-hour soak to surface:

          * acquiring segment-by-segment in *travel* order let two aircraft
            taxiing toward each other on the same apron lane acquire the same
            segments in opposite orders and wedge head-on;
          * splitting the route into apron/movement-area blocks and releasing
            the apron behind us looked safe, but VABO's apron has only two
            links to the taxiway, and both are taxilane-kind - so they landed
            in the apron block, and aircraft sat holding a scarce apron exit
            while queueing for the movement-area block, forming the same
            cycle one level up.

        Holding the whole route is less concurrent, but it is *correct*, and
        apron congestion is better solved by not over-filling the apron in the
        first place (see accepts_arrival and the turnaround/stand budget) than
        by weakening the invariant that keeps the airfield from wedging.
        """
        fid = f["id"]
        v_entry = v_cruise if v_entry is None else v_entry

        # Poll for the whole clearance instead of blocking on it.
        #
        # GroundNetwork.acquire() takes keys one at a time, yielding on each -
        # so an aircraft that blocks part-way through is holding the keys it
        # already got while waiting for the rest. That is a
        # lock-held-while-waiting edge in the wait-for graph, and it is enough
        # to deadlock two departures against each other even though every
        # acquisition follows the canonical order (the ordering argument
        # assumes an all-or-nothing acquisition, which a yielding loop is
        # not). try_acquire() is genuinely all-or-nothing: it takes every key
        # or none, so a waiting aircraft holds nothing and can never be part
        # of a cycle.
        f["hold_reason"] = "awaiting taxi clearance"
        keys = self.ground.route_keys(route)
        while not self.ground.try_acquire(fid, keys):
            yield self.env.timeout(10)
        f["hold_reason"] = None
        f["status"] = status_label

        legs = route.legs[1:] if skip_first_leg else route.legs
        for li, (edge, forward) in enumerate(legs):
            pts = self.layout.edge_points(edge, forward)
            is_last = li == len(legs) - 1

            # Runway crossing. At a multi-runway aerodrome the way from the
            # apron to one runway routinely crosses another, and taxiing
            # across an active runway unannounced is the worst thing a ground
            # model can get wrong - so the aircraft takes that runway's
            # occupancy for the crossing, exactly as it would be held and then
            # cleared to cross in reality.
            crossing_ctl = None
            crossing_req = None
            if edge.crosses_runway:
                crossing_ctl = self.runway_ctls.get(edge.crosses_runway)
            if crossing_ctl is not None:
                f["status"] = "hold_short"
                f["hold_reason"] = f"hold short of runway {crossing_ctl.runway.name}"
                crossing_req = crossing_ctl.resource.request(
                    priority=atc_mod.PRIORITY_DEPARTURE - 1)
                yield crossing_req
                f["cleared_to"] = f"cross runway {crossing_ctl.runway.name}"
                f["hold_reason"] = None
                f["status"] = status_label

            try:
                yield from self._traverse(
                    f, pts, v_entry if li == 0 else v_cruise, v_cruise,
                    v_exit if is_last else v_cruise,
                    accel=0.8, decel=1.2,
                    alt_fn=lambda p, s, t: 0.0, pitch_fn=lambda p: 0.0)
            finally:
                if crossing_req is not None:
                    crossing_ctl.resource.release(crossing_req)

    def _taxi_in(self, f, ac):
        """From the runway turn-off to an allocated stand."""
        fid = f["id"]
        stand = self.stands.free_stand(ac)
        if stand is None:
            # No stand: hold on the taxiway until one frees up. Real, and a
            # good demonstration of apron capacity as a constraint - but
            # capped, same reasoning as the departure route wait above: this
            # aircraft is also still holding its runway-exit lock the whole
            # time it waits here, so an unbounded wait risks tying up that
            # exit for everyone else too, not just itself.
            f["status"] = "hold_short"
            f["hold_reason"] = "no stand available"
            stand_wait_attempts = 0
            while stand is None:
                stand_wait_attempts += 1
                if stand_wait_attempts > 20:  # 20 * 20s ≈ 6.5 sim-minutes
                    self.ground.release_all(fid)
                    yield from self._divert(f)
                    return
                yield self.env.timeout(20)
                stand = self.stands.free_stand(ac)
        yield from self.stands.occupy(fid, stand.id)
        f["stand"] = stand.id
        f["stand_name"] = stand.name

        route = routing.plan(self.layout, f["_exit_node"], stand.node_id)
        if route is None:
            f["hold_reason"] = "no taxi route"
            self._finish(fid, "despawned")
            return
        f["route"] = route.describe()
        f["cleared_to"] = f"taxi to {stand.name}"
        f["status"] = "hold_short"
        f["hold_reason"] = "taxi clearance"

        # An arrival sitting on the runway turn-off is holding pavement that
        # departures need, so it must never JOIN A QUEUE for its taxi route
        # while holding it - that is a lock held while waiting for locks, and
        # it deadlocked arrivals against departures: the arrival waited on a
        # junction owned by a departure, while the departure waited on apron
        # edges owned by the arrival. Instead, poll non-blockingly: take the
        # route only when it is free in one go, and while it is not, keep the
        # exit but add nothing to the wait-for graph. The whole route is
        # still taken atomically in canonical order, so the no-cycle argument
        # is untouched.
        # Take the taxi route without ever QUEUEING for it while parked on the
        # runway turn-off. Two failure modes were ruled out here, in order:
        #
        #   * blocking on acquire_route() while holding the turn-off put a
        #     lock-held-while-waiting edge into the wait-for graph and
        #     deadlocked arrivals against departures outright;
        #   * polling non-blockingly but *camping* on the turn-off until the
        #     route came free was deadlock-safe but starved everyone: several
        #     arrivals each sat on a turn-off holding three locks, blocking
        #     the departures whose routes they needed AND the next arrival,
        #     which then held for "no usable runway exit".
        #
        # So: poll, and if the route does not come free promptly, release the
        # turn-off pavement (keeping only the stand booking) and wait clear of
        # it before trying again. The aircraft is still on the ground and
        # still going to its stand - it just stops being an obstacle while it
        # waits, which is what a real aircraft told to hold clear would do.
        taxi_kt = self._taxi_speed(ac)
        route_keys = self.ground.route_keys(route)
        clearance_attempts = 0
        while not self.ground.try_acquire(fid, route_keys):
            clearance_attempts += 1
            if clearance_attempts % 6 == 0:
                # Give back everything EXCEPT the pavement we are physically
                # sitting on. Releasing that too (release_all) let a departure
                # taxi straight through a parked arrival - 0.0 m separation,
                # caught by the soak test. What we hand back is the part of
                # the turn-off ahead of us; the exit edge and its node stay
                # ours until we actually move off them.
                keep = set()
                exit_edge = self.layout.edges.get(f.get("_exit_edge"))
                if exit_edge is not None:
                    keep.update(self.ground.edge_keys(exit_edge))
                keep.add(("N", f["_exit_node"]))
                self.ground.release_all(fid, keep=keep)
                alt = routing.plan(self.layout, f["_exit_node"], stand.node_id)
                if alt is not None:
                    route = alt
                    route_keys = self.ground.route_keys(route)
                    f["route"] = route.describe()
            yield self.env.timeout(15)

        yield from self._taxi_whole_route(f, route, taxi_kt, "taxi_in", v_entry=10, v_exit=2)
        self.ground.release_all(fid)

        f["lat"], f["lng"] = stand.pos
        f["heading"] = stand.heading_deg
        f["status"] = "parked"
        f["speed"] = 0
        f["cleared_to"] = None

    def _taxi_speed(self, ac):
        """Taxi speed, slowed by the ML taxi-time model and by visibility.

        Module 02's prediction is a duration; the twin turns it into a speed by
        comparing it against the nominal taxi time for the airport, so a busy
        queue or a bad hour genuinely slows every aircraft on the surface.
        """
        predicted_s = registry.predict_taxi_time_seconds(
            queue_depth=self.queue_depth(),
            hour_of_day=int(self.local_hour()),
            wind_kt=self.weather["wind_kt"],
        )
        nominal_s = 420.0
        factor = max(0.55, min(1.15, nominal_s / max(60.0, predicted_s)))
        speed = ac.taxi_speed_kt * factor
        if self.weather["visibility_m"] < 1500:
            speed *= 0.6            # low visibility taxi procedures
        elif self.weather.get("wet"):
            speed *= 0.85
        return max(5.0, speed)

    def _turnaround_and_depart(self, f, ac):
        """The aircraft on stand becomes the next departure."""
        fid = f["id"]
        turn_s = ac.turnaround_min * 60.0 * TURNAROUND_SCALE
        f["status"] = "turnaround"
        f["direction"] = "TURN"
        f["cleared_to"] = None
        yield self.env.timeout(turn_s)

        f["direction"] = "DEP"
        # The outbound leg gets its own runway assignment - wind, closures and
        # load may all have changed during the turnaround.
        f["_ctl"] = self.assign_runway(ac, "DEP")
        f["runway"] = f["_ctl"].active_end_ident
        f["runway_name"] = f["_ctl"].runway.name
        f["other_airport"] = self.rng.choice([d for d in DESTINATIONS if d != self.layout.icao])
        f["approach_attempt"] = 0
        f["risk"] = self._risk()
        stand = self.layout.stand_by_id(f["stand"])
        yield from self._depart_from_stand(f, ac, stand)

    def operate_departure(self, ac_type=None, stand=None):
        """A departure that starts already parked (used to seed the apron)."""
        ac = ac_type or fleet.pick_type(self.layout.fleet_mix, self.rng)
        if stand is None:
            stand = self.stands.free_stand(ac)
            if stand is None:
                return
        f = self._new_flight("DEP", ac, stand, ctl=self.assign_runway(ac, "DEP"))
        yield from self.stands.occupy(f["id"], stand.id)
        f["lat"], f["lng"] = stand.pos
        f["heading"] = stand.heading_deg
        f["status"] = "scheduled"
        yield self.env.timeout(self.rng.uniform(5, 90))
        yield from self._depart_from_stand(f, ac, stand)

    def _depart_from_stand(self, f, ac, stand):
        ctl = self.controller_for(f)
        fid = f["id"]
        ready_t = self.env.now

        # --- ground stop / ATC flow control ------------------------------
        while self.ground_stop:
            yield from self._hold_position(f, 15, "ground_stop", self.ground_stop_reason or "ground stop")

        # --- plan the route, waiting if the runway direction is unusable --
        # This wait is capped, unlike the ground-stop wait above it. A ground
        # stop or bad weather is time-bounded - it always clears on its own
        # (see _auto() callbacks in inject_disruption) - so waiting for it
        # indefinitely is correct. "No hold point gives this aircraft enough
        # runway" is a different kind of condition: for a fixed airport and a
        # fixed active runway direction, if it's not solvable now it will
        # never become solvable by waiting, only by the wind changing. A
        # retry cap with a graceful cancellation is the difference between
        # that showing up as one cancelled flight and freed stand, or as a
        # stand lost for the rest of the session - which is exactly what
        # happened before core/airports/vabo.py's A4 station was moved to
        # match A1's setback (see the comment there): an A321 needing 2394 m
        # of a 2472 m runway had no legal departure point whenever the wind
        # put runway 22 into use, and every aircraft that turned around into
        # that condition held its stand forever, one at a time, until the
        # apron was full and nothing could arrive either.
        hold_node, route = self._plan_departure_route(f, stand)
        route_wait_attempts = 0
        while hold_node is None:
            route_wait_attempts += 1
            if route_wait_attempts > 15:  # 15 * 20s = 5 sim-minutes
                self.metrics["cancelled_departures"] += 1
                f["hold_reason"] = "no legal departure point on this runway direction"
                self.stands.vacate(fid)
                self._finish(fid, "despawned")
                return
            yield from self._hold_position(f, 20, "scheduled", "awaiting usable runway")
            if self.ground_stop:
                continue
            hold_node, route = self._plan_departure_route(f, stand)

        # --- pushback: only the stand lead-in, not the whole route --------
        # Acquiring the entire taxi route before being allowed to move was the
        # second gridlock cause (see _taxi_incremental's docstring): with a
        # full apron, every ready departure needed to lock every segment of a
        # shared lane before any of them could take a first step, so none of
        # them ever did. Pushback now takes only the pavement it physically
        # occupies - the stand lead-in and the lane junction it backs onto -
        # and the taxi out acquires the rest a segment at a time.
        # Take the whole clearance before moving. Anything acquired outside
        # this single canonical-order acquisition - even just the stand
        # lead-in for the pushback - is a lock held out of order, which is
        # exactly how the head-on apron deadlock got in.
        # All-or-nothing, for the same reason as the taxi clearance above: a
        # partial acquisition here holds apron edges while queueing for the
        # rest of the route, which deadlocks departures against each other.
        f["status"] = "scheduled"
        f["hold_reason"] = "awaiting pushback clearance"
        push_keys = self.ground.route_keys(route)
        while not self.ground.try_acquire(fid, push_keys):
            yield self.env.timeout(10)
        f["hold_reason"] = None

        pts = route.points()
        # The first leg is the lead-in line: reverse it at walking pace, which
        # is a pushback, then taxi forward from the taxilane.
        push_end = min(len(pts) - 1, 2)
        f["status"] = "pushback"
        f["cleared_to"] = "pushback approved"
        push_points = pts[:push_end + 1]
        start_heading = f["heading"]
        yield from self._traverse(
            f, push_points, 1, ac.pushback_speed_kt, 0.5, accel=0.25, decel=0.4,
            alt_fn=lambda p, s, t: 0.0, pitch_fn=lambda p: 0.0,
            roll_fn=lambda p: 0.0,
        )
        # Tail-first push: keep the nose pointing at the stand throughout.
        f["heading"] = start_heading
        yield from self._hold_position(f, 20, "pushback", "disconnecting tug")

        # --- taxi out to the holding point --------------------------------
        # Pushback already covered the stand lead-in (leg 0), so the rolling
        # taxi picks up from leg 1 with those resources already in hand.
        taxi_start = self.env.now
        f["status"] = "taxi_out"
        f["cleared_to"] = f"taxi to {hold_node.label or hold_node.id} via {route.describe()}"
        f["hold_reason"] = None
        taxi_kt = self._taxi_speed(ac)
        yield from self._taxi_whole_route(
            f, route, taxi_kt, "taxi_out", v_entry=3, v_exit=3,
            skip_first_leg=True)
        self.metrics["total_taxi_out_s"] += self.env.now - taxi_start
        self.metrics["taxi_out_samples"] += 1

        # Release the taxiways behind us so the queue can close up, but keep the
        # stretch we are physically parked on. Releasing that too was letting a
        # follower taxi into the aircraft holding short of the runway.
        link_edge = self.layout.edge_between(hold_node.id, self._runway_entry_for(hold_node))
        standing_on = route.edges[-1] if route.edges else None
        keep = set()
        for edge in (link_edge, standing_on):
            if edge is not None:
                keep.update(self.ground.edge_keys(edge))
        keep.add(("N", hold_node.id))
        self.ground.release_all(fid, keep=keep)

        # --- hold short ---------------------------------------------------
        f["status"] = "hold_short"
        f["cleared_to"] = f"holding short {ctl.active_end_ident} at {hold_node.label}"
        f["heading"] = bearing_deg(hold_node.pos, self.layout.nodes[self._runway_entry_for(hold_node)].pos)
        if fid not in ctl.departure_queue:
            ctl.departure_queue.append(fid)

        while True:
            if self.ground_stop:
                f["hold_reason"] = self.ground_stop_reason or "ground stop"
                yield self.env.timeout(10)
                continue
            ok, reason = ctl.takeoff_allowed(self.weather)
            if not ok:
                f["hold_reason"] = reason
                yield self.env.timeout(10)
                continue
            if ctl.active_end_ident != f["runway"]:
                # Runway direction changed while we were holding: re-plan.
                f["hold_reason"] = "runway change - re-routing"
                f["runway"] = ctl.active_end_ident
                new_hold, new_route = self._plan_departure_route(f, stand)
                if new_hold and new_hold.id != hold_node.id:
                    ctl.departure_queue.remove(fid)
                    self.ground.release_all(fid)
                    new_keys = self.ground.route_keys(new_route)
                    while not self.ground.try_acquire(fid, new_keys):
                        yield self.env.timeout(10)
                    yield from self._traverse(f, new_route.points(), 3, taxi_kt, 3,
                                              alt_fn=lambda p, s, t: 0.0)
                    hold_node = new_hold
                    ctl.departure_queue.append(fid)
                continue
            break

        f["hold_reason"] = None
        f["delay_min"] = round((self.env.now - ready_t) / 60.0, 1)

        # --- runway: line up, wait out the separation, roll ---------------
        # Arrivals outrank departures, which at a busy single-runway airport
        # would starve the departure queue forever. Real towers interleave, so
        # a departure's priority escalates the longer it has been holding: after
        # a few minutes it outranks an inbound, and the tower slots it in.
        req = None
        waited = 0.0
        while True:
            priority = max(atc_mod.PRIORITY_EMERGENCY + 1,
                           atc_mod.PRIORITY_DEPARTURE - waited / 25.0)
            req = ctl.resource.request(priority=priority)
            outcome = yield req | self.env.timeout(30)
            if req in outcome:
                break
            req.cancel()
            ctl.resource.release(req)
            waited += 30
            f["hold_reason"] = f"number {ctl.departure_queue.index(fid) + 1 if fid in ctl.departure_queue else 1} for departure"
            yield self.env.timeout(1)
        gap = ctl.separation_wait_s(ac, "DEP")
        entry_id = self._runway_entry_for(hold_node)
        entry = self.layout.nodes[entry_id]
        if link_edge is not None:
            link_keys = self.ground.edge_keys(link_edge)
            while not self.ground.try_acquire(fid, link_keys):
                yield self.env.timeout(5)

        f["status"] = "lineup"
        f["cleared_to"] = f"line up and wait {ctl.active_end_ident}"
        ctl.occupy(fid, "DEP", ac)
        yield from self._traverse(
            f, [hold_node.pos, entry.pos], 3, 10, 1, accel=0.6, decel=0.8,
            alt_fn=lambda p, s, t: 0.0)
        end = ctl.active_end()
        f["heading"] = end.heading_deg
        if gap > 0:
            yield from self._hold_position(f, gap, "lineup", f"wake separation {int(gap)}s")
        if fid in ctl.departure_queue:
            ctl.departure_queue.remove(fid)

        # --- takeoff roll --------------------------------------------------
        f["status"] = "takeoff_roll"
        f["cleared_to"] = f"cleared for takeoff {end.ident}"
        f["hold_reason"] = None
        rotate_point = destination(entry.pos, end.heading_deg,
                                   min(ac.todr_m * 0.78,
                                       max(600.0, distance_m(entry.pos, self._far_threshold(ctl)) - 350)))
        yield from self._traverse(
            f, [entry.pos, rotate_point], 5, ac.v_rotate_kt, ac.v_rotate_kt,
            accel=2.0, decel=2.0,
            alt_fn=lambda p, s, t: 0.0,
            pitch_fn=lambda p: 0.0 if p < 0.9 else 4.0,
            roll_fn=lambda p: 0.0,
        )

        # --- rotate and climb out -----------------------------------------
        f["status"] = "climb"
        f["on_ground"] = False
        dep_fix = destination(end.threshold, end.heading_deg, DEPARTURE_FIX_M)
        dep_fix = destination(dep_fix, (end.heading_deg + 25) % 360, 2600)
        climb_rate_ms = ac.climb_rate_fpm * FPM
        released = {"done": False}

        def _release_when_clear(progress, s, total):
            if not released["done"] and s > 900:
                released["done"] = True
                ctl.vacate(fid, ac, "DEP")
                ctl.resource.release(req)
                self.ground.release_all(fid)

        yield from self._traverse(
            f, [rotate_point, dep_fix], ac.v_rotate_kt, ac.climb_speed_kt, ac.climb_speed_kt,
            accel=1.4, decel=1.0,
            alt_fn=lambda p, s, t: min(DEPARTURE_ALT_M, (s / max(1.0, ac.v2_kt * KT)) * climb_rate_ms),
            pitch_fn=lambda p: 14.0 if p < 0.35 else 9.0 if p < 0.7 else 5.0,
            on_progress=_release_when_clear,
        )
        if not released["done"]:
            ctl.vacate(fid, ac, "DEP")
            ctl.resource.release(req)
            self.ground.release_all(fid)

        self.stands.vacate(fid)
        self.metrics["departures"] += 1
        self.metrics["total_departure_delay_min"] += f["delay_min"]
        f["pitch"] = 0.0
        f["roll"] = 0.0
        self._finish(fid, "airborne")

    def _runway_entry_for(self, hold_node):
        for edge in self.layout.edges.values():
            if edge.kind == "runway_link" and hold_node.id in (edge.u, edge.v):
                return edge.v if edge.u == hold_node.id else edge.u
        return hold_node.id

    def _far_threshold(self, ctl=None):
        ctl = ctl or self.runway_ctl
        end = ctl.active_end()
        return ctl.runway.opposite(end.ident).threshold

    # =====================================================================
    # Apron seeding
    # =====================================================================
    def _seed_apron(self):
        """Park a realistic number of aircraft before the first frame, so the
        twin opens on a working airport rather than an empty one."""
        n = max(1, int(len(self.layout.stands) * INITIAL_PARKED_FRACTION))
        # Assign distinct stands up front. Asking the stand manager for a free
        # stand in a loop would hand out the same one every time, because none
        # of these processes has started - and therefore actually taken a
        # stand - yet.
        pool = [s for s in self.layout.stands]
        self.rng.shuffle(pool)
        for stand in pool[:n]:
            ac = fleet.pick_type(self.layout.fleet_mix, self.rng)
            if not fleet.fits_stand(ac, stand.max_category):
                ac = fleet.get("AT76")
            self.env.process(self.operate_departure(ac, stand))

    # =====================================================================
    # Bi-directional control surface (called from FastAPI)
    # =====================================================================
    def inject_disruption(self, kind, duration_minutes=15.0, label=None, target=None):
        duration_s = max(0.0, float(duration_minutes)) * 60.0
        now = self.env.now
        msg = None

        if kind in ("runway_closure", "maintenance_delay"):
            for c in self.runway_ctls.values():
                c.close_for(duration_s)
            msg = (f"All runways ({', '.join(self.runway_ctls)}) closed for "
                   f"{duration_minutes:.0f} min - arrivals will hold or divert")

        elif kind == "ground_stop":
            self.ground_stop = True
            self.ground_stop_reason = label or "ATC ground stop"
            self.env.process(self._auto(lambda: setattr(self, "ground_stop", False), duration_s))
            msg = f"Ground stop: no departures for {duration_minutes:.0f} min"

        elif kind == "fog":
            self._set_weather_effect(
                "fog", {"visibility_m": 350, "ceiling_ft": 100, "condition": "FOG"}, duration_s)
            end = self.runway_ctl.active_end()
            msg = (f"Fog: RVR 350 m, ceiling 100 ft. {self.layout.icao} RWY {end.ident} is "
                   f"{end.ils_category.replace('_', ' ')} - arrivals below minima")

        elif kind == "low_visibility":
            self._set_weather_effect(
                "low_visibility", {"visibility_m": 900, "ceiling_ft": 250, "condition": "MIST"}, duration_s)
            msg = f"Low visibility procedures for {duration_minutes:.0f} min"

        elif kind == "high_wind":
            self._set_weather_effect(
                "high_wind",
                {"wind_kt": 38, "wind_dir_deg": (self.runway_ctl.active_end().heading_deg + 95) % 360,
                 "condition": "HIGH_WIND"},
                duration_s)
            msg = "Crosswind 38 kt across the runway - beyond code C limits"

        elif kind == "wind_shift":
            end = self.runway_ctl.active_end()
            # No duration_s here (None) - this one is permanent until a
            # "clear" is issued, matching the previous behaviour.
            self._set_weather_effect(
                "wind_shift", {"wind_dir_deg": end.heading_deg % 360, "wind_kt": 18,
                               "condition": "WIND_SHIFT"}, None)
            msg = "Wind shift - runway direction under review"

        elif kind == "thunderstorm":
            self._set_weather_effect(
                "thunderstorm",
                {"visibility_m": 2200, "ceiling_ft": 700, "wind_kt": 28, "wet": True,
                 "condition": "THUNDERSTORM"},
                duration_s)
            for c in self.runway_ctls.values():
                c.close_for(min(duration_s, 900))
            msg = "Thunderstorm overhead - runway suspended, surface wet"

        elif kind == "taxiway_closure":
            name = target or "A"
            closed = self.ground.close_taxiway(name, True)
            self.env.process(self._auto(lambda: self.ground.close_taxiway(name, False), duration_s))
            msg = f"Taxiway {name} closed ({len(closed)} segments) - traffic re-routing"

        elif kind == "stand_closure":
            msg = "Stand closure is not implemented yet"

        elif kind == "emergency_arrival":
            self.env.process(self._emergency_arrival())
            msg = "Emergency aircraft inbound - priority landing, all traffic held"

        elif kind == "clear":
            for c in self.runway_ctls.values():
                c.reopen()
            self.ground_stop = False
            self.ground_stop_reason = None
            self.active_weather_effects = {}
            self._weather_effect_tokens = {}
            self._recompute_weather()
            for name in {e.name for e in self.layout.edges.values()}:
                self.ground.close_taxiway(name, False)
            msg = "All disruptions cleared - normal operations resumed"

        else:
            msg = f"Unknown disruption '{kind}' ignored"

        entry = {"time": round(now, 1), "type": kind, "label": label or msg}
        self.active_disruptions.insert(0, entry)
        self.active_disruptions = self.active_disruptions[:DISRUPTION_LOG_LIMIT]
        return entry

    def _auto(self, fn, delay_s):
        yield self.env.timeout(delay_s)
        fn()

    # Fixed, deterministic combination order so the same set of active
    # effects always produces the same "A + B + C" condition label
    # regardless of which order they were clicked in.
    _WEATHER_EFFECT_ORDER = ("fog", "low_visibility", "wind_shift", "high_wind", "thunderstorm")

    def _set_weather_effect(self, kind, fields, duration_s):
        """Register (or refresh) one named weather effect and recombine.

        Effects are additive and independent, keyed by `kind`: injecting
        `high_wind` while `fog` is still active keeps fog's reduced
        visibility instead of clobbering it with clear-air defaults, and
        each effect expires on its own timer. Previously every weather
        disruption shared one `self.weather` dict and one `_clear_weather`
        callback, so a later 10-minute thunderstorm would reset a still-
        running 20-minute fog back to clear skies ten minutes early - and
        the single `condition` field could only ever show the most recently
        injected effect's name, even while an earlier one was still active.
        """
        self._weather_effect_seq += 1
        token = self._weather_effect_seq
        self._weather_effect_tokens[kind] = token
        self.active_weather_effects[kind] = dict(fields)
        self._recompute_weather()
        if duration_s:
            self.env.process(self._auto_clear_weather_effect(kind, token, duration_s))

    def _auto_clear_weather_effect(self, kind, token, delay_s):
        yield self.env.timeout(delay_s)
        # Only remove it if this is still the activation that scheduled this
        # timer - if the same effect was re-triggered (refreshing/extending
        # it) after this timer was set, an older timer must not clear the
        # newer activation out from under it.
        if self._weather_effect_tokens.get(kind) == token:
            self.active_weather_effects.pop(kind, None)
            self._weather_effect_tokens.pop(kind, None)
            self._recompute_weather()

    def _recompute_weather(self):
        """Recombine every still-active weather effect into `self.weather`.

        Starts from the airport's clear-sky baseline, then layers each
        active effect on top: visibility and ceiling take the worst (lowest)
        value any active effect sets, "wet" is true if any effect sets it,
        and the displayed wind is whichever active effect is pushing hardest
        (highest wind_kt) since two effects can't both dictate the wind
        direction at once. `condition` becomes every active effect's label
        joined together (e.g. "FOG + HIGH_WIND + THUNDERSTORM"), or "CLEAR"
        with nothing active.
        """
        base_wind_dir = self.layout.default_wind_dir_deg
        base_wind_kt = self.layout.default_wind_kt

        if not self.active_weather_effects:
            self.weather.clear()
            self.weather.update(CLEAR_WEATHER)
            self.weather["wind_dir_deg"] = base_wind_dir
            self.weather["wind_kt"] = base_wind_kt
            return

        visibility_m = CLEAR_WEATHER["visibility_m"]
        ceiling_ft = CLEAR_WEATHER["ceiling_ft"]
        wind_kt = base_wind_kt
        wind_dir_deg = base_wind_dir
        dominant_wind_kt = -1.0
        wet = False
        labels = []

        ordered_kinds = [k for k in self._WEATHER_EFFECT_ORDER if k in self.active_weather_effects]
        # Any future/unknown kind (defensive - keeps a typo from silently
        # dropping an effect) still gets combined in, just after the known
        # ones, in whatever order it was inserted.
        ordered_kinds += [k for k in self.active_weather_effects if k not in ordered_kinds]

        for kind in ordered_kinds:
            eff = self.active_weather_effects[kind]
            if "visibility_m" in eff:
                visibility_m = min(visibility_m, eff["visibility_m"])
            if "ceiling_ft" in eff:
                ceiling_ft = min(ceiling_ft, eff["ceiling_ft"])
            if eff.get("wet"):
                wet = True
            if "wind_kt" in eff and eff["wind_kt"] > dominant_wind_kt:
                dominant_wind_kt = eff["wind_kt"]
                wind_kt = eff["wind_kt"]
                wind_dir_deg = eff.get("wind_dir_deg", wind_dir_deg)
            if eff.get("condition"):
                labels.append(eff["condition"])

        self.weather.clear()
        self.weather.update(CLEAR_WEATHER)
        self.weather.update({
            "visibility_m": visibility_m,
            "ceiling_ft": ceiling_ft,
            "wind_kt": wind_kt,
            "wind_dir_deg": wind_dir_deg,
            "wet": wet,
            "condition": " + ".join(labels) if labels else "CLEAR",
        })

    def _clear_weather(self):
        """Drop every active weather effect and return to clear skies."""
        self.active_weather_effects = {}
        self._weather_effect_tokens = {}
        self._recompute_weather()

    def _emergency_arrival(self):
        ac = fleet.get("A20N")
        yield self.env.process(self.operate_arrival(ac, emergency=True))

    # =====================================================================
    # Snapshot for the wire
    # =====================================================================
    def review_runway_direction(self):
        """Re-evaluate the runway in use against the current wind."""
        for _c in self.runway_ctls.values():
            _c.select_active_end(self.weather["wind_dir_deg"], self.weather["wind_kt"],
                                 self.weather.get("wet", False))
        ident, assessment, usable = self.runway_ctl.select_active_end(
            self.weather["wind_dir_deg"], self.weather["wind_kt"], self.weather.get("wet", False))
        return ident, assessment, usable

    def status_snapshot(self):
        active = [f for f in self.flights.values()
                  if f["status"] not in ("airborne", "diverted", "despawned")]
        avg_risk = sum(f["risk"] for f in active) / len(active) if active else 0.2
        _, assessment, wind_ok = self.review_runway_direction()
        taxi_avg = (self.metrics["total_taxi_out_s"] / self.metrics["taxi_out_samples"]
                    if self.metrics["taxi_out_samples"] else 0.0)
        return {
            "airport": {
                "icao": self.layout.icao,
                "iata": self.layout.iata,
                "name": self.layout.name,
                "city": self.layout.city,
                "slug": self.layout.slug,
            },
            "runway": self.runway_ctl.snapshot(),
            "runways": [c.snapshot() for c in self.runway_ctls.values()],
            "wind": assessment,
            "wind_usable": wind_ok,
            "weather": self.weather,
            "ground_stop": self.ground_stop,
            "ground_stop_reason": self.ground_stop_reason,
            "ground": self.ground.snapshot(),
            "stands": self.stands.snapshot(),
            "separation": self.monitor.snapshot(),
            "queue_depth": self.queue_depth(),
            "airborne": self.airborne_count(),
            "congestion_tier": registry.congestion_tier(len(active), round(avg_risk, 3)),
            "network_criticality": round(registry.network_criticality(self.layout.icao), 4),
            "macro_delay_risk": round(registry.predict_macro_delay_risk(), 3),
            "ground_stop_probability": round(registry.predict_ground_stop_probability(
                self.weather["visibility_m"], self.weather["ceiling_ft"], self.weather["wind_kt"]), 3),
            "local_hour": round(self.local_hour(), 2),
            "metrics": {
                **self.metrics,
                "avg_taxi_out_s": round(taxi_avg, 1),
                "avg_departure_delay_min": round(
                    self.metrics["total_departure_delay_min"] / max(1, self.metrics["departures"]), 2),
            },
            "disruptions": self.active_disruptions,
        }
