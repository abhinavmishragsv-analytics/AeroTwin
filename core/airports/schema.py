"""
AeroTwin Airport Schema
=======================
The structural description of an aerodrome, independent of any one airport.

An airport definition is *structure*, not pixels: runway thresholds, a taxi
graph (nodes + edges), stands, and building massing. Everything the 3D client
draws - pavement polygons, centreline dashes, piano keys, hold-short bars,
stand lead-in lines, edge lights - is derived from this structure by
`core.airports.geometry`, so adding Delhi or Mumbai later means describing
their thresholds and taxi graph, not redrawing an airfield by hand.

The taxi graph is the part that makes conflict-free ground movement possible.
Each `TaxiEdge` is a physical stretch of pavement that exactly one aircraft may
occupy at a time; `core.atc` turns each one into a SimPy resource and `core.routing`
plans stand-to-runway paths across them. Ground collisions are therefore not
"avoided" by tuning timings until they stop looking wrong - they are impossible
by construction, because two aircraft can never hold the same edge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# --- Node kinds -------------------------------------------------------------
# stand         aircraft parking position (nose-in), terminus of the graph
# apron         apron taxilane junction
# taxi          plain taxiway junction
# hold_short    runway holding position - the CAT I/II hold bar; an aircraft
#               waits here for takeoff clearance and never crosses without it
# runway_entry  the point where the taxiway meets the runway centreline
# runway_exit   a rapid-exit or right-angle turn-off from the runway
# runway        a point on the runway centreline itself (threshold, midpoint)
NODE_KINDS = {"stand", "apron", "taxi", "hold_short", "runway_entry", "runway_exit", "runway"}

# --- Edge kinds -------------------------------------------------------------
# taxiway   main parallel/link taxiway (code C width, 23 m)
# taxilane  apron taxilane, slower, tighter clearances
# stand_lead lead-in line from the taxilane to the stand stop bar
# rapid_exit high-speed runway turn-off
# runway_link short stretch between the hold bar and the runway centreline
EDGE_KINDS = {"taxiway", "taxilane", "stand_lead", "rapid_exit", "runway_link"}


@dataclass
class RunwayEnd:
    """One direction of a runway (e.g. "04")."""
    ident: str
    threshold: tuple            # (lat, lng) of the landing threshold
    heading_deg: float          # true bearing of the takeoff/landing direction
    ils_category: str = "NONE"  # NONE | CAT_I | CAT_II | CAT_III
    # Lowest visibility / decision height this end can be used at. Fog closes
    # the aerodrome for arrivals when reported visibility drops below this.
    minima_visibility_m: int = 1200
    minima_ceiling_ft: int = 200
    displaced_threshold_m: float = 0.0
    approach_lights: bool = True
    papi: bool = True


@dataclass
class Runway:
    name: str                   # "04/22"
    ends: list                  # [RunwayEnd, RunwayEnd]
    length_m: float
    width_m: float = 45.0
    surface: str = "ASPH"

    def end(self, ident: str) -> RunwayEnd:
        for e in self.ends:
            if e.ident == ident:
                return e
        raise KeyError(f"runway end {ident!r} not on {self.name}")

    def opposite(self, ident: str) -> RunwayEnd:
        return self.ends[0] if self.ends[1].ident == ident else self.ends[1]


@dataclass
class TaxiNode:
    id: str
    pos: tuple                  # (lat, lng)
    kind: str = "taxi"
    label: Optional[str] = None      # sign text, e.g. "A1"
    runway: Optional[str] = None     # runway this node relates to, if any
    end_ident: Optional[str] = None  # runway end served, for hold_short/entry/exit
    # For runway_exit nodes: distance from that end's threshold, so the sim
    # knows which exit a landing aircraft can realistically make.
    exit_distance_m: float = 0.0
    # Rapid exits can be taken at speed; right-angle turn-offs cannot.
    rapid: bool = False


@dataclass
class TaxiEdge:
    id: str
    u: str                      # node id
    v: str                      # node id
    kind: str = "taxiway"
    name: str = "A"             # taxiway designator painted on the signs
    width_m: float = 23.0
    max_speed_kt: float = 20.0
    # Extra shape points between u and v, for curved links. Excludes endpoints.
    via: list = field(default_factory=list)
    # A closed edge is removed from routing entirely (see the taxiway_closure
    # disruption) - aircraft reroute around it rather than driving through it.
    closed: bool = False
    # Name of a runway this edge physically crosses, if any. An aircraft may
    # not traverse it without that runway's clearance - at a multi-runway
    # aerodrome the route from the apron to one runway routinely crosses
    # another, and taxiing across an active runway unannounced is the single
    # worst thing a ground movement model can get wrong.
    crosses_runway: Optional[str] = None

    def nodes(self):
        return (self.u, self.v)


@dataclass
class Stand:
    id: str                     # "S1"
    name: str                   # "Stand 1"
    pos: tuple                  # nose-in stopping position (lat, lng)
    heading_deg: float          # heading the parked aircraft faces
    max_category: str = "C"     # ICAO aerodrome reference code letter
    contact: bool = True        # jet bridge (contact) vs remote bay
    node_id: str = ""           # taxi graph node for this stand


@dataclass
class Building:
    id: str
    name: str
    center: tuple
    width_m: float
    depth_m: float
    rotation_deg: float
    height_m: float
    kind: str = "terminal"      # terminal | tower | hangar | support
    color: tuple = (148, 163, 184)


@dataclass
class AirportLayout:
    icao: str
    iata: str
    name: str
    city: str
    slug: str                   # URL segment: /vadodara, /delhi, ...
    arp: tuple                  # aerodrome reference point (lat, lng)
    elevation_m: float
    timezone: str
    runways: list               # [Runway]
    nodes: dict                 # id -> TaxiNode
    edges: dict                 # id -> TaxiEdge
    stands: list                # [Stand]
    buildings: list = field(default_factory=list)
    # Typical narrow-body movement rate; drives the flight generator so a busy
    # airport feels busy and a quiet one does not.
    movements_per_hour: int = 8
    fleet_mix: dict = field(default_factory=lambda: {"A20N": 0.4, "B738": 0.25, "AT76": 0.2, "A321": 0.15})
    airlines: list = field(default_factory=lambda: ["6E", "AI", "SG", "QP", "IX"])
    # Prevailing wind, used to pick the runway in use before any weather event.
    default_wind_dir_deg: float = 250.0
    default_wind_kt: float = 8.0
    notes: str = ""

    # -- convenience ---------------------------------------------------------
    def runway_for(self, end_ident: str):
        for rwy in self.runways:
            for e in rwy.ends:
                if e.ident == end_ident:
                    return rwy, e
        raise KeyError(end_ident)

    def all_end_idents(self):
        return [e.ident for rwy in self.runways for e in rwy.ends]

    def stand_by_id(self, sid):
        for s in self.stands:
            if s.id == sid:
                return s
        raise KeyError(sid)

    def hold_short_nodes(self, end_ident):
        """Holding points protecting the runway that `end_ident` belongs to.

        A holding point is a position on the airfield, not a property of one
        direction: A1 protects runway 04/22 whether the runway in use is 04 or
        22. Matching on the runway rather than the end is what lets the twin
        reverse the runway direction on a wind shift and still find somewhere
        for departures to hold.
        """
        rwy, _ = self.runway_for(end_ident)
        return [n for n in self.nodes.values()
                if n.kind == "hold_short" and (n.runway == rwy.name or n.end_ident == end_ident)]

    def runway_access_nodes(self, runway_name=None):
        """Every point where an aircraft can join or leave the runway surface.

        Both rapid exits and the plain runway links count: landing on 22 at
        VABO, the usable turn-offs are B2 plus whichever of A1..A4 lie beyond
        the landing distance. Which of them a given arrival can actually take
        depends on its rollout, so that choice is made at runtime rather than
        baked in here.
        """
        return [n for n in self.nodes.values()
                if n.kind in ("runway_exit", "runway_entry")
                and (runway_name is None or n.runway in (None, runway_name) or n.runway == runway_name)]

    def edge_between(self, a, b):
        for e in self.edges.values():
            if (e.u, e.v) == (a, b) or (e.u, e.v) == (b, a):
                return e
        return None

    def edge_points(self, edge: TaxiEdge, forward=True):
        """Full polyline for an edge, including any `via` shape points."""
        pts = [self.nodes[edge.u].pos] + list(edge.via) + [self.nodes[edge.v].pos]
        return pts if forward else list(reversed(pts))


# ---------------------------------------------------------------------------
# Graph hygiene
# ---------------------------------------------------------------------------
# Junctions are generated from along-track distances (apron entries, rapid-exit
# tie-ins, taxiway stations), and at some airports two of those land almost on
# top of each other. Two distinct nodes a few metres apart are two separately
# lockable positions, so ATC would happily park one aircraft on each and the
# result is two aircraft in the same place - not a rendering artefact but a real
# modelling error. Merging them keeps the graph honest at any airport, including
# ones added later.
# 70 m: comfortably below the deliberate ~90 m spacing of apron lane junctions
# and stand lead-ins, so a regular chain of junctions survives intact, but above
# the separation standard the twin audits against, so anything closer than one
# aircraft length really is two names for the same piece of pavement.
MIN_NODE_SEPARATION_M = 70.0
MERGEABLE_KINDS = {"taxi", "apron"}


def merge_close_nodes(nodes: dict, edges: dict, min_sep_m: float = MIN_NODE_SEPARATION_M):
    """Collapse mergeable junctions closer than `min_sep_m`, rewiring edges.

    Stands, holding positions and runway entries/exits are never merged: their
    positions are meaningful, and two of those being close is a layout bug to
    fix rather than to paper over.
    """
    from core.geo import distance_m as _dist

    candidates = [nid for nid, n in nodes.items() if n.kind in MERGEABLE_KINDS]
    candidates.sort()
    alias = {}
    for i, a in enumerate(candidates):
        if a in alias:
            continue
        for b in candidates[i + 1:]:
            if b in alias:
                continue
            if _dist(nodes[a].pos, nodes[b].pos) < min_sep_m:
                alias[b] = a
    if not alias:
        return nodes, edges

    def resolve(nid):
        seen = set()
        while nid in alias and nid not in seen:
            seen.add(nid)
            nid = alias[nid]
        return nid

    for nid in alias:
        nodes.pop(nid, None)

    rewired, seen_pairs = {}, {}
    for eid, edge in edges.items():
        u, v = resolve(edge.u), resolve(edge.v)
        if u == v:
            continue                      # edge collapsed to nothing
        key = tuple(sorted((u, v)))
        if key in seen_pairs:
            continue                      # duplicate of an edge we already kept
        edge.u, edge.v = u, v
        seen_pairs[key] = eid
        rewired[eid] = edge
    return nodes, rewired


def mark_runway_crossings(layout):
    """Flag every taxi edge that physically crosses a runway.

    Edges that legitimately meet a runway at its surface - the runway links
    from a holding point to a runway entry, and the rapid exits - are skipped:
    they touch the centreline at an endpoint by design and are already
    governed by the runway occupancy resource. What this is looking for is the
    other case, a taxiway that cuts straight across a runway on its way
    somewhere else, which at a multi-runway airport is the normal way to reach
    the far runway from the apron.
    """
    from core.geo import segments_intersect

    ref = layout.arp
    for edge in layout.edges.values():
        if edge.kind in ("runway_link", "rapid_exit"):
            continue
        u, v = layout.nodes.get(edge.u), layout.nodes.get(edge.v)
        if u is None or v is None:
            continue
        if u.kind in ("runway_entry", "runway_exit") or v.kind in ("runway_entry", "runway_exit"):
            continue
        pts = layout.edge_points(edge)
        hit = None
        for rwy in layout.runways:
            a, b = rwy.ends[0].threshold, rwy.ends[1].threshold
            for i in range(len(pts) - 1):
                if segments_intersect(pts[i], pts[i + 1], a, b, ref):
                    hit = rwy.name
                    break
            if hit:
                break
        edge.crosses_runway = hit
    return layout
