/**
 * Disruption Layers
 * =================
 * Spatial disruptions get real deck.gl layers, not a screen overlay - a
 * closed runway has an actual position and heading, a closed taxiway has an
 * actual centreline, and the emergency-arrival aircraft has an actual flight
 * to sit next to. See components/WeatherFX.jsx / lib/weatherFX.js for the
 * atmospheric effects (fog, rain, wind) that genuinely are screen-space.
 *
 * All three read live twin state each frame (closed runway/taxiway names,
 * which aircraft is tagged `emergency`) rather than the disruption event
 * that caused them, so they stay correct even if the underlying cause
 * changes or a page reload catches the twin mid-disruption.
 */
import { PathLayer, ScatterplotLayer } from "@deck.gl/layers";

const R_EARTH_M = 6371000;

// Minimal client-side geodesy - just enough to place a cross-mark and dash a
// line, mirroring core/geo.py's `destination`/`distance_m` at the precision
// this needs (airport-scale distances, not navigation).
function destination([lng, lat], bearingDeg, meters) {
  const brng = (bearingDeg * Math.PI) / 180;
  const lat1 = (lat * Math.PI) / 180;
  const lng1 = (lng * Math.PI) / 180;
  const dOverR = meters / R_EARTH_M;
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(dOverR) + Math.cos(lat1) * Math.sin(dOverR) * Math.cos(brng)
  );
  const lng2 =
    lng1 +
    Math.atan2(
      Math.sin(brng) * Math.sin(dOverR) * Math.cos(lat1),
      Math.cos(dOverR) - Math.sin(lat1) * Math.sin(lat2)
    );
  return [(lng2 * 180) / Math.PI, (lat2 * 180) / Math.PI];
}

function distanceM([lng1, lat1], [lng2, lat2]) {
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R_EARTH_M * Math.asin(Math.sqrt(a));
}

/** Two diagonal line segments forming a big "closed" X across the pavement. */
function runwayXMark(rwy) {
  const a = rwy.ends[0].threshold;
  const heading = rwy.ends[0].heading_deg;
  const len = rwy.length_m;
  const halfW = (rwy.width_m / 2) * 0.85;
  const point = (t, side) => {
    const centre = destination(a, heading, len * t);
    return side === 0 ? centre : destination(centre, heading + 90, halfW * side);
  };
  return [
    [point(0.24, -1), point(0.76, 1)],
    [point(0.24, 1), point(0.76, -1)],
  ];
}

/** Break a polyline into alternating draw/gap segments for a dashed look
 *  (deck.gl's PathLayer has no native dashing without the extensions
 *  package, and this is the only place that needs it). */
function dashPath(path, dashM = 14, gapM = 10) {
  const segments = [];
  let drawing = true;
  let remaining = dashM;
  let current = drawing ? [path[0]] : null;

  for (let i = 0; i < path.length - 1; i++) {
    let a = path[i];
    const b = path[i + 1];
    let segLen = distanceM(a, b);
    while (segLen > 0) {
      const step = Math.min(remaining, segLen);
      const t = step / segLen;
      const mid = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      if (drawing) {
        if (!current) current = [a];
        current.push(mid);
      }
      remaining -= step;
      segLen -= step;
      a = mid;
      if (remaining <= 0.0001) {
        if (drawing && current && current.length > 1) segments.push(current);
        drawing = !drawing;
        remaining = drawing ? dashM : gapM;
        current = drawing ? [a] : null;
      }
    }
  }
  if (drawing && current && current.length > 1) segments.push(current);
  return segments;
}

export function buildDisruptionLayers(layout, twin, renderFlights, nowMs) {
  if (!layout || !twin) return [];
  const layers = [];
  const blink = 0.5 + 0.5 * Math.sin(nowMs / 260);

  // --- Closed runway(s): a pulsing red X across the pavement plus red
  // beacons at both thresholds. ------------------------------------------
  const closedRunwayNames = new Set(
    (twin.runways || []).filter((r) => r.closed).map((r) => r.name)
  );
  if (closedRunwayNames.size) {
    const xPaths = [];
    const beacons = [];
    for (const rwy of layout.runways || []) {
      if (!closedRunwayNames.has(rwy.name)) continue;
      xMarkSafe(rwy, xPaths);
      beacons.push(rwy.ends[0].threshold, rwy.ends[1].threshold);
    }
    if (xPaths.length) {
      layers.push(
        new PathLayer({
          id: "disruption-runway-closed-x",
          data: xPaths,
          getPath: (d) => d,
          getColor: [235, 45, 45, Math.round(150 + 100 * blink)],
          getWidth: 3.2,
          widthMinPixels: 4,
          pickable: false,
        })
      );
      layers.push(
        new ScatterplotLayer({
          id: "disruption-runway-closed-beacons",
          data: beacons,
          getPosition: (d) => d,
          getRadius: 5 + blink * 2.5,
          radiusUnits: "meters",
          getFillColor: [255, 40, 30, Math.round(180 + 75 * blink)],
          pickable: false,
        })
      );
    }
  }

  // --- Closed taxiway(s): dashed red highlight over the actual closed
  // centreline segments, whichever taxiway(s) the console closed. ---------
  const closedEdgeIds = new Set(twin.ground?.closed_edges || []);
  if (closedEdgeIds.size) {
    const closedLines = (layout.visuals?.centerlines || []).filter((c) => closedEdgeIds.has(c.id));
    const dashes = [];
    for (const line of closedLines) dashes.push(...dashPath(line.path));
    if (dashes.length) {
      layers.push(
        new PathLayer({
          id: "disruption-taxiway-closed",
          data: dashes,
          getPath: (d) => d,
          getColor: [235, 55, 55, Math.round(170 + 80 * blink)],
          getWidth: 2.4,
          widthMinPixels: 3,
          pickable: false,
        })
      );
    }
  }

  // --- Emergency arrival: a pulsing amber halo around the actual aircraft
  // that was tagged emergency, wherever it currently is. -------------------
  const emergencyFlight = (renderFlights || []).find((f) => f.emergency);
  if (emergencyFlight) {
    layers.push(
      new ScatterplotLayer({
        id: "disruption-emergency-halo",
        data: [emergencyFlight],
        getPosition: (d) => [d.lng, d.lat, d.altitude || 0],
        getRadius: 24 + blink * 10,
        radiusUnits: "meters",
        stroked: true,
        filled: false,
        getLineColor: [255, 150, 20, Math.round(160 + 90 * blink)],
        lineWidthMinPixels: 2.5,
        pickable: false,
      })
    );
  }

  return layers;
}

function xMarkSafe(rwy, out) {
  try {
    const paths = runwayXMark(rwy);
    out.push(...paths);
  } catch {
    // Malformed runway geometry shouldn't take the whole layer stack down -
    // just skip the mark for this runway.
  }
}
