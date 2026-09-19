/**
 * Airfield Layers
 * ===============
 * Turns the server's generated `layout.visuals` into Deck.GL layers. This
 * file draws nothing of its own - no hard-coded runway coordinates, no
 * approximated taxiway - every polygon, dash and light position was computed
 * server-side by core/airports/geometry.py from the same structure the
 * simulation itself flies aircraft over. If the picture and the physics ever
 * disagree, it is a server bug, not a frontend one, which is the point.
 */
import {
  PathLayer,
  PolygonLayer,
  ScatterplotLayer,
  TextLayer,
} from "@deck.gl/layers";

const PAVEMENT_COLOR = {
  runway: [58, 58, 64],
  shoulder: [46, 46, 52],
  taxiway: [50, 52, 58],
  apron: [54, 56, 60],
};

const PAINT_COLOR = {
  threshold: [255, 255, 255],
  aiming: [255, 255, 255],
  tdz: [255, 255, 255],
  centerline: [255, 214, 90],
};

const BUILDING_HEIGHT_SCALE = 1.0;

export function buildAirfieldLayers(layout, opts = {}) {
  if (!layout) return [];
  const v = layout.visuals || {};
  const showLights = opts.showLights !== false;
  const showSigns = opts.showSigns !== false;
  const layers = [];

  // --- Pavement: runway, shoulders, taxiways, apron -----------------------
  layers.push(
    new PolygonLayer({
      id: "pavement",
      data: v.pavement || [],
      getPolygon: (d) => d.polygon,
      getFillColor: (d) => PAVEMENT_COLOR[d.kind] || [48, 48, 54],
      getLineWidth: 0,
      stroked: false,
      filled: true,
      pickable: false,
    })
  );

  // --- Paint: piano keys, aiming points, TDZ bars, centreline dashes ------
  layers.push(
    new PolygonLayer({
      id: "paint",
      data: v.paint || [],
      getPolygon: (d) => d.polygon,
      getFillColor: (d) => PAINT_COLOR[d.kind] || [255, 255, 255],
      stroked: false,
      filled: true,
      pickable: false,
    })
  );

  // --- Hold-short bars (ICAO pattern A) ------------------------------------
  layers.push(
    new PolygonLayer({
      id: "hold-bars",
      data: v.hold_bars || [],
      getPolygon: (d) => d.polygon,
      getFillColor: [255, 214, 0],
      stroked: false,
      filled: true,
      pickable: false,
    })
  );

  // --- Stand stop bars ------------------------------------------------------
  layers.push(
    new PolygonLayer({
      id: "stand-marks",
      data: v.stand_marks || [],
      getPolygon: (d) => d.polygon,
      getFillColor: [255, 255, 255],
      stroked: false,
      filled: true,
      pickable: false,
    })
  );

  // --- Taxiway / runway centrelines (thin path, closed edges dimmed) -----
  layers.push(
    new PathLayer({
      id: "centerlines",
      data: (v.centerlines || []).filter((c) => c.kind !== "lead_in"),
      getPath: (d) => d.path,
      getColor: (d) => (d.closed ? [180, 60, 60, 180] : [255, 214, 90, 140]),
      getWidth: 0.4,
      widthMinPixels: 1,
      pickable: false,
    })
  );

  // --- Buildings, extruded as flat-shaded polygons (no 3D lib needed) -----
  layers.push(
    new PolygonLayer({
      id: "buildings",
      data: v.buildings || [],
      getPolygon: (d) => d.polygon,
      getElevation: (d) => d.height * BUILDING_HEIGHT_SCALE,
      getFillColor: (d) => [...d.color, 255],
      extruded: true,
      wireframe: false,
      pickable: true,
    })
  );

  // --- Lights: edge, threshold/end, approach, PAPI, taxiway blue ---------
  if (showLights) {
    layers.push(
      new ScatterplotLayer({
        id: "lights",
        data: v.lights || [],
        getPosition: (d) => d.position,
        getFillColor: (d) => d.color,
        getRadius: 1.1,
        radiusMinPixels: 1.5,
        radiusMaxPixels: 4,
        pickable: false,
      })
    );
  }

  // --- Labels: runway designators, stand names ----------------------------
  layers.push(
    new TextLayer({
      id: "labels",
      data: v.labels || [],
      getPosition: (d) => d.position,
      getText: (d) => d.text,
      getSize: (d) => d.size || 12,
      getAngle: (d) => 0,
      getColor: [255, 255, 255, 230],
      fontFamily: "monospace",
      fontWeight: "bold",
      billboard: true,
      pickable: false,
    })
  );

  // --- Mandatory / location signs -----------------------------------------
  if (showSigns) {
    layers.push(
      new TextLayer({
        id: "signs",
        data: v.signs || [],
        getPosition: (d) => d.position,
        getText: (d) => d.text,
        getSize: 11,
        getColor: (d) => (d.kind === "mandatory" ? [255, 210, 70, 255] : [140, 190, 255, 220]),
        getBackgroundColor: (d) => (d.kind === "mandatory" ? [130, 20, 20, 220] : [10, 30, 60, 200]),
        background: true,
        backgroundPadding: [3, 2],
        fontFamily: "monospace",
        billboard: true,
        pickable: false,
      })
    );
  }

  return layers;
}

/** Camera target: the airport's ARP, used for the initial fly-to. */
export function airportViewState(layout) {
  if (!layout) return null;
  const [lng, lat] = layout.arp;
  return {
    longitude: lng,
    latitude: lat,
    zoom: 15.4,
    pitch: 55,
    bearing: layout.runways?.[0]?.ends?.[0]?.heading_deg ?? 0,
  };
}

// --- small client-side geodesy, just enough for camera aiming ------------
// Mirrors the relevant bits of core/geo.py. Kept minimal on purpose - this is
// for pointing a camera, not for anything the simulation depends on.
function bearingDeg([lng1, lat1], [lng2, lat2]) {
  const toRad = (d) => (d * Math.PI) / 180;
  const dLng = toRad(lng2 - lng1);
  const y = Math.sin(dLng) * Math.cos(toRad(lat2));
  const x =
    Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
    Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(dLng);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

/**
 * Tower-cab camera: positioned AT the airport's control tower, looking out
 * toward the field - not just "zoomed in on the runway" (what this used to
 * do). The camera target is the tower's own ground position (from the
 * `position` field geometry.py now sends on every building), the bearing is
 * computed to face the runway, and the pitch is steep enough to feel like
 * looking down from height rather than the top-down orbit view.
 *
 * MapView's camera always looks AT its target from a distance implied by
 * zoom, so this can't place the eye at an exact metre altitude the way a
 * dedicated FirstPersonView could - doing that would mean dropping the
 * MapLibre satellite basemap, since react-map-gl only syncs to a standard
 * Web Mercator view. What this gets right, and what actually mattered: a
 * real vantage point (the tower's coordinates, not the airport centre) and a
 * real look-at direction (out across the runway, not down at it).
 */
export function towerViewState(layout) {
  if (!layout) return airportViewState(layout);
  const tower = (layout.buildings || []).find((b) => b.kind === "tower");
  const rwy = layout.runways?.[0];
  if (!tower || !rwy) return { ...airportViewState(layout), pitch: 75, zoom: 17.2 };

  const towerPos = tower.position; // [lng, lat]
  const aimAt = rwy.ends[0].threshold; // [lng, lat] - look out toward the runway
  const bearing = bearingDeg(towerPos, aimAt);

  return {
    longitude: towerPos[0],
    latitude: towerPos[1],
    zoom: 17.6,
    pitch: 80,
    bearing,
  };
}
