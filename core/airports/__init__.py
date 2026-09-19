"""
AeroTwin Airport Registry
=========================
One place that knows every aerodrome the twin can simulate, keyed by both ICAO
code and URL slug. The frontend resolves `/delhi` -> VIDP through
`GET /api/airports`, then opens `ws://.../ws/twin/VIDP`; the backend spins up an
independent SimPy simulation per airport on first connect.

VABO is surveyed in detail (see `vabo.py`). The other airports are built by the
generic builder from their real runway thresholds, with apron arrangements that
are representative rather than surveyed - clearly flagged in each layout's
`notes` so nobody mistakes a plausible apron for a charted one. Adding another
airport is one entry in `_BUILDERS`.
"""
from core.airports.generic import build_airport
from core.airports.geometry import layout_to_dict
from core.airports import vabo


def _vidp():
    # Indira Gandhi International, Delhi. Real IGIA has FOUR runways, not
    # three: two near-parallel 11/29s (11R/29L - the longest, and 11L/29R),
    # plus 10/28 and 09/27. Thresholds below are the published runway-end
    # coordinates for all four; the earlier build modelled only one 11/29
    # runway (treating it as a single "11/29" instead of the real L/R pair)
    # and had all three of its thresholds displaced ~1-4 km from where the
    # real pavement sits.
    return build_airport(
        icao="VIDP", iata="DEL", name="Indira Gandhi International Airport",
        city="Delhi", slug="delhi",
        thresholds=((28.54720, 77.06550), (28.53770, 77.10950)),  # 11R/29L
        idents=("11R", "29L"),
        extra_runways=[
            ("11L/29R", (28.55010, 77.06820), (28.54070, 77.11190), "11L", "29R", 45.0),
            ("10/28", (28.56720, 77.08480), (28.55850, 77.12250), "10", "28", 45.0),
            ("09/27", (28.57050, 77.08800), (28.56980, 77.11700), "09", "27", 45.0),
        ],
        elevation_m=237.0, runway_width=60.0,
        taxiway_offset=-210.0, apron_lane_offset=-330.0, stand_offset=-390.0,
        terminal_offset=-500.0,
        n_contact_stands=20, n_remote_stands=10, stand_spacing_m=110.0,
        # One runway's practical single-runway capacity, not the aerodrome's
        # total: the twin sequences one runway at a time, so quoting Delhi's
        # real all-runway movement rate here would just manufacture go-arounds.
        movements_per_hour=30,
        fleet_mix={"A20N": 0.34, "B738": 0.16, "A321": 0.18, "B78X": 0.12,
                   "B77W": 0.08, "AT76": 0.07, "Q400": 0.05},
        airlines=["6E", "AI", "UK", "SG", "IX", "QP", "EK", "SQ"],
        ils=("CAT_III", "CAT_I"), minima=((200, 50), (1200, 200)),
        default_wind_dir_deg=290.0, default_wind_kt=10.0,
        notes="Runway thresholds are real; apron/stand arrangement is representative, not charted.",
    )


def _vabb():
    # Chhatrapati Shivaji Maharaj International, Mumbai. Main runway 09/27,
    # intersecting 14/32. Thresholds re-surveyed against published runway-end
    # coordinates - the earlier 09/27 pair had the 27 end ~450 m north of
    # where the real runway lies, skewing its heading off the true 89 deg.
    return build_airport(
        icao="VABB", iata="BOM", name="Chhatrapati Shivaji Maharaj International Airport",
        city="Mumbai", slug="mumbai",
        thresholds=((19.08840, 72.84800), (19.08890, 72.88110)),
        idents=("09", "27"),
        extra_runways=[("14/32", (19.09850, 72.85730), (19.08010, 72.87720), "14", "32", 45.0)],
        elevation_m=11.0, runway_width=60.0,
        taxiway_offset=-200.0, apron_lane_offset=-320.0, stand_offset=-380.0,
        terminal_offset=-480.0,
        n_contact_stands=16, n_remote_stands=8, stand_spacing_m=105.0,
        movements_per_hour=28,
        fleet_mix={"A20N": 0.33, "B738": 0.18, "A321": 0.18, "B78X": 0.11,
                   "B77W": 0.09, "AT76": 0.06, "Q400": 0.05},
        airlines=["6E", "AI", "UK", "SG", "IX", "QP", "EK"],
        ils=("CAT_III", "CAT_I"), minima=((300, 50), (1200, 200)),
        default_wind_dir_deg=260.0, default_wind_kt=12.0,
        notes="Runway thresholds are real; apron/stand arrangement is representative, not charted.",
    )


def _vaah():
    # Sardar Vallabhbhai Patel International, Ahmedabad. Runway 05/23,
    # re-surveyed against published threshold coordinates.
    return build_airport(
        icao="VAAH", iata="AMD", name="Sardar Vallabhbhai Patel International Airport",
        city="Ahmedabad", slug="ahmedabad",
        thresholds=((23.06600, 72.62270), (23.08840, 72.64660)),
        idents=("05", "23"),
        elevation_m=58.0,
        n_contact_stands=10, n_remote_stands=6,
        movements_per_hour=20,
        ils=("CAT_I", "CAT_I"),
        default_wind_dir_deg=240.0, default_wind_kt=10.0,
        notes="Runway thresholds are real; apron/stand arrangement is representative, not charted.",
    )


def _vapo():
    # Pune (Lohegaon). Runway 10/28, shared with the Indian Air Force.
    return build_airport(
        icao="VAPO", iata="PNQ", name="Pune Airport (Lohegaon)",
        city="Pune", slug="pune",
        thresholds=((18.58600, 73.90100), (18.58120, 73.93150)),
        idents=("10", "28"),
        elevation_m=594.0,
        n_contact_stands=6, n_remote_stands=4,
        movements_per_hour=14,
        fleet_mix={"A20N": 0.42, "B738": 0.18, "A321": 0.14, "AT76": 0.16, "Q400": 0.10},
        ils=("CAT_I", "NONE"), minima=((1200, 200), (2400, 400)),
        default_wind_dir_deg=270.0, default_wind_kt=8.0,
        notes="Runway thresholds are real; apron/stand arrangement is representative, not charted.",
    )


def _vasu():
    # Surat. Runway 04/22.
    return build_airport(
        icao="VASU", iata="STV", name="Surat International Airport",
        city="Surat", slug="surat",
        thresholds=((21.10900, 72.72900), (21.12350, 72.75050)),
        idents=("04", "22"),
        elevation_m=8.0,
        n_contact_stands=6, n_remote_stands=3,
        movements_per_hour=10,
        fleet_mix={"A20N": 0.45, "B738": 0.15, "A321": 0.1, "AT76": 0.2, "Q400": 0.1},
        ils=("CAT_I", "NONE"), minima=((1200, 200), (2400, 400)),
        default_wind_dir_deg=250.0, default_wind_kt=9.0,
        notes="Runway thresholds are real; apron/stand arrangement is representative, not charted.",
    )


def _vegt():
    # Lokpriya Gopinath Bordoloi International, Guwahati. Runway 02/20, the
    # main gateway to North-East India. Single runway, joint civil/military.
    return build_airport(
        icao="VEGT", iata="GAU", name="Lokpriya Gopinath Bordoloi International Airport",
        city="Guwahati", slug="guwahati",
        thresholds=((26.09470, 91.58060), (26.11750, 91.59120)),
        idents=("02", "20"),
        elevation_m=49.0, runway_width=46.0,
        n_contact_stands=9, n_remote_stands=5,
        movements_per_hour=16,
        fleet_mix={"A20N": 0.40, "B738": 0.14, "A321": 0.16, "AT76": 0.20, "Q400": 0.10},
        airlines=["6E", "AI", "SG", "UK", "IX"],
        ils=("CAT_I", "NONE"), minima=((1200, 200), (2400, 400)),
        default_wind_dir_deg=20.0, default_wind_kt=7.0,
        notes="Runway thresholds are real; apron/stand arrangement is representative, not charted.",
    )


_BUILDERS = {
    "VABO": vabo.build,
    "VIDP": _vidp,
    "VABB": _vabb,
    "VAAH": _vaah,
    "VAPO": _vapo,
    "VASU": _vasu,
    "VEGT": _vegt,
}

DEFAULT_ICAO = "VABO"

_cache = {}


def available_icaos():
    return list(_BUILDERS)


def get_layout(icao: str):
    """Build (and memoise) an airport layout by ICAO code."""
    key = (icao or DEFAULT_ICAO).upper()
    if key not in _BUILDERS:
        raise KeyError(icao)
    if key not in _cache:
        _cache[key] = _BUILDERS[key]()
    return _cache[key]


def resolve(identifier: str):
    """Accept an ICAO code, IATA code or URL slug and return the ICAO code."""
    if not identifier:
        return DEFAULT_ICAO
    want = identifier.strip().lower()
    for icao in _BUILDERS:
        if want == icao.lower():
            return icao
        layout = get_layout(icao)
        if want in (layout.slug.lower(), layout.iata.lower(), layout.city.lower()):
            return icao
    raise KeyError(identifier)


def directory():
    """Lightweight index for the frontend's airport switcher."""
    out = []
    for icao in _BUILDERS:
        lay = get_layout(icao)
        out.append({
            "icao": lay.icao,
            "iata": lay.iata,
            "name": lay.name,
            "city": lay.city,
            "slug": lay.slug,
            "arp": [lay.arp[1], lay.arp[0]],
            "runways": [r.name for r in lay.runways],
            "stands": len(lay.stands),
            "movements_per_hour": lay.movements_per_hour,
            "detail": "surveyed" if icao == "VABO" else "representative",
        })
    return out


__all__ = [
    "available_icaos", "get_layout", "resolve", "directory", "layout_to_dict", "DEFAULT_ICAO",
]
