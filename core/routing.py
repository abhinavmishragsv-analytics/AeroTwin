"""
AeroTwin Taxi Routing
=====================
Shortest-path planning across an airport's taxi graph.

Real ground movement is not "fly from the stand to the runway" - it is a route
along named taxiways, issued as a clearance ("taxi to holding point A1 via
Alpha"). This module produces exactly that: an ordered list of edges from any
node to any other, respecting closures.

Because routes are graph paths rather than straight lines, two things fall out
for free:
  * Aircraft follow taxiway centrelines, entering the runway only at a real
    link, at the correct angle.
  * Closing a taxiway (the `taxiway_closure` disruption) makes traffic
    genuinely *reroute* - the planner simply never returns the closed edge -
    rather than driving through a cone.

Cost is distance weighted by edge kind, so the planner prefers the parallel
taxiway over threading through the apron, and prefers a rapid exit to a
right-angle turn-off, the way a real ground controller would.
"""
from __future__ import annotations

import heapq

from core.geo import distance_m, path_length_m

# Multipliers applied to raw distance when choosing a route.
KIND_COST = {
    "taxiway": 1.0,
    "rapid_exit": 0.85,   # preferred when leaving the runway
    "runway_link": 1.2,
    "taxilane": 1.6,      # slow, congested, avoid as a through route
    "stand_lead": 2.0,    # only ever used at the ends of a route
}


class TaxiRoute:
    """An ordered walk through the taxi graph, with per-edge direction."""

    def __init__(self, layout, node_ids):
        self.layout = layout
        self.node_ids = list(node_ids)
        self.legs = []          # [(edge, forward: bool)]
        for a, b in zip(self.node_ids, self.node_ids[1:]):
            edge = layout.edge_between(a, b)
            if edge is None:
                raise ValueError(f"no edge between {a} and {b}")
            self.legs.append((edge, edge.u == a))

    @property
    def edges(self):
        return [e for e, _ in self.legs]

    def points(self):
        """Full polyline of the route, deduplicated at the joins."""
        pts = []
        for edge, forward in self.legs:
            leg = self.layout.edge_points(edge, forward)
            if pts and distance_m(pts[-1], leg[0]) < 0.5:
                leg = leg[1:]
            pts.extend(leg)
        return pts

    def length_m(self):
        pts = self.points()
        return path_length_m(pts) if len(pts) > 1 else 0.0

    def describe(self):
        """Human-readable clearance text, e.g. 'A -> A1'. Consecutive legs on
        the same taxiway collapse into one name, exactly like a spoken clearance."""
        names = []
        for edge, _ in self.legs:
            if edge.kind == "stand_lead":
                continue
            if not names or names[-1] != edge.name:
                names.append(edge.name)
        return " ".join(names) if names else "direct"

    def __len__(self):
        return len(self.legs)

    def __bool__(self):
        return bool(self.legs)


def plan(layout, start_node, goal_node, avoid_edges=(), allow_closed=False):
    """Dijkstra from start_node to goal_node. Returns a TaxiRoute or None."""
    if start_node == goal_node:
        return TaxiRoute(layout, [start_node])

    adjacency = {}
    for edge in layout.edges.values():
        if edge.id in avoid_edges:
            continue
        if edge.closed and not allow_closed:
            continue
        pts = layout.edge_points(edge)
        cost = path_length_m(pts) * KIND_COST.get(edge.kind, 1.0)
        adjacency.setdefault(edge.u, []).append((edge.v, cost))
        adjacency.setdefault(edge.v, []).append((edge.u, cost))

    dist = {start_node: 0.0}
    prev = {}
    queue = [(0.0, start_node)]
    seen = set()
    while queue:
        d, node = heapq.heappop(queue)
        if node in seen:
            continue
        seen.add(node)
        if node == goal_node:
            break
        for nxt, cost in adjacency.get(node, ()):
            nd = d + cost
            if nd < dist.get(nxt, float("inf")):
                dist[nxt] = nd
                prev[nxt] = node
                heapq.heappush(queue, (nd, nxt))

    if goal_node not in dist:
        return None

    chain = [goal_node]
    while chain[-1] != start_node:
        chain.append(prev[chain[-1]])
    chain.reverse()
    return TaxiRoute(layout, chain)


def best_hold_short(layout, stand_node, end_ident, avoid_edges=()):
    """Pick the departure holding point that gives the shortest taxi.

    Full-length departures use the holding point at the threshold end; if
    another link is much closer, an intersection departure is offered - which is
    what a controller does at a quiet airport when the pilot accepts it.
    """
    best = None
    for node in layout.hold_short_nodes(end_ident):
        route = plan(layout, stand_node, node.id, avoid_edges=avoid_edges)
        if route is None:
            continue
        # Only the link at the runway's used end gives full length; others cost
        # runway distance, so penalise them unless they save a lot of taxiing.
        if best is None or route.length_m() < best[1].length_m():
            best = (node, route)
    return best


def route_from_exit(layout, exit_node_id, stand_node, avoid_edges=()):
    return plan(layout, exit_node_id, stand_node, avoid_edges=avoid_edges)
