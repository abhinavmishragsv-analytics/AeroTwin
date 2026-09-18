"""
AeroTwin Airfield Geometry Generator
====================================
Turns an `AirportLayout` (structure) into the exact drawable geometry the 3D
client renders (pavement, paint, lights, signs), in WGS84.

Why this lives on the server rather than in the React app: the frontend should
be a *renderer*, not a second, drifting source of truth about where the runway
is. Generating here means (a) the simulation and the picture are guaranteed to
agree - an aircraft holding at A1 is drawn exactly on the A1 hold bar, because
both read the same coordinate; and (b) adding Delhi later needs no frontend
work at all: describe VIDP's thresholds and taxi graph and the client draws it.

Marking dimensions follow ICAO Annex 14 / the AAI aerodrome design manual
(threshold stripe widths, touchdown-zone spacing, aiming-point placement,
taxiway hold-position pattern), so the airfield reads correctly to anyone who
actually knows what an airfield looks like.
"""
from __future__ import annotations

from core.geo import (
    bearing_deg,
    destination,
    distance_m,
    offset,
    rect_polygon,
    ribbon,
)

# ICAO Annex 14 marking constants (metres)
THRESHOLD_STRIPE_W = 1.8
THRESHOLD_STRIPE_L = 30.0
THRESHOLD_STRIPE_GAP = 1.8
THRESHOLD_STRIPE_START = 6.0
CENTERLINE_STRIPE_L = 30.0
CENTERLINE_STRIPE_GAP = 30.0
CENTERLINE_STRIPE_W = 0.9
AIMING_POINT_START = 300.0
AIMING_POINT_L = 50.0
AIMING_POINT_W = 6.0
AIMING_POINT_OFFSET = 10.5
TDZ_FIRST = 150.0
TDZ_SPACING = 150.0
TDZ_BAR_L = 22.5
TDZ_BAR_W = 1.8
EDGE_LIGHT_SPACING = 60.0
TAXI_CENTERLINE_W = 0.15


def _stripe(center, along_bearing, length, width):
    """Rectangular paint stripe aligned with a bearing, as a [lng, lat] ring."""
    return rect_polygon(center, width, length, along_bearing)


def _threshold_stripes(end, length_m, width_m):
    """Piano keys. Stripe count follows Annex 14 Table: 12 for a 45 m runway."""
    count = 12 if width_m >= 45 else 8 if width_m >= 30 else 4
    total = count * THRESHOLD_STRIPE_W + (count - 1) * THRESHOLD_STRIPE_GAP
    start_cross = -total / 2 + THRESHOLD_STRIPE_W / 2
    base = destination(end.threshold, end.heading_deg,
                       THRESHOLD_STRIPE_START + THRESHOLD_STRIPE_L / 2 + end.displaced_threshold_m)
    out = []
    for i in range(count):
        cross = start_cross + i * (THRESHOLD_STRIPE_W + THRESHOLD_STRIPE_GAP)
        c = destination(base, (end.heading_deg + 90) % 360, cross)
        out.append({
            "polygon": _stripe(c, end.heading_deg, THRESHOLD_STRIPE_L, THRESHOLD_STRIPE_W),
            "kind": "threshold",
        })
    return out


def _runway_paint(rwy):
    """All paint on one runway: piano keys, designators, centreline, TDZ, aiming points."""
    paint = []
    labels = []
    a, b = rwy.ends

    for end in (a, b):
        paint += _threshold_stripes(end, rwy.length_m, rwy.width_m)

        # Runway designator numerals, 45 m past the threshold, reading up the runway
        num_pos = destination(end.threshold, end.heading_deg, 60.0)
        labels.append({
            "position": [num_pos[1], num_pos[0]],
            "text": end.ident,
            "angle": end.heading_deg,
            "size": 26,
            "kind": "designator",
        })

        # Aiming point (two thick bars, 300 m in) and touchdown-zone bars
        for side in (-1, 1):
            c = offset(end.threshold, end.heading_deg,
                       AIMING_POINT_START + AIMING_POINT_L / 2, side * AIMING_POINT_OFFSET)
            paint.append({"polygon": _stripe(c, end.heading_deg, AIMING_POINT_L, AIMING_POINT_W),
                          "kind": "aiming"})

        d = TDZ_FIRST
        pair_index = 0
        while d < rwy.length_m / 2 - 150:
            bars = 3 - min(2, pair_index // 2)
            for side in (-1, 1):
                for k in range(bars):
                    cross = side * (AIMING_POINT_OFFSET - 3.0 + k * (TDZ_BAR_W + 1.5))
                    c = offset(end.threshold, end.heading_deg, d + TDZ_BAR_L / 2, cross)
                    paint.append({"polygon": _stripe(c, end.heading_deg, TDZ_BAR_L, TDZ_BAR_W),
                                  "kind": "tdz"})
            d += TDZ_SPACING
            pair_index += 1

    # Centreline dashes down the whole runway
    heading = a.heading_deg
    d = CENTERLINE_STRIPE_GAP
    while d < rwy.length_m - CENTERLINE_STRIPE_L:
        c = destination(a.threshold, heading, d + CENTERLINE_STRIPE_L / 2)
        paint.append({"polygon": _stripe(c, heading, CENTERLINE_STRIPE_L, CENTERLINE_STRIPE_W),
                      "kind": "centerline"})
        d += CENTERLINE_STRIPE_L + CENTERLINE_STRIPE_GAP

    return paint, labels


def _runway_lights(rwy):
    """Edge lights (white), threshold (green), runway end (red), approach bars."""
    lights = []
    a, b = rwy.ends
    half = rwy.width_m / 2 + 1.5
    d = 0.0
    while d <= rwy.length_m:
        # Last 600 m of edge lighting is amber (caution zone), per Annex 14
        remaining = rwy.length_m - d
        color = [255, 196, 90] if remaining < 600 else [255, 250, 225]
        for side in (-1, 1):
            p = offset(a.threshold, a.heading_deg, d, side * half)
            lights.append({"position": [p[1], p[0]], "color": color, "kind": "edge"})
        d += EDGE_LIGHT_SPACING

    for end in (a, b):
        for side in (-1, 1):
            for k in range(6):
                cross = side * (rwy.width_m / 2 - k * (rwy.width_m / 12))
                p = offset(end.threshold, end.heading_deg, 1.0, cross)
                lights.append({"position": [p[1], p[0]], "color": [40, 255, 120], "kind": "threshold"})
                q = offset(end.threshold, end.heading_deg, rwy.length_m - 1.0, cross)
                lights.append({"position": [q[1], q[0]], "color": [255, 60, 60], "kind": "end"})

        if end.approach_lights:
            for k in range(1, 11):
                p = destination(end.threshold, (end.heading_deg + 180) % 360, k * 30.0)
                lights.append({"position": [p[1], p[0]], "color": [255, 255, 255], "kind": "approach"})
                if k % 5 == 0:  # crossbars
                    for side in (-1, 1):
                        for j in (1, 2, 3):
                            q = destination(p, (end.heading_deg + 90 * side) % 360, j * 4.5)
                            lights.append({"position": [q[1], q[0]], "color": [255, 255, 255],
                                           "kind": "approach"})

        if end.papi:
            for k in range(4):
                p = offset(end.threshold, end.heading_deg, 300.0,
                           -(rwy.width_m / 2 + 15 + k * 9))
                lights.append({"position": [p[1], p[0]], "color": [255, 70, 70], "kind": "papi"})

    return lights


def _hold_bar(layout, node):
    """ICAO pattern A holding position: two solid + two dashed yellow lines
    across the taxiway, plus the red mandatory sign text."""
    # Orientation: perpendicular to the link that leads onto the runway.
    link = None
    for e in layout.edges.values():
        if node.id in (e.u, e.v) and e.kind == "runway_link":
            link = e
            break
    if link is None:
        for e in layout.edges.values():
            if node.id in (e.u, e.v):
                link = e
                break
    if link is None:
        return []
    other = link.v if link.u == node.id else link.u
    brg = bearing_deg(node.pos, layout.nodes[other].pos)
    width = link.width_m + 6

    bars = []
    for i, (back, dashed) in enumerate(((-1.5, False), (-0.6, False), (0.6, True), (1.5, True))):
        c = destination(node.pos, brg, back)
        if dashed:
            # three dashes with gaps
            for seg in (-1, 0, 1):
                cc = destination(c, (brg + 90) % 360, seg * (width / 3.2))
                bars.append({"polygon": rect_polygon(cc, width / 4.5, 0.3, brg), "dashed": True})
        else:
            bars.append({"polygon": rect_polygon(c, width, 0.3, brg), "dashed": False})
    return bars


def build_visuals(layout):
    """Everything the client draws, as plain JSON-ready dicts."""
    pavement = []
    paint = []
    labels = []
    lights = []
    hold_bars = []
    centerlines = []
    signs = []

    # --- Runways ---
    for rwy in layout.runways:
        a, b = rwy.ends
        pavement.append({
            "id": f"rwy-{rwy.name}",
            "polygon": ribbon([a.threshold, b.threshold], rwy.width_m),
            "kind": "runway",
        })
        # Paved shoulders + the graded strip, so the runway sits in something
        # rather than floating on satellite imagery.
        pavement.append({
            "id": f"rwy-shoulder-{rwy.name}",
            "polygon": ribbon([a.threshold, b.threshold], rwy.width_m + 15),
            "kind": "shoulder",
        })
        p, l = _runway_paint(rwy)
        paint += p
        labels += l
        lights += _runway_lights(rwy)

    # --- Taxiways / taxilanes / stand leads ---
    for edge in layout.edges.values():
        pts = layout.edge_points(edge)
        if edge.kind == "stand_lead":
            centerlines.append({
                "id": edge.id,
                "path": [[lng, lat] for lat, lng in pts],
                "kind": "lead_in",
                "name": edge.name,
            })
            continue
        pavement.append({
            "id": f"pave-{edge.id}",
            "polygon": ribbon(pts, edge.width_m),
            "kind": "taxiway" if edge.kind != "taxilane" else "apron",
        })
        centerlines.append({
            "id": edge.id,
            "path": [[lng, lat] for lat, lng in pts],
            "kind": edge.kind,
            "name": edge.name,
            "closed": edge.closed,
        })
        # Blue taxiway edge lights on the main taxiways only
        if edge.kind in ("taxiway", "rapid_exit"):
            total = distance_m(pts[0], pts[-1])
            n = max(2, int(total // 60))
            for i in range(n + 1):
                t = i / n
                c = (pts[0][0] + (pts[-1][0] - pts[0][0]) * t, pts[0][1] + (pts[-1][1] - pts[0][1]) * t)
                brg = bearing_deg(pts[0], pts[-1])
                for side in (-1, 1):
                    q = destination(c, (brg + 90 * side) % 360, edge.width_m / 2 + 2)
                    lights.append({"position": [q[1], q[0]], "color": [80, 150, 255], "kind": "taxi_edge"})

    # --- Hold-short bars and mandatory signs ---
    for node in layout.nodes.values():
        if node.kind == "hold_short":
            hold_bars += _hold_bar(layout, node)
            sp = destination(node.pos, (bearing_deg(node.pos, layout.arp) + 90) % 360, 18)
            signs.append({
                "position": [sp[1], sp[0]],
                "text": f"{node.end_ident}-{node.label or node.id}",
                "kind": "mandatory",
            })
        elif node.kind in ("taxi", "apron") and node.label:
            signs.append({"position": [node.pos[1], node.pos[0]], "text": node.label, "kind": "location"})

    # --- Aprons and stands ---
    stand_marks = []
    for stand in layout.stands:
        # Stop bar across the lead-in line at the nose-in position
        stand_marks.append({
            "id": f"{stand.id}-stopbar",
            "polygon": rect_polygon(stand.pos, 12.0, 0.5, stand.heading_deg),
            "kind": "stopbar",
        })
        lbl = destination(stand.pos, (stand.heading_deg + 180) % 360, 26.0)
        labels.append({
            "position": [lbl[1], lbl[0]],
            "text": stand.name.upper(),
            "angle": stand.heading_deg,
            "size": 9,
            "kind": "stand",
        })

    # --- Buildings ---
    buildings = [{
        "id": b.id,
        "name": b.name,
        "polygon": rect_polygon(b.center, b.width_m, b.depth_m, b.rotation_deg),
        "height": b.height_m,
        "kind": b.kind,
        "color": list(b.color),
    } for b in layout.buildings]

    return {
        "pavement": pavement,
        "paint": paint,
        "hold_bars": hold_bars,
        "centerlines": centerlines,
        "stand_marks": stand_marks,
        "labels": labels,
        "lights": lights,
        "signs": signs,
        "buildings": buildings,
    }


def layout_to_dict(layout):
    """Full layout payload: structure + generated visuals, sent once on connect."""
    return {
        "icao": layout.icao,
        "iata": layout.iata,
        "name": layout.name,
        "city": layout.city,
        "slug": layout.slug,
        "arp": [layout.arp[1], layout.arp[0]],
        "elevation_m": layout.elevation_m,
        "timezone": layout.timezone,
        "notes": layout.notes,
        "runways": [{
            "name": r.name,
            "length_m": r.length_m,
            "width_m": r.width_m,
            "surface": r.surface,
            "ends": [{
                "ident": e.ident,
                "threshold": [e.threshold[1], e.threshold[0]],
                "heading_deg": e.heading_deg,
                "ils_category": e.ils_category,
                "minima_visibility_m": e.minima_visibility_m,
                "minima_ceiling_ft": e.minima_ceiling_ft,
            } for e in r.ends],
        } for r in layout.runways],
        "stands": [{
            "id": s.id, "name": s.name, "position": [s.pos[1], s.pos[0]],
            "heading_deg": s.heading_deg, "contact": s.contact, "max_category": s.max_category,
        } for s in layout.stands],
        "nodes": [{
            "id": n.id, "position": [n.pos[1], n.pos[0]], "kind": n.kind,
            "label": n.label, "end_ident": n.end_ident,
        } for n in layout.nodes.values()],
        "edges": [{
            "id": e.id, "u": e.u, "v": e.v, "kind": e.kind, "name": e.name, "closed": e.closed,
        } for e in layout.edges.values()],
        "visuals": build_visuals(layout),
    }
