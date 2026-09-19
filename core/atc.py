"""
AeroTwin Air Traffic Control
============================
The controller layer. Everything that decides *who may move where, and when*
lives here; `core.twin_sim` only decides what that looks like in motion.

The first build let aircraft overlap on the ground and occasionally on final,
because position was animated on a timer and nothing ever said no. Here every
piece of pavement is a resource with an owner, and an aircraft physically
cannot be given a position it has not been cleared into:

  * GroundNetwork  - one SimPy resource per taxiway edge, capacity 1. Two
    aircraft can never occupy the same stretch of taxiway. Routes are acquired
    in a fixed global edge order, which makes ground deadlock impossible (the
    classic resource-hierarchy argument: no cycle can form in the wait-for
    graph), and released progressively behind the aircraft so followers can
    close up into a normal departure queue.

  * RunwayController - a priority resource guarding the runway, plus wake
    turbulence separation, plus low-visibility and crosswind limits. Arrivals
    outrank departures; an emergency outranks everything. A departure holds the
    runway from line-up until it is airborne and clear; an arrival holds it
    from short final until it has vacated onto a turn-off, which is what makes
    "landing while someone is rolling" impossible rather than unlikely.

  * StandManager - stands are resources too, matched to aircraft category, so a
    777 never parks on the ATR bay and two aircraft never share a stand.

  * SeparationMonitor - an independent audit that measures actual distances
    every tick and counts violations. It is deliberately *not* used to prevent
    anything; it exists so the twin can prove the locking above is working, and
    the count it reports is shown in the UI.
"""
from __future__ import annotations

import itertools
import math

import simpy

from core import aircraft as fleet
from core.geo import crosswind_component, distance_m

# Runway occupancy priorities (lower value = served first)
PRIORITY_EMERGENCY = -10
PRIORITY_ARRIVAL = 0
PRIORITY_DEPARTURE = 10

# Wind limits
MAX_TAILWIND_KT = 10.0
MAX_CROSSWIND_KT = 33.0        # dry runway limit for a code C narrow-body
MAX_CROSSWIND_WET_KT = 25.0

# Low-visibility procedure thresholds
LVP_TAKEOFF_VISIBILITY_M = 550
LVP_TRIGGER_VISIBILITY_M = 1500

# Minimum separation the monitor audits against (metres)
MIN_GROUND_SEPARATION_M = 55.0
MIN_AIRBORNE_SEPARATION_M = 300.0

# States in which an aircraft is stationary on a stand and therefore outside
# the separation audit entirely.
PARKED_STATUSES = {"parked", "scheduled", "turnaround", "despawned", "diverted"}


class GroundNetwork:
    """Single-occupancy locking over the taxi graph.

    Two things are locked, not one. Locking only the *edges* leaves junctions
    unprotected: an aircraft stopped at the end of taxiway B and an aircraft
    taxiing through the same junction on taxiway A hold different edges and can
    therefore stand in the same place. So every junction *node* is a resource
    too, and a taxi clearance takes the edges and the nodes together.

    Both live in one keyspace ("E", edge_id) / ("N", node_id) with a single
    canonical ordering, and every aircraft acquires its whole clearance in that
    order. That is the standard resource-hierarchy argument for deadlock
    freedom: no cycle can form in the wait-for graph, so the airfield can jam
    up with traffic but can never wedge.
    """

    def __init__(self, env: simpy.Environment, layout):
        self.env = env
        self.layout = layout
        self.locks = {}
        for eid in layout.edges:
            self.locks[("E", eid)] = simpy.Resource(env, capacity=1)
        for nid, node in layout.nodes.items():
            # Stand nodes are governed by the stand resource instead.
            if node.kind != "stand":
                self.locks[("N", nid)] = simpy.Resource(env, capacity=1)
        self.order = {key: i for i, key in enumerate(sorted(self.locks, key=lambda k: (k[0], k[1])))}
        self.occupant = {key: None for key in self.locks}
        self.closed_edges = set()
        self._held = {}         # flight_id -> {key: request}

    # -- keys --------------------------------------------------------------
    def route_keys(self, route):
        """Every resource a taxi clearance along this route needs."""
        keys = [("E", e.id) for e in route.edges]
        keys += [("N", nid) for nid in route.node_ids if ("N", nid) in self.locks]
        return keys

    def edge_keys(self, edge):
        keys = [("E", edge.id)]
        for nid in (edge.u, edge.v):
            if ("N", nid) in self.locks:
                keys.append(("N", nid))
        return keys

    def _sorted(self, keys):
        return sorted({k for k in keys if k in self.locks}, key=lambda k: self.order[k])

    # -- clearance ---------------------------------------------------------
    def acquire(self, flight_id, keys):
        """Generator: take every resource in the clearance, in canonical order.

        The caller is stationary while this is pending - that is an aircraft
        holding position waiting for taxi clearance, which is what should
        happen when the route ahead is occupied.

        The canonical ordering is load-bearing, not cosmetic. Acquiring in a
        fixed global order is the entire reason the ground network cannot
        deadlock (the standard resource-hierarchy argument), and it only
        holds if EVERY acquisition anywhere follows it - including
        incremental ones. Acquiring a route piecemeal in travel order breaks
        it outright: two aircraft taxiing toward each other along the same
        apron lane acquire the same segments in opposite orders, each ends up
        holding what the other needs next, and the pair wedges permanently.
        That is not hypothetical - it is what happened when this was tried,
        and why `reserve_corridor` below exists instead.
        """
        held = self._held.setdefault(flight_id, {})
        for key in self._sorted(keys):
            if key in held:
                continue
            req = self.locks[key].request()
            yield req
            held[key] = req
            self.occupant[key] = flight_id

    def acquire_route(self, flight_id, route):
        yield from self.acquire(flight_id, self.route_keys(route))

    def free(self, keys):
        return all(self.locks[k].count == 0 for k in self._sorted(keys))

    def try_acquire(self, flight_id, keys):
        """Non-blocking all-or-nothing grab. Returns True if the whole set was free."""
        wanted = self._sorted(keys)
        held = self._held.setdefault(flight_id, {})
        if not all(k in held or self.locks[k].count == 0 for k in wanted):
            return False
        for key in wanted:
            if key in held:
                continue
            req = self.locks[key].request()
            held[key] = req
            self.occupant[key] = flight_id
        return True

    def release(self, flight_id, key):
        held = self._held.get(flight_id, {})
        req = held.pop(key, None)
        if req is not None:
            self.locks[key].release(req)
            if self.occupant.get(key) == flight_id:
                self.occupant[key] = None

    def release_all(self, flight_id, keep=()):
        keep = set(keep)
        for key in list(self._held.get(flight_id, {})):
            if key not in keep:
                self.release(flight_id, key)
        if not self._held.get(flight_id):
            self._held.pop(flight_id, None)

    def holds(self, flight_id):
        return list(self._held.get(flight_id, {}))

    # -- closures ----------------------------------------------------------
    def close_edge(self, edge_id, closed=True):
        edge = self.layout.edges.get(edge_id)
        if edge is None:
            return False
        edge.closed = closed
        if closed:
            self.closed_edges.add(edge_id)
        else:
            self.closed_edges.discard(edge_id)
        return True

    def close_taxiway(self, name, closed=True):
        """Close every segment of a named taxiway. Routing simply stops
        returning those edges, so traffic re-routes rather than driving through."""
        hit = [e.id for e in self.layout.edges.values()
               if e.name == name and e.kind not in ("stand_lead", "runway_link")]
        for eid in hit:
            self.close_edge(eid, closed)
        return hit

    def snapshot(self):
        busy = {k[1]: occ for k, occ in self.occupant.items() if occ and k[0] == "E"}
        return {
            "occupied_edges": busy,
            "closed_edges": sorted(self.closed_edges),
            "utilisation": round(len(busy) / max(1, len(self.layout.edges)), 3),
        }


class StandManager:
    """Stands as resources, allocated by aircraft category."""

    def __init__(self, env: simpy.Environment, layout):
        self.env = env
        self.layout = layout
        self.resources = {s.id: simpy.Resource(env, capacity=1) for s in layout.stands}
        self.occupant = {s.id: None for s in layout.stands}
        self._held = {}

    def candidates(self, ac_type):
        """Stands that physically fit, contact bays preferred."""
        fits = [s for s in self.layout.stands if fleet.fits_stand(ac_type, s.max_category)]
        return sorted(fits, key=lambda s: (not s.contact, s.id))

    def free_stand(self, ac_type):
        for s in self.candidates(ac_type):
            if self.resources[s.id].count == 0:
                return s
        return None

    def occupy(self, flight_id, stand_id):
        """Generator: take the stand (waits if someone is still on it)."""
        req = self.resources[stand_id].request()
        yield req
        self._held.setdefault(flight_id, {})[stand_id] = req
        self.occupant[stand_id] = flight_id

    def vacate(self, flight_id, stand_id=None):
        held = self._held.get(flight_id, {})
        for sid in list(held) if stand_id is None else [stand_id]:
            req = held.pop(sid, None)
            if req is not None:
                self.resources[sid].release(req)
                if self.occupant.get(sid) == flight_id:
                    self.occupant[sid] = None
        if not held:
            self._held.pop(flight_id, None)

    def snapshot(self):
        return {
            "total": len(self.resources),
            "occupied": sum(1 for v in self.occupant.values() if v),
            "by_stand": dict(self.occupant),
        }


class RunwayController:
    """The runway: one aircraft at a time, with real sequencing rules."""

    def __init__(self, env: simpy.Environment, layout, runway):
        self.env = env
        self.layout = layout
        self.runway = runway
        self.resource = simpy.PriorityResource(env, capacity=1)
        self.active_end_ident = runway.ends[0].ident
        self.closed_until = 0.0
        self.occupant = None
        self.occupant_role = None
        self.last_release_t = -1e9
        self.last_type = None
        self.last_role = None
        self.required_gap_s = 0.0
        self._ticket = itertools.count()
        # Sequencing lists, purely for display - the actual order is enforced
        # by the priority resource, this is the strip board the tower sees.
        self.departure_queue = []   # [flight_id]
        self.arrival_sequence = []  # [flight_id]

    # -- runway in use -----------------------------------------------------
    def wind_assessment(self, wind_dir_deg, wind_kt, wet=False):
        """Per-end headwind/crosswind, and whether the end is usable."""
        limit = MAX_CROSSWIND_WET_KT if wet else MAX_CROSSWIND_KT
        out = {}
        for end in self.runway.ends:
            head, cross = crosswind_component(wind_dir_deg, wind_kt, end.heading_deg)
            out[end.ident] = {
                "headwind_kt": round(head, 1),
                "crosswind_kt": round(cross, 1),
                "usable": (-head) <= MAX_TAILWIND_KT and cross <= limit,
                "limit_kt": limit,
            }
        return out

    def select_active_end(self, wind_dir_deg, wind_kt, wet=False):
        """Pick the runway in use from the wind. Never switches while occupied."""
        assessment = self.wind_assessment(wind_dir_deg, wind_kt, wet)
        usable = [i for i, a in assessment.items() if a["usable"]]
        if not usable:
            return self.active_end_ident, assessment, False
        best = max(usable, key=lambda i: assessment[i]["headwind_kt"])
        if best != self.active_end_ident and self.occupant is None:
            # Only swap for a meaningful gain, so a gusting wind does not make
            # the tower flip the runway every thirty seconds.
            gain = assessment[best]["headwind_kt"] - assessment[self.active_end_ident]["headwind_kt"]
            if gain > 4.0 or not assessment[self.active_end_ident]["usable"]:
                self.active_end_ident = best
        return self.active_end_ident, assessment, True

    def active_end(self):
        return self.runway.end(self.active_end_ident)

    # -- availability ------------------------------------------------------
    def is_closed(self):
        return self.env.now < self.closed_until

    def close_for(self, seconds):
        self.closed_until = max(self.closed_until, self.env.now + seconds)

    def reopen(self):
        self.closed_until = 0.0

    def landing_allowed(self, weather):
        """Can an arrival be accepted on the active end right now?"""
        end = self.active_end()
        if self.is_closed():
            return False, "runway closed"
        if weather["visibility_m"] < end.minima_visibility_m:
            return False, f"below {end.ils_category or 'NON-PRECISION'} minima (RVR)"
        if weather["ceiling_ft"] < end.minima_ceiling_ft:
            return False, "below minima (ceiling)"
        assessment = self.wind_assessment(weather["wind_dir_deg"], weather["wind_kt"],
                                          weather.get("wet", False))
        if not assessment[end.ident]["usable"]:
            return False, "wind out of limits"
        return True, "cleared to land"

    def takeoff_allowed(self, weather):
        end = self.active_end()
        if self.is_closed():
            return False, "runway closed"
        if weather["visibility_m"] < LVP_TAKEOFF_VISIBILITY_M:
            return False, "below LVP takeoff minima"
        assessment = self.wind_assessment(weather["wind_dir_deg"], weather["wind_kt"],
                                          weather.get("wet", False))
        if not assessment[end.ident]["usable"]:
            return False, "wind out of limits"
        return True, "cleared for takeoff"

    def usable_length_from(self, hold_node):
        """Runway remaining ahead of a given holding point, for the active end.

        This is what decides whether an intersection departure is legal - the
        thing that makes A2 a real option for an ATR and never for an A321.
        """
        end = self.active_end()
        along = distance_m(end.threshold, hold_node.pos)
        # Project onto the runway: the hold node sits beside the runway, so use
        # its along-track distance from the active threshold.
        opposite = self.runway.opposite(end.ident)
        total = self.runway.length_m
        d_from_far = distance_m(opposite.threshold, hold_node.pos)
        # Nodes abeam a point have ~equal cross-track error at both ends, so the
        # along-track share is recovered from the difference of the two ranges.
        along_track = (total + (along ** 2 - d_from_far ** 2) / total) / 2
        return max(0.0, total - along_track)

    # -- occupancy ---------------------------------------------------------
    def request(self, flight_id, role, emergency=False):
        """Priority request for the runway. Arrivals beat departures."""
        priority = (PRIORITY_EMERGENCY if emergency
                    else PRIORITY_ARRIVAL if role == "ARR" else PRIORITY_DEPARTURE)
        return self.resource.request(priority=priority, preempt=False)

    def separation_wait_s(self, ac_type, role):
        """Remaining seconds of wake/runway separation owed before this
        aircraft may begin its roll or cross the threshold."""
        if self.last_type is None:
            return 0.0
        if role == "DEP":
            need = fleet.departure_separation_s(self.last_type, ac_type)
        else:
            need = fleet.arrival_separation_s(self.last_type, ac_type)
        # A departure behind an arrival only needs the runway vacated plus a
        # short buffer, not full wake spacing.
        if self.last_role == "ARR" and role == "DEP":
            need = min(need, 45)
        elapsed = self.env.now - self.last_release_t
        return max(0.0, need - elapsed)

    def occupy(self, flight_id, role, ac_type):
        self.occupant = flight_id
        self.occupant_role = role
        self.required_gap_s = 0.0

    def vacate(self, flight_id, ac_type, role):
        if self.occupant == flight_id:
            self.occupant = None
            self.occupant_role = None
        self.last_release_t = self.env.now
        self.last_type = ac_type
        self.last_role = role

    def snapshot(self):
        return {
            "name": self.runway.name,
            "active_end": self.active_end_ident,
            "heading_deg": round(self.active_end().heading_deg, 1),
            "length_m": round(self.runway.length_m),
            "ils": self.active_end().ils_category,
            "closed": self.is_closed(),
            "closed_remaining_s": max(0.0, round(self.closed_until - self.env.now, 1)),
            "occupant": self.occupant,
            "occupant_role": self.occupant_role,
            "departure_queue": list(self.departure_queue),
            "arrival_sequence": list(self.arrival_sequence),
            "waiting_for_runway": len(self.resource.queue),
        }


class SeparationMonitor:
    """Independent audit of the separation the locking above is supposed to give.

    This does not enforce anything. It measures, every broadcast frame, the
    closest pair of aircraft on the ground and in the air, and counts how often
    the twin's own rules were broken. A digital twin that claims to be
    conflict-free should be able to show its working; this is that evidence.
    """

    def __init__(self):
        self.ground_violations = 0
        self.airborne_violations = 0
        self.min_ground_m = float("inf")
        self.min_airborne_m = float("inf")
        self.runway_incursions = 0
        self.worst_pair = None

    def audit(self, flights, runway_controller=None):
        ground, air = [], []
        for f in flights:
            # Aircraft on stand are not a separation problem - stands are
            # deliberately close together and an aircraft on one is chocked.
            if f.get("status") in PARKED_STATUSES:
                continue
            (ground if (f.get("altitude") or 0) < 5 else air).append(f)

        for a, b in itertools.combinations(ground, 2):
            d = distance_m((a["lat"], a["lng"]), (b["lat"], b["lng"]))
            if d < self.min_ground_m:
                self.min_ground_m = d
                self.worst_pair = (a["id"], b["id"], round(d, 1))
            if d < MIN_GROUND_SEPARATION_M:
                self.ground_violations += 1

        for a, b in itertools.combinations(air, 2):
            d = distance_m((a["lat"], a["lng"]), (b["lat"], b["lng"]))
            vertical = abs((a.get("altitude") or 0) - (b.get("altitude") or 0))
            self.min_airborne_m = min(self.min_airborne_m, d)
            if d < MIN_AIRBORNE_SEPARATION_M and vertical < 120:
                self.airborne_violations += 1

        if runway_controller is not None:
            on_runway = [f for f in flights
                         if f.get("status") in ("lineup", "takeoff_roll", "landing_rollout", "touchdown")]
            if len(on_runway) > 1:
                self.runway_incursions += 1

    def snapshot(self):
        return {
            "ground_violations": self.ground_violations,
            "airborne_violations": self.airborne_violations,
            "runway_incursions": self.runway_incursions,
            "closest_ground_m": None if math.isinf(self.min_ground_m) else round(self.min_ground_m, 1),
            "closest_airborne_m": None if math.isinf(self.min_airborne_m) else round(self.min_airborne_m, 1),
            "closest_pair": self.worst_pair,
            "min_ground_standard_m": MIN_GROUND_SEPARATION_M,
        }
