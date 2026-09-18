"""
AeroTwin Fleet
==============
Aircraft types, with the performance numbers the simulation actually needs.

The old build moved every aircraft at the same invented speeds, which is why
nothing about the ground movement felt right: an ATR 72 and an A321 taxied,
rotated and rolled out identically. Here each type carries published figures -
takeoff distance required, rotation and approach speeds, climb rate, wingspan,
wake category - and the SimPy processes are driven by them.

Two consequences that matter for the twin's realism:
  * Separation is wake-category based, so a heavy departing ahead of a light
    costs more runway time than a narrow-body pair.
  * Takeoff distance required decides whether an intersection departure is even
    legal from a given link - a loaded A321 needs the full length at VABO, a
    Q400 does not.

Figures are typical sea-level ISA values at a representative operating weight;
they are simulation inputs, not performance-manual data.
"""
from __future__ import annotations

from dataclasses import dataclass


# ICAO wake turbulence categories used for departure/arrival separation.
WAKE_LIGHT, WAKE_MEDIUM, WAKE_HEAVY = "L", "M", "H"

# Minimum separation on the runway between successive departures, in seconds,
# keyed by (leading wake, following wake). ICAO Doc 4444 style.
WAKE_SEPARATION_S = {
    ("H", "H"): 90, ("H", "M"): 120, ("H", "L"): 180,
    ("M", "H"): 60, ("M", "M"): 60, ("M", "L"): 120,
    ("L", "H"): 60, ("L", "M"): 60, ("L", "L"): 60,
}

# Minimum time an arrival pair must be spaced by on final, seconds.
ARRIVAL_SEPARATION_S = {
    ("H", "H"): 96, ("H", "M"): 120, ("H", "L"): 144,
    ("M", "H"): 82, ("M", "M"): 82, ("M", "L"): 120,
    ("L", "H"): 82, ("L", "M"): 82, ("L", "L"): 82,
}


@dataclass(frozen=True)
class AircraftType:
    code: str               # ICAO type designator
    name: str
    wake: str
    category: str           # ICAO aerodrome reference code letter
    wingspan_m: float
    length_m: float
    seats: int
    # Ground performance
    taxi_speed_kt: float
    max_taxi_speed_kt: float
    pushback_speed_kt: float
    turnaround_min: float
    # Runway performance
    todr_m: float           # takeoff distance required (dry, typical weight)
    ldr_m: float            # landing distance required
    v_rotate_kt: float
    v2_kt: float
    # Air performance
    climb_rate_fpm: float
    climb_speed_kt: float
    approach_speed_kt: float
    exit_speed_kt: float    # speed a rapid exit can be taken at
    model_scale: float = 1.0   # relative size for the 3D model in the client


FLEET = {
    "A20N": AircraftType(
        code="A20N", name="Airbus A320neo", wake=WAKE_MEDIUM, category="C",
        wingspan_m=35.8, length_m=37.6, seats=180,
        taxi_speed_kt=15, max_taxi_speed_kt=25, pushback_speed_kt=3, turnaround_min=35,
        todr_m=1950, ldr_m=1500, v_rotate_kt=140, v2_kt=150,
        climb_rate_fpm=2400, climb_speed_kt=250, approach_speed_kt=138, exit_speed_kt=28,
        model_scale=1.0,
    ),
    "A321": AircraftType(
        code="A321", name="Airbus A321neo", wake=WAKE_MEDIUM, category="C",
        wingspan_m=35.8, length_m=44.5, seats=222,
        taxi_speed_kt=15, max_taxi_speed_kt=25, pushback_speed_kt=3, turnaround_min=40,
        todr_m=2280, ldr_m=1680, v_rotate_kt=148, v2_kt=158,
        climb_rate_fpm=2100, climb_speed_kt=250, approach_speed_kt=144, exit_speed_kt=25,
        model_scale=1.12,
    ),
    "B738": AircraftType(
        code="B738", name="Boeing 737-800", wake=WAKE_MEDIUM, category="C",
        wingspan_m=35.8, length_m=39.5, seats=189,
        taxi_speed_kt=15, max_taxi_speed_kt=25, pushback_speed_kt=3, turnaround_min=35,
        todr_m=2100, ldr_m=1600, v_rotate_kt=145, v2_kt=155,
        climb_rate_fpm=2200, climb_speed_kt=250, approach_speed_kt=142, exit_speed_kt=27,
        model_scale=1.02,
    ),
    "B38M": AircraftType(
        code="B38M", name="Boeing 737 MAX 8", wake=WAKE_MEDIUM, category="C",
        wingspan_m=35.9, length_m=39.5, seats=189,
        taxi_speed_kt=15, max_taxi_speed_kt=25, pushback_speed_kt=3, turnaround_min=35,
        todr_m=2000, ldr_m=1550, v_rotate_kt=143, v2_kt=153,
        climb_rate_fpm=2500, climb_speed_kt=250, approach_speed_kt=140, exit_speed_kt=27,
        model_scale=1.02,
    ),
    "AT76": AircraftType(
        code="AT76", name="ATR 72-600", wake=WAKE_MEDIUM, category="B",
        wingspan_m=27.1, length_m=27.2, seats=78,
        taxi_speed_kt=13, max_taxi_speed_kt=20, pushback_speed_kt=3, turnaround_min=25,
        todr_m=1290, ldr_m=1050, v_rotate_kt=100, v2_kt=108,
        climb_rate_fpm=1350, climb_speed_kt=170, approach_speed_kt=105, exit_speed_kt=22,
        model_scale=0.74,
    ),
    "Q400": AircraftType(
        code="Q400", name="De Havilland Dash 8 Q400", wake=WAKE_MEDIUM, category="C",
        wingspan_m=28.4, length_m=32.8, seats=78,
        taxi_speed_kt=14, max_taxi_speed_kt=22, pushback_speed_kt=3, turnaround_min=25,
        todr_m=1400, ldr_m=1290, v_rotate_kt=110, v2_kt=118,
        climb_rate_fpm=1500, climb_speed_kt=230, approach_speed_kt=115, exit_speed_kt=24,
        model_scale=0.82,
    ),
    "B78X": AircraftType(
        code="B78X", name="Boeing 787-9", wake=WAKE_HEAVY, category="E",
        wingspan_m=60.1, length_m=62.8, seats=296,
        taxi_speed_kt=15, max_taxi_speed_kt=25, pushback_speed_kt=3, turnaround_min=75,
        todr_m=2800, ldr_m=1900, v_rotate_kt=155, v2_kt=165,
        climb_rate_fpm=2300, climb_speed_kt=280, approach_speed_kt=148, exit_speed_kt=25,
        model_scale=1.55,
    ),
    "B77W": AircraftType(
        code="B77W", name="Boeing 777-300ER", wake=WAKE_HEAVY, category="E",
        wingspan_m=64.8, length_m=73.9, seats=396,
        taxi_speed_kt=15, max_taxi_speed_kt=25, pushback_speed_kt=3, turnaround_min=90,
        todr_m=3100, ldr_m=2100, v_rotate_kt=165, v2_kt=175,
        climb_rate_fpm=2000, climb_speed_kt=280, approach_speed_kt=152, exit_speed_kt=24,
        model_scale=1.75,
    ),
}

CATEGORY_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5}


def get(code: str) -> AircraftType:
    return FLEET.get(code, FLEET["A20N"])


def fits_stand(ac: AircraftType, stand_max_category: str) -> bool:
    return CATEGORY_ORDER.get(ac.category, 9) <= CATEGORY_ORDER.get(stand_max_category, 2)


def departure_separation_s(leader: AircraftType, follower: AircraftType) -> float:
    return WAKE_SEPARATION_S.get((leader.wake, follower.wake), 90)


def arrival_separation_s(leader: AircraftType, follower: AircraftType) -> float:
    return ARRIVAL_SEPARATION_S.get((leader.wake, follower.wake), 100)


def pick_type(fleet_mix: dict, rng) -> AircraftType:
    """Weighted random type from an airport's fleet mix."""
    codes = list(fleet_mix)
    weights = [fleet_mix[c] for c in codes]
    return get(rng.choices(codes, weights=weights, k=1)[0])
