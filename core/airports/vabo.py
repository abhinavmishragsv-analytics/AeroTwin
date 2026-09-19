"""
VABO - Vadodara Airport (Harni), Gujarat, India
================================================
The reference airfield for AeroTwin, defined at full fidelity.

Surveyed facts (AAI / AIP India / public sources):
  * Single asphalt runway 04/22, 2,469 m x 45 m, true bearing ~044 deg.
  * Aerodrome elevation ~129 ft (39 m).
  * CAT I ILS; the aerodrome is not CAT III equipped, which is exactly why the
    fog scenario in this twin closes it for arrivals rather than merely slowing
    them down - a detail the earlier build got wrong.
  * New Integrated Terminal Building (2016), 18,120 sq m, on the north-west
    side of the runway facing the city.
  * Apron: 13 Code C stands - 7 contact bays (6 A320-class + 1 ATR) and 6
    remote bays.

Everything below the runway thresholds is *derived* from them: the parallel
taxiway, its four links, the two rapid-exit taxiways, the apron taxilane and
the stand lead-in lines are all computed as along-track/cross-track offsets
from the 04 threshold. That means the airfield is internally consistent by
construction - the taxiway really is parallel, the hold bars really are at the
runway edge, and the stands really are on the apron rather than, as in the
first demo, sitting 42 m from the runway centreline inside the strip.

Cross-track sign convention (see core.geo): negative is LEFT of the 04
direction of travel, i.e. the north-west / terminal side.

Coordinates are surveyed from public satellite imagery against the two runway
thresholds. They are accurate to a few metres - good enough to sit correctly on
the MapLibre satellite basemap - but this is a digital twin for simulation, not
a navigation chart, and must not be used for real operations.
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
from core.geo import bearing_deg, destination, distance_m, offset

# --- Surveyed runway thresholds --------------------------------------------
THR_04 = (22.32970, 73.21930)
THR_22 = (22.34560, 73.23610)

RWY_HEADING = bearing_deg(THR_04, THR_22)          # ~44.34 deg true
RWY_LENGTH = distance_m(THR_04, THR_22)            # ~2472 m
RWY_WIDTH = 45.0

# --- Airfield cross-track offsets (metres, negative = terminal side) --------
TWY_A_OFFSET = -182.0      # parallel Taxiway Alpha, standard code C separation
APRON_LANE_OFFSET = -268.0  # apron taxilane, one taxiway width further in
STAND_OFFSET = -318.0      # stand nose-in line
TERMINAL_OFFSET = -372.0   # terminal face


def _rw(along_m, cross_m=0.0):
    """Point at (along, cross) relative to the 04 threshold."""
    return offset(THR_04, RWY_HEADING, along_m, cross_m)


# ---------------------------------------------------------------------------
# Taxi graph
# ---------------------------------------------------------------------------
# Taxiway Alpha runs the full length of the runway on the terminal side, with
# four links (A1..A4) onto the runway. A1 and A4 are the full-length departure
# entries at each end; A2 and A3 are intersection departures / crossing points.
# Two rapid-exit taxiways (B1 for landings on 04, B2 for landings on 22) let an
# arrival leave the runway at speed instead of rolling to the far end, which is
# what actually keeps a single-runway airport's arrival rate up.
ALPHA_STATIONS = {
    "A1": 60.0,     # abeam RWY 04 threshold
    "A2": 780.0,
    "A3": 1450.0,   # abeam the apron
    # 60 m short of the 22 threshold, matching A1's setback from the 04
    # threshold (RWY_LENGTH - 60, not a separately-chosen number). The two
    # full-length departure points need matching setbacks - a hold point
    # even a few extra metres short of its threshold measurably shrinks the
    # takeoff run available in that direction, and for an aircraft whose
    # TODR is a tight fraction of the runway length (an A321 here needs
    # 2394 m of a 2472 m runway), that's the difference between "every
    # departure candidate qualifies" and "none of them do, ever, whenever
    # the wind favours this direction" - which is exactly what a 2390 m
    # placement (82 m short) used to cause: see the retry cap in
    # twin_sim._depart_from_stand for the failure mode this produced when
    # it happened anyway.
    "A4": RWY_LENGTH - 60.0,
}
# Rapid exits are placed where a narrow-body actually slows to turning speed:
# roughly 1,500-1,800 m past the threshold it is using. B1 serves landings on
# 04, B2 serves landings on 22 (its along-distance is still measured from the
# 04 threshold, like everything else in this file).
RAPID_EXITS = {
    "B1": (1820.0, "04"),
    "B2": (1150.0, "22"),
}

_nodes = {}
_edges = {}


def _node(nid, pos, kind="taxi", **kw):
    _nodes[nid] = TaxiNode(id=nid, pos=pos, kind=kind, **kw)
    return nid


def _edge(eid, u, v, kind="taxiway", name="A", width=23.0, speed=20.0, via=None):
    _edges[eid] = TaxiEdge(id=eid, u=u, v=v, kind=kind, name=name,
                           width_m=width, max_speed_kt=speed, via=via or [])
    return eid


# -- Taxiway Alpha: the spine, plus its runway links -------------------------
_alpha_order = sorted(ALPHA_STATIONS.items(), key=lambda kv: kv[1])
for name, along in _alpha_order:
    _node(f"TA_{name}", _rw(along, TWY_A_OFFSET), kind="taxi", label=name)
    # Hold-short position: 90 m from the runway centreline (CAT I holding
    # position for a code C runway), on the link between Alpha and the runway.
    _node(f"HS_{name}_04", _rw(along, -90.0), kind="hold_short",
          label=name, runway="04/22", end_ident="04")
    _node(f"RE_{name}", _rw(along, 0.0), kind="runway_entry",
          label=name, runway="04/22", end_ident="04")
    _edge(f"E_TA_{name}_HS", f"TA_{name}", f"HS_{name}_04", kind="taxiway", name=name, speed=15)
    _edge(f"E_HS_{name}_RE", f"HS_{name}_04", f"RE_{name}", kind="runway_link", name=name, speed=12)

# Spine segments between consecutive Alpha stations. Each is its own edge -
# and therefore its own single-occupancy resource - so two aircraft can be on
# Alpha at once without ever being on the same stretch of it.
for (n1, _), (n2, _) in zip(_alpha_order, _alpha_order[1:]):
    _edge(f"E_ALPHA_{n1}_{n2}", f"TA_{n1}", f"TA_{n2}", kind="taxiway", name="A", speed=22)

# -- Rapid exit taxiways -----------------------------------------------------
# A rapid exit leaves the runway at roughly 30 deg and curves onto Alpha, so it
# is drawn and driven as a curved edge rather than a right-angle turn.
for rname, (along, serves) in RAPID_EXITS.items():
    direction = 1 if serves == "04" else -1
    _node(f"RX_{rname}", _rw(along, 0.0), kind="runway_exit", label=rname,
          runway="04/22", end_ident=serves, rapid=True,
          exit_distance_m=along if serves == "04" else RWY_LENGTH - along)
    _node(f"TX_{rname}", _rw(along + direction * 190.0, TWY_A_OFFSET), kind="taxi", label=rname)
    _edge(f"E_RX_{rname}", f"RX_{rname}", f"TX_{rname}", kind="rapid_exit", name=rname, speed=30,
          via=[_rw(along + direction * 70.0, -60.0), _rw(along + direction * 140.0, -140.0)])

# Splice the rapid-exit junctions into the Alpha spine so routing can use them.
# TX_B2 sits between A2 and A3; TX_B1 between A3 and A4.
_edge("E_ALPHA_A2_TXB2", "TA_A2", "TX_B2", kind="taxiway", name="A", speed=22)
_edge("E_ALPHA_TXB2_A3", "TX_B2", "TA_A3", kind="taxiway", name="A", speed=22)
_edge("E_ALPHA_A3_TXB1", "TA_A3", "TX_B1", kind="taxiway", name="A", speed=22)
_edge("E_ALPHA_TXB1_A4", "TX_B1", "TA_A4", kind="taxiway", name="A", speed=22)
# Those four replace the two long spans they subdivide.
for dead in ("E_ALPHA_A2_A3", "E_ALPHA_A3_A4"):
    _edges.pop(dead, None)

# -- Apron taxilane and stands ----------------------------------------------
# The apron taxilane runs parallel to Alpha in front of the terminal. Aircraft
# reach it from Alpha via two apron entries (N and S) - having two means a
# pushback at one end does not deadlock an arrival trying to reach the other.
# The apron entries sit just outside the stand block at either end, so an
# aircraft entering the apron never shares a position with a stand lead-in.
APRON_SOUTH = 1080.0
APRON_NORTH = 1850.0
_node("AP_S", _rw(APRON_SOUTH, APRON_LANE_OFFSET), kind="apron", label="Apron S")
_node("AP_N", _rw(APRON_NORTH, APRON_LANE_OFFSET), kind="apron", label="Apron N")
_node("AP_MID", _rw((APRON_SOUTH + APRON_NORTH) / 2, APRON_LANE_OFFSET), kind="apron")

# Alpha <-> apron connectors
_node("TA_APS", _rw(APRON_SOUTH, TWY_A_OFFSET), kind="taxi", label="A5")
_node("TA_APN", _rw(APRON_NORTH, TWY_A_OFFSET), kind="taxi", label="A6")
_edge("E_ALPHA_A2_APS", "TA_A2", "TA_APS", kind="taxiway", name="A", speed=22)
_edge("E_ALPHA_APS_TXB2", "TA_APS", "TX_B2", kind="taxiway", name="A", speed=22)
_edges.pop("E_ALPHA_A2_TXB2", None)
_edge("E_ALPHA_A3_APN", "TA_A3", "TA_APN", kind="taxiway", name="A", speed=22)
_edge("E_ALPHA_APN_TXB1", "TA_APN", "TX_B1", kind="taxiway", name="A", speed=22)
_edges.pop("E_ALPHA_A3_TXB1", None)

_edge("E_APS_LINK", "TA_APS", "AP_S", kind="taxilane", name="S", width=25, speed=12)
_edge("E_APN_LINK", "TA_APN", "AP_N", kind="taxilane", name="N", width=25, speed=12)
_edge("E_APRON_S_MID", "AP_S", "AP_MID", kind="taxilane", name="Apron", width=25, speed=10)
_edge("E_APRON_MID_N", "AP_MID", "AP_N", kind="taxilane", name="Apron", width=25, speed=10)

# Stands. 7 contact bays in front of the terminal, 6 remote bays to the south.
# Nose-in heading points at the terminal (i.e. further cross-track), which is
# what makes a pushback physically sensible: the aircraft is pushed tail-first
# back onto the taxilane, then taxis forward.
_stands = []
STAND_HEADING = (RWY_HEADING - 90.0) % 360.0   # facing the terminal

_contact_alongs = [1180.0 + i * 95.0 for i in range(7)]
for i, along in enumerate(_contact_alongs, start=1):
    sid = f"S{i}"
    pos = _rw(along, STAND_OFFSET)
    lane = _rw(along, APRON_LANE_OFFSET)
    node_id = _node(f"ST_{sid}", pos, kind="stand", label=f"Stand {i}")
    _node(f"LN_{sid}", lane, kind="apron")
    _edge(f"E_LEAD_{sid}", f"LN_{sid}", node_id, kind="stand_lead", name=sid, width=18, speed=8)
    _stands.append(Stand(
        id=sid, name=f"Stand {i}", pos=pos, heading_deg=STAND_HEADING,
        max_category="C" if i != 7 else "B",   # bay 7 is the ATR stand
        contact=True, node_id=node_id,
    ))

_remote_alongs = [560.0 + i * 88.0 for i in range(6)]
for i, along in enumerate(_remote_alongs, start=8):
    sid = f"R{i - 7}"
    pos = _rw(along, STAND_OFFSET - 34.0)
    lane = _rw(along, APRON_LANE_OFFSET)
    node_id = _node(f"ST_{sid}", pos, kind="stand", label=f"Remote {i - 7}")
    _node(f"LN_{sid}", lane, kind="apron")
    _edge(f"E_LEAD_{sid}", f"LN_{sid}", node_id, kind="stand_lead", name=sid, width=18, speed=8)
    _stands.append(Stand(
        id=sid, name=f"Remote {i - 7}", pos=pos, heading_deg=STAND_HEADING,
        max_category="C", contact=False, node_id=node_id,
    ))

# Chain the stand lead-in junctions along the apron taxilane, so the taxilane
# is a real sequence of single-occupancy blocks rather than one huge free-for-all.
_lane_nodes = sorted(
    [nid for nid in _nodes if nid.startswith("LN_")] + ["AP_S", "AP_MID", "AP_N"],
    key=lambda nid: distance_m(THR_04, _nodes[nid].pos),
)
_edges.pop("E_APRON_S_MID", None)
_edges.pop("E_APRON_MID_N", None)
for a, b in zip(_lane_nodes, _lane_nodes[1:]):
    _edge(f"E_LANE_{a}_{b}", a, b, kind="taxilane", name="Apron", width=25, speed=10)

# ---------------------------------------------------------------------------
# Buildings
# ---------------------------------------------------------------------------
_terminal_center = _rw(1465.0, TERMINAL_OFFSET)
_buildings = [
    Building(
        id="nitb", name="New Integrated Terminal",
        center=_terminal_center, width_m=164.0, depth_m=62.0,
        rotation_deg=RWY_HEADING, height_m=22.0, kind="terminal",
        color=(203, 213, 225),
    ),
    Building(
        id="old-terminal", name="Old Domestic Terminal",
        center=_rw(1120.0, TERMINAL_OFFSET - 10), width_m=62.0, depth_m=34.0,
        rotation_deg=RWY_HEADING, height_m=12.0, kind="terminal",
        color=(214, 197, 168),
    ),
    Building(
        id="atc", name="VABO Control Tower",
        center=_rw(1620.0, TWY_A_OFFSET - 70), width_m=16.0, depth_m=16.0,
        rotation_deg=RWY_HEADING, height_m=34.0, kind="tower",
        color=(226, 232, 240),
    ),
    Building(
        id="hangar-iaf", name="IAF No. 36 Wing Hangar",
        center=_rw(560.0, STAND_OFFSET - 40), width_m=84.0, depth_m=54.0,
        rotation_deg=RWY_HEADING, height_m=18.0, kind="hangar",
        color=(120, 128, 138),
    ),
    Building(
        id="fire", name="Fire & Rescue Station",
        center=_rw(1940.0, TWY_A_OFFSET - 60), width_m=34.0, depth_m=22.0,
        rotation_deg=RWY_HEADING, height_m=9.0, kind="support",
        color=(185, 74, 62),
    ),
    Building(
        id="cargo", name="Cargo & GSE Compound",
        center=_rw(2020.0, APRON_LANE_OFFSET - 44), width_m=48.0, depth_m=30.0,
        rotation_deg=RWY_HEADING, height_m=10.0, kind="support",
        color=(140, 146, 152),
    ),
]


def build():
    nodes, edges = merge_close_nodes(dict(_nodes), dict(_edges))
    return AirportLayout(
        icao="VABO",
        iata="BDQ",
        name="Vadodara Airport (Harni)",
        city="Vadodara",
        slug="vadodara",
        arp=_rw(RWY_LENGTH / 2, 0.0),
        elevation_m=39.0,
        timezone="Asia/Kolkata",
        runways=[Runway(
            name="04/22",
            length_m=RWY_LENGTH,
            width_m=RWY_WIDTH,
            ends=[
                RunwayEnd(ident="04", threshold=THR_04, heading_deg=RWY_HEADING,
                          ils_category="CAT_I", minima_visibility_m=1200, minima_ceiling_ft=200),
                RunwayEnd(ident="22", threshold=THR_22, heading_deg=(RWY_HEADING + 180) % 360,
                          ils_category="NONE", minima_visibility_m=2400, minima_ceiling_ft=400,
                          approach_lights=False),
            ],
        )],
        nodes=nodes,
        edges=edges,
        stands=list(_stands),
        buildings=list(_buildings),
        movements_per_hour=10,
        fleet_mix={"A20N": 0.38, "B738": 0.14, "A321": 0.12, "AT76": 0.22, "Q400": 0.09, "B38M": 0.05},
        airlines=["6E", "AI", "SG", "QP", "IX", "UK"],
        default_wind_dir_deg=250.0,
        default_wind_kt=9.0,
        notes=(
            "Single CAT I runway, 13 Code C stands. Aerodrome has no CAT II/III "
            "capability, so low-visibility events suspend arrivals rather than "
            "merely slowing them."
        ),
    )
