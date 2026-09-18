"""
Generic Airfield Builder
========================
VABO is defined by hand in `vabo.py` because it is the reference airport and
deserves its real apron arrangement. Every *other* airport in the registry is
built by this function from a short description: runway thresholds, how far the
parallel taxiway and apron sit from the centreline, and how many stands.

The result is structurally identical to VABO's - same node kinds, same
single-occupancy edges, same hold-short positions - so `core.atc`,
`core.routing` and the entire frontend work on Delhi or Ahmedabad with no
changes whatsoever. That is the whole point of keeping the twin's logic
airport-agnostic: `/delhi` is a data change, not a code change.

Secondary runways (Delhi's three, Mumbai's two) are included as *pavement and
paint* so the picture is right, but the simulation currently works one runway
at a time - the one selected as the active runway by wind. Multi-runway
independent operations are a natural next step, not a pretence made here.
"""
from core.airports.schema import (
    AirportLayout,
    Building,
    Runway,
    RunwayEnd,
    Stand,
    TaxiEdge,
    TaxiNode,
    merge_close_nodes,
)
from core.aircraft import get as get_ac_type
from core.geo import bearing_deg, distance_m, offset


def build_airport(
    *,
    icao,
    iata,
    name,
    city,
    slug,
    thresholds,                 # (point_a, point_b) of the OPERATING runway
    idents,                     # ("09", "27")
    elevation_m,
    extra_runways=(),           # [(name, thr_a, thr_b, ident_a, ident_b, width)]
    runway_width=45.0,
    taxiway_offset=-190.0,
    apron_lane_offset=-280.0,
    stand_offset=-330.0,
    terminal_offset=-395.0,
    n_contact_stands=8,
    n_remote_stands=4,
    stand_spacing_m=95.0,
    apron_center_frac=0.5,
    movements_per_hour=12,
    fleet_mix=None,
    airlines=None,
    ils=("CAT_I", "CAT_I"),
    minima=((1200, 200), (1200, 200)),
    default_wind_dir_deg=250.0,
    default_wind_kt=9.0,
    timezone="Asia/Kolkata",
    notes="",
):
    thr_a, thr_b = thresholds
    heading = bearing_deg(thr_a, thr_b)
    length = distance_m(thr_a, thr_b)

    def rw(along, cross=0.0):
        return offset(thr_a, heading, along, cross)

    nodes, edges, stands, buildings = {}, {}, [], []

    def node(nid, pos, kind="taxi", **kw):
        nodes[nid] = TaxiNode(id=nid, pos=pos, kind=kind, **kw)
        return nid

    def edge(eid, u, v, kind="taxiway", ename="A", width=23.0, speed=20.0, via=None):
        edges[eid] = TaxiEdge(id=eid, u=u, v=v, kind=kind, name=ename,
                              width_m=width, max_speed_kt=speed, via=via or [])
        return eid

    # --- Parallel taxiway with four runway links -------------------------
    stations = {
        "A1": 60.0,
        "A2": length * 0.30,
        "A3": length * 0.62,
        "A4": length - 70.0,
    }
    ordered = sorted(stations.items(), key=lambda kv: kv[1])
    for sname, along in ordered:
        node(f"TA_{sname}", rw(along, taxiway_offset), kind="taxi", label=sname)
        node(f"HS_{sname}_{idents[0]}", rw(along, -90.0), kind="hold_short",
             label=sname, runway=f"{idents[0]}/{idents[1]}", end_ident=idents[0])
        node(f"RE_{sname}", rw(along, 0.0), kind="runway_entry", label=sname,
             runway=f"{idents[0]}/{idents[1]}", end_ident=idents[0])
        edge(f"E_TA_{sname}_HS", f"TA_{sname}", f"HS_{sname}_{idents[0]}", ename=sname, speed=15)
        edge(f"E_HS_{sname}_RE", f"HS_{sname}_{idents[0]}", f"RE_{sname}",
             kind="runway_link", ename=sname, speed=12)

    for (n1, _), (n2, _) in zip(ordered, ordered[1:]):
        edge(f"E_ALPHA_{n1}_{n2}", f"TA_{n1}", f"TA_{n2}", ename="A", speed=22)

    # --- Rapid exits, one for each landing direction ---------------------
    # Deliberately offset from the A2/A3 stations above: a rapid exit and a
    # taxiway link at the same point on the runway would be two names for one
    # place, and the twin would treat them as two independently lockable ones.
    for rname, frac, serves in (("B1", 0.53, idents[0]), ("B2", 0.42, idents[1])):
        along = length * frac
        direction = 1 if serves == idents[0] else -1
        node(f"RX_{rname}", rw(along, 0.0), kind="runway_exit", label=rname,
             end_ident=serves, rapid=True,
             exit_distance_m=along if serves == idents[0] else length - along)
        node(f"TX_{rname}", rw(along + direction * 200.0, taxiway_offset), kind="taxi", label=rname)
        edge(f"E_RX_{rname}", f"RX_{rname}", f"TX_{rname}", kind="rapid_exit", ename=rname, speed=30,
             via=[rw(along + direction * 75.0, -60.0), rw(along + direction * 150.0, -145.0)])

    # Splice rapid-exit junctions into the spine between the stations they fall between.
    def _splice(tx_node):
        target = distance_m(thr_a, nodes[tx_node].pos)
        best = None
        for eid, e in list(edges.items()):
            if not eid.startswith("E_ALPHA_"):
                continue
            du = distance_m(thr_a, nodes[e.u].pos)
            dv = distance_m(thr_a, nodes[e.v].pos)
            lo, hi = min(du, dv), max(du, dv)
            if lo <= target <= hi:
                best = (eid, e)
                break
        if best is None:
            return
        eid, e = best
        edges.pop(eid)
        edge(f"{eid}_a", e.u, tx_node, ename="A", speed=22)
        edge(f"{eid}_b", tx_node, e.v, ename="A", speed=22)

    _splice("TX_B2")
    _splice("TX_B1")

    # --- Apron taxilane + stands -----------------------------------------
    total_stands = n_contact_stands + n_remote_stands
    apron_len = max(total_stands, 4) * stand_spacing_m
    apron_start = length * apron_center_frac - apron_len / 2

    node("AP_S", rw(apron_start - 60, apron_lane_offset), kind="apron", label="Apron S")
    node("AP_N", rw(apron_start + apron_len + 60, apron_lane_offset), kind="apron", label="Apron N")
    node("TA_APS", rw(apron_start - 60, taxiway_offset), kind="taxi", label="A5")
    node("TA_APN", rw(apron_start + apron_len + 60, taxiway_offset), kind="taxi", label="A6")
    _splice("TA_APS")
    _splice("TA_APN")
    edge("E_APS_LINK", "TA_APS", "AP_S", kind="taxilane", ename="S", width=25, speed=12)
    edge("E_APN_LINK", "TA_APN", "AP_N", kind="taxilane", ename="N", width=25, speed=12)

    # Match stand size to the fleet actually operating here: an airport whose
    # mix includes wide-bodies needs some stands built to take them, or every
    # widebody arrival finds nowhere to park and the approach backs up behind
    # it indefinitely. The first third of contact stands (a realistic split at
    # a mixed hub) get the largest category the fleet mix actually uses; the
    # rest stay code C.
    mix = fleet_mix or {}
    order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5}
    widest = max((get_ac_type(c).category for c, w in mix.items() if w > 0),
                 key=lambda cat: order.get(cat, 2), default="C")
    n_wide = max(1, n_contact_stands // 3) if order.get(widest, 2) > order["C"] else 0

    for i in range(1, n_contact_stands + 1):
        sid = f"S{i}"
        cat = widest if i <= n_wide else "C"
        along = apron_start + (i - 0.5) * stand_spacing_m
        node(f"LN_{sid}", rw(along, apron_lane_offset), kind="apron")
        nid = node(f"ST_{sid}", rw(along, stand_offset), kind="stand", label=f"Stand {i}")
        edge(f"E_LEAD_{sid}", f"LN_{sid}", nid, kind="stand_lead", ename=sid, width=18, speed=8)
        stands.append(Stand(id=sid, name=f"Stand {i}", pos=rw(along, stand_offset),
                            heading_deg=(heading - 90) % 360, contact=True, node_id=nid,
                            max_category=cat))

    for i in range(1, n_remote_stands + 1):
        sid = f"R{i}"
        along = apron_start + (n_contact_stands + i - 0.5) * stand_spacing_m
        node(f"LN_{sid}", rw(along, apron_lane_offset), kind="apron")
        nid = node(f"ST_{sid}", rw(along, stand_offset - 34), kind="stand", label=f"Remote {i}")
        edge(f"E_LEAD_{sid}", f"LN_{sid}", nid, kind="stand_lead", ename=sid, width=18, speed=8)
        stands.append(Stand(id=sid, name=f"Remote {i}", pos=rw(along, stand_offset - 34),
                            heading_deg=(heading - 90) % 360, contact=False, node_id=nid))

    lane_nodes = sorted(
        [n for n in nodes if n.startswith("LN_")] + ["AP_S", "AP_N"],
        key=lambda n: distance_m(thr_a, nodes[n].pos),
    )
    for a, b in zip(lane_nodes, lane_nodes[1:]):
        edge(f"E_LANE_{a}_{b}", a, b, kind="taxilane", ename="Apron", width=25, speed=10)

    # --- Buildings --------------------------------------------------------
    term_along = apron_start + apron_len / 2
    buildings.append(Building(
        id="terminal", name=f"{city} Terminal", center=rw(term_along, terminal_offset),
        width_m=min(420.0, apron_len * 0.85), depth_m=70.0, rotation_deg=heading,
        height_m=24.0, kind="terminal", color=(203, 213, 225),
    ))
    buildings.append(Building(
        id="atc", name=f"{icao} Control Tower", center=rw(term_along + apron_len * 0.55, taxiway_offset - 80),
        width_m=18.0, depth_m=18.0, rotation_deg=heading, height_m=46.0, kind="tower",
        color=(226, 232, 240),
    ))
    buildings.append(Building(
        id="hangar", name="Maintenance Hangar", center=rw(apron_start - 260, stand_offset - 40),
        width_m=90.0, depth_m=58.0, rotation_deg=heading, height_m=20.0, kind="hangar",
        color=(120, 128, 138),
    ))

    runways = [Runway(
        name=f"{idents[0]}/{idents[1]}",
        length_m=length,
        width_m=runway_width,
        ends=[
            RunwayEnd(ident=idents[0], threshold=thr_a, heading_deg=heading,
                      ils_category=ils[0], minima_visibility_m=minima[0][0],
                      minima_ceiling_ft=minima[0][1]),
            RunwayEnd(ident=idents[1], threshold=thr_b, heading_deg=(heading + 180) % 360,
                      ils_category=ils[1], minima_visibility_m=minima[1][0],
                      minima_ceiling_ft=minima[1][1]),
        ],
    )]
    for rname, ta, tb, ia, ib, width in extra_runways:
        h = bearing_deg(ta, tb)
        runways.append(Runway(
            name=rname, length_m=distance_m(ta, tb), width_m=width,
            ends=[
                RunwayEnd(ident=ia, threshold=ta, heading_deg=h, ils_category="CAT_I"),
                RunwayEnd(ident=ib, threshold=tb, heading_deg=(h + 180) % 360, ils_category="CAT_I"),
            ],
        ))

    nodes, edges = merge_close_nodes(nodes, edges)
    return AirportLayout(
        icao=icao, iata=iata, name=name, city=city, slug=slug,
        arp=rw(length / 2, 0.0), elevation_m=elevation_m, timezone=timezone,
        runways=runways, nodes=nodes, edges=edges, stands=stands, buildings=buildings,
        movements_per_hour=movements_per_hour,
        fleet_mix=fleet_mix or {"A20N": 0.36, "B738": 0.2, "A321": 0.16, "AT76": 0.16, "B78X": 0.06, "Q400": 0.06},
        airlines=airlines or ["6E", "AI", "SG", "QP", "IX", "UK"],
        default_wind_dir_deg=default_wind_dir_deg,
        default_wind_kt=default_wind_kt,
        notes=notes,
    )
