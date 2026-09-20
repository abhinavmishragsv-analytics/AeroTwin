"""
AeroTwin Geodesy
================
Every coordinate in AeroTwin is WGS84 (lat, lng) in degrees. Airfield geometry
(runway edges, taxiway centrelines, stand lead-in lines, hold-short bars) is
*generated* from a handful of surveyed reference points rather than hand-typed,
so a new airport only has to supply its runway thresholds and apron anchors and
every marking falls out correctly.

That generation needs real spherical maths - offsetting a point 190 m
perpendicular to a runway bearing is not "add 0.0017 to the latitude", and at
22 degrees north a degree of longitude is only ~103 km, not 111 km. All of that
lives here so the rest of the codebase never re-derives it (or gets it subtly
wrong in two different places).

Convention used throughout:
  point      = (lat, lng) tuple, degrees
  bearing    = degrees clockwise from true north, [0, 360)
  distance   = metres
  "along"    = distance measured down a runway/taxiway centreline
  "cross"    = distance perpendicular to it, positive to the RIGHT of the
               direction of travel (so negative = left, which for RWY 04 at
               VABO is the terminal/apron side)
"""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6371008.8  # IUGG mean radius
M_PER_DEG_LAT = 111320.0


def m_per_deg_lng(lat_deg: float) -> float:
    """Metres per degree of longitude at a given latitude."""
    return M_PER_DEG_LAT * math.cos(math.radians(lat_deg))


def bearing_deg(p1, p2) -> float:
    """Initial great-circle bearing from p1 to p2, degrees [0, 360)."""
    lat1, lng1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lng2 = math.radians(p2[0]), math.radians(p2[1])
    dlng = lng2 - lng1
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def distance_m(p1, p2) -> float:
    """Great-circle (haversine) distance in metres."""
    lat1, lng1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lng2 = math.radians(p2[0]), math.radians(p2[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def destination(p, bearing, distance):
    """Point reached by travelling `distance` metres from `p` on `bearing`.

    Uses the local flat-earth approximation deliberately: over the <5 km spans
    of an airfield it agrees with the spherical formula to well under a
    centimetre, and it is numerically better behaved (no catastrophic
    cancellation) for the thousands of small offsets the marking generator
    performs.
    """
    lat, lng = p
    rad = math.radians(bearing)
    north = distance * math.cos(rad)
    east = distance * math.sin(rad)
    return (lat + north / M_PER_DEG_LAT, lng + east / m_per_deg_lng(lat))


def offset(p, along_bearing, along_m, cross_m=0.0):
    """Move `along_m` down `along_bearing`, then `cross_m` to the right of it."""
    q = destination(p, along_bearing, along_m)
    if cross_m:
        q = destination(q, (along_bearing + 90.0) % 360.0, cross_m)
    return q


def interpolate(p1, p2, t):
    """Linear interpolation between two nearby points (airfield-scale exact enough)."""
    return (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)


def normalize_heading(h: float) -> float:
    return h % 360.0


def heading_delta(a: float, b: float) -> float:
    """Signed shortest turn from heading a to heading b, in (-180, 180]."""
    return ((b - a + 180.0) % 360.0) - 180.0


def lerp_heading(a: float, b: float, t: float) -> float:
    """Interpolate between headings the short way round, never spinning 350 deg."""
    return normalize_heading(a + heading_delta(a, b) * t)


def path_length_m(points) -> float:
    return sum(distance_m(points[i], points[i + 1]) for i in range(len(points) - 1))


def point_along_path(points, distance):
    """Position and heading at `distance` metres along a polyline.

    Returns (point, heading). Clamps to the ends. Rescans from the start of
    `points` every call - fine for one-off lookups, but see PathCursor below
    for the case this function is NOT a good fit for.
    """
    if distance <= 0:
        return points[0], bearing_deg(points[0], points[1])
    travelled = 0.0
    for i in range(len(points) - 1):
        seg = distance_m(points[i], points[i + 1])
        if seg <= 1e-9:
            continue
        if travelled + seg >= distance:
            t = (distance - travelled) / seg
            return interpolate(points[i], points[i + 1], t), bearing_deg(points[i], points[i + 1])
        travelled += seg
    return points[-1], bearing_deg(points[-2], points[-1])


class PathCursor:
    """Stateful walk along a polyline for monotonically non-decreasing queries.

    point_along_path() rescans from the start of the polyline on every call,
    which was a fine cost when a taxi route was 5-10 waypoints. It stopped
    being fine once smooth_path() started expanding a route into dozens-to-
    hundreds of points: _traverse() (core/twin_sim.py) calls this once per
    STEP_DT physics tick with a distance `s` that only ever grows over the
    course of one traversal, so rescanning from zero every tick turned an
    O(n) per-tick cost into an O(n^2) cost for the traversal as a whole -
    negligible at 6 points, measurably not negligible at 130.

    This keeps a cursor (which segment the previous call landed in, and the
    cumulative distance travelled up to it) so each call only walks FORWARD
    from wherever the last call left off. Amortized O(1) per tick, O(n)
    total per traversal - the same total cost paying for the whole route
    once that point_along_path always had, just no longer paid for on every
    single tick along the way.

    Only valid when `distance` is non-decreasing across calls to the same
    cursor - which is exactly (and only) how _traverse()'s speed-profile
    loop advances `s`. Anything that needs a one-off or non-monotonic
    lookup should use point_along_path() instead.
    """

    __slots__ = ("points", "_i", "_travelled")

    def __init__(self, points):
        self.points = points
        self._i = 0
        self._travelled = 0.0

    def at(self, distance):
        points = self.points
        if distance <= 0:
            return points[0], bearing_deg(points[0], points[1])
        n = len(points) - 1
        while self._i < n:
            seg = distance_m(points[self._i], points[self._i + 1])
            if seg <= 1e-9:
                self._i += 1
                continue
            if self._travelled + seg >= distance:
                t = (distance - self._travelled) / seg
                return (
                    interpolate(points[self._i], points[self._i + 1], t),
                    bearing_deg(points[self._i], points[self._i + 1]),
                )
            self._travelled += seg
            self._i += 1
        return points[-1], bearing_deg(points[-2], points[-1])


def smooth_path(points, spacing_m=6.0, alpha=0.5):
    """Round a polyline's corners into a continuous curve.

    `_traverse()` (core/twin_sim.py) drives every aircraft along the raw
    taxiway-graph polyline: a sequence of straight segments joined at nodes
    (spine stations, hold bars, runway entries). Between nodes that's fine -
    taxiways really are straight - but AT a node the direction of travel
    changes instantaneously, while the aircraft's heading is only allowed to
    turn at MAX_TURN_RATE_DEG_S. Position (which snaps exactly onto the
    polyline) and heading (which is still catching up) disagree for a moment
    at every corner, and that mismatch is what reads as blocky, hitching
    motion through turns.

    This runs a centripetal Catmull-Rom spline through the same points -
    still passing through every one of them exactly (so hold-short bars,
    runway thresholds and stand centrelines stay exactly where the airfield
    generator put them) - and returns a much finer polyline whose bearing
    changes continuously through what used to be a corner. Centripetal
    (alpha=0.5) rather than uniform parameterisation matters here because
    taxiway stations are unevenly spaced; uniform Catmull-Rom can loop or
    overshoot on that kind of input, centripetal never does.
    """
    if len(points) < 3:
        return list(points)
    ref = points[0]
    xy = [to_local_xy(p, ref) for p in points]
    padded = [xy[0]] + xy + [xy[-1]]

    def lerp2(a, b, t):
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    out = []
    for i in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[i - 1], padded[i], padded[i + 1], padded[i + 2]
        seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if seg_len < 1e-6:
            continue
        n = max(2, int(seg_len / spacing_m))

        def knot(t0, pa, pb):
            d = max(1e-6, math.hypot(pb[0] - pa[0], pb[1] - pa[1])) ** alpha
            return t0 + d

        t0 = 0.0
        t1 = knot(t0, p0, p1)
        t2 = knot(t1, p1, p2)
        t3 = knot(t2, p2, p3)
        for k in range(n):
            t = t1 + (t2 - t1) * (k / n)
            a1 = lerp2(p0, p1, (t - t0) / (t1 - t0)) if t1 != t0 else p1
            a2 = lerp2(p1, p2, (t - t1) / (t2 - t1)) if t2 != t1 else p2
            a3 = lerp2(p2, p3, (t - t2) / (t3 - t2)) if t3 != t2 else p3
            b1 = lerp2(a1, a2, (t - t0) / (t2 - t0)) if t2 != t0 else a2
            b2 = lerp2(a2, a3, (t - t1) / (t3 - t1)) if t3 != t1 else a3
            out.append(lerp2(b1, b2, (t - t1) / (t2 - t1)) if t2 != t1 else b1)
    out.append(xy[-1])

    mlat, mlng = M_PER_DEG_LAT, m_per_deg_lng(ref[0])
    result = [(ref[0] + ny / mlat, ref[1] + ex / mlng) for ex, ny in out]

    deduped = [result[0]]
    for p in result[1:]:
        if distance_m(p, deduped[-1]) > 0.15:
            deduped.append(p)
    return deduped if len(deduped) >= 2 else list(points)


def ribbon(points, width_m):
    """Turn a centreline polyline into a closed [lng, lat] polygon of given width.

    Used for runway/taxiway/apron pavement. Each vertex is offset perpendicular
    to the *local* bearing, which is good enough for the shallow bends real
    taxiways have and avoids the mitre maths a full stroker would need.
    """
    if len(points) < 2:
        return []
    half = width_m / 2.0
    left, right = [], []
    for i, p in enumerate(points):
        if i == 0:
            brg = bearing_deg(points[0], points[1])
        elif i == len(points) - 1:
            brg = bearing_deg(points[-2], points[-1])
        else:
            b1 = bearing_deg(points[i - 1], points[i])
            b2 = bearing_deg(points[i], points[i + 1])
            brg = normalize_heading(b1 + heading_delta(b1, b2) / 2.0)
        left.append(destination(p, (brg - 90.0) % 360.0, half))
        right.append(destination(p, (brg + 90.0) % 360.0, half))
    ring = left + list(reversed(right))
    return [[lng, lat] for lat, lng in ring]


def rect_polygon(center, width_m, depth_m, rotation_deg=0.0):
    """Axis-rotated rectangle as a [lng, lat] ring, centred on `center`.

    `rotation_deg` is the bearing the rectangle's *depth* axis points along, so
    a building can be aligned with the runway instead of sitting north-south.
    """
    lat, lng = center
    rad = math.radians(rotation_deg)
    mlat, mlng = M_PER_DEG_LAT, m_per_deg_lng(lat)
    ring = []
    for ex, ny in ((-width_m / 2, -depth_m / 2), (width_m / 2, -depth_m / 2),
                   (width_m / 2, depth_m / 2), (-width_m / 2, depth_m / 2)):
        east = ex * math.cos(rad) + ny * math.sin(rad)
        north = -ex * math.sin(rad) + ny * math.cos(rad)
        ring.append([lng + east / mlng, lat + north / mlat])
    return ring


def crosswind_component(wind_dir_deg: float, wind_kt: float, runway_heading_deg: float):
    """Split a wind vector into (headwind, crosswind) components for a runway.

    Positive headwind = wind down the approach (good). Crosswind is returned as
    an absolute magnitude, which is what limits apply to.
    """
    angle = math.radians(wind_dir_deg - runway_heading_deg)
    return wind_kt * math.cos(angle), abs(wind_kt * math.sin(angle))


def to_local_xy(p, ref):
    """Project a (lat, lng) to local east/north metres about a reference point."""
    return ((p[1] - ref[1]) * m_per_deg_lng(ref[0]), (p[0] - ref[0]) * M_PER_DEG_LAT)


def segments_intersect(a1, a2, b1, b2, ref):
    """Whether two lat/lng segments cross, evaluated in local metres.

    Used to find taxiway edges that cross a runway. At airfield scale the
    local projection is exact enough that a crossing is never missed, and the
    consequence of the answer - whether an aircraft needs runway crossing
    clearance - is one that has to be right.
    """
    (x1, y1), (x2, y2) = to_local_xy(a1, ref), to_local_xy(a2, ref)
    (x3, y3), (x4, y4) = to_local_xy(b1, ref), to_local_xy(b2, ref)

    def orient(ax, ay, bx, by, cx, cy):
        v = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(v) < 1e-9:
            return 0
        return 1 if v > 0 else -1

    d1 = orient(x1, y1, x2, y2, x3, y3)
    d2 = orient(x1, y1, x2, y2, x4, y4)
    d3 = orient(x3, y3, x4, y4, x1, y1)
    d4 = orient(x3, y3, x4, y4, x2, y2)
    return d1 != d2 and d3 != d4
