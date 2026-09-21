/**
 * Flight Details
 * ==============
 * The simulation broadcasts everything it actually knows about a flight -
 * type, seats, status, the airport at the other end of the route, current
 * stand. It does not model a passenger manifest, a flight number distinct
 * from the ATC callsign, or a gate assignment, because none of that affects
 * how the twin behaves - it would just be UI decoration.
 *
 * The detail panel wants that decoration, so it's generated here instead:
 * deterministically, seeded from the flight's own callsign, so the same
 * aircraft shows the same "flight" every time you look at it rather than a
 * new one every animation frame.
 */

const AIRLINE_NAMES = {
  "6E": "IndiGo", AI: "Air India", UK: "Vistara", SG: "SpiceJet",
  IX: "Air India Express", QP: "Akasa Air", EK: "Emirates", SQ: "Singapore Airlines",
};

// Airports the twin can simulate aren't necessarily the only place a flight
// is headed - DESTINATIONS in core/twin_sim.py includes a few that never
// get their own layout. Named here so the route line always reads as a real
// place rather than a bare ICAO code.
const FALLBACK_AIRPORT_NAMES = {
  VOBL: "Bengaluru", VOMM: "Chennai", VOHS: "Hyderabad", VECC: "Kolkata",
  VOGO: "Goa", VOCI: "Kochi", VIJP: "Jaipur",
};

function hashSeed(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// mulberry32 - small, fast, deterministic from a 32-bit seed.
function mulberry32(seed) {
  let a = seed;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function cityFor(icao, airports) {
  if (!icao) return null;
  const known = (airports || []).find((a) => a.icao === icao);
  if (known) return known.city || known.name;
  return FALLBACK_AIRPORT_NAMES[icao] || icao;
}

const REG_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

/**
 * Build the full detail set for one flight. `airports` is the directory
 * from GET /api/airports (App.jsx already fetches it), used to resolve the
 * other end of the route to a real name instead of a bare ICAO code.
 */
export function buildFlightDetails(flight, airports, homeAirport) {
  if (!flight) return null;
  const rng = mulberry32(hashSeed(flight.id));

  const [airlineCode] = flight.id.split("-");
  const airlineName = AIRLINE_NAMES[airlineCode] || airlineCode;
  const flightNumber = `${airlineCode} ${100 + Math.floor(rng() * 899)}`;

  const isArrival = flight.direction === "ARR";
  const homeName = homeAirport ? homeAirport.city || homeAirport.name : null;
  const otherName = cityFor(flight.other_airport, airports);
  const origin = isArrival ? otherName : homeName;
  const destination = isArrival ? homeName : otherName;

  const seats = flight.seats || 150;
  const loadFactor = 0.62 + rng() * 0.33; // a typical 62-95% load
  const passengers = Math.max(4, Math.round(seats * loadFactor));

  const reg = `VT-${REG_LETTERS[Math.floor(rng() * 26)]}${REG_LETTERS[Math.floor(rng() * 26)]}${REG_LETTERS[Math.floor(rng() * 26)]}`;
  const squawk = String(1000 + Math.floor(rng() * 6999)).padStart(4, "0");

  const gate = flight.stand_name
    || `${["T1", "T2", "T3"][Math.floor(rng() * 3)]} • Gate ${1 + Math.floor(rng() * 24)}`;

  return {
    flightNumber,
    callsign: flight.id,
    airline: airlineName,
    aircraftType: flight.type_name || flight.type,
    registration: reg,
    origin: origin || "—",
    destination: destination || "—",
    passengers,
    seats,
    loadFactor,
    gate,
    squawk,
  };
}
