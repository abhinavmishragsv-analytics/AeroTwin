/**
 * Aircraft Layer
 * ==============
 * Renders the live `flights` array from a traffic frame. Each aircraft is a
 * simple triangular glyph sized by `model_scale` (from core/aircraft.py) and
 * coloured by status, oriented by heading - deliberately lightweight rather
 * than a GLB model, since the previous build's biggest cost was 540 draw
 * calls for a single mesh; this keeps every frame cheap at any traffic level.
 */
import { IconLayer, TextLayer } from "@deck.gl/layers";

const STATUS_COLOR = {
  parked: [110, 118, 130],
  scheduled: [110, 118, 130],
  pushback: [200, 170, 90],
  taxi_out: [90, 200, 140],
  hold_short: [230, 90, 70],
  lineup: [255, 140, 60],
  takeoff_roll: [255, 200, 60],
  climb: [110, 190, 255],
  inbound: [110, 190, 255],
  approach: [110, 190, 255],
  holding: [200, 130, 255],
  go_around: [255, 90, 200],
  final: [255, 214, 90],
  landing_rollout: [255, 214, 90],
  runway_vacate: [120, 220, 160],
  taxi_in: [90, 200, 140],
  turnaround: [110, 118, 130],
  diverted: [255, 60, 60],
};

// A minimal plane glyph as an inline SVG data URI - no external asset fetch,
// no GLB parse cost, and it scales trivially with model_scale.
//
// width/height are required here, not just viewBox: deck.gl's IconLayer loads
// this through createImageBitmap(), and a browser refuses to rasterize an SVG
// that has no explicit natural dimensions - viewBox alone doesn't count. Without
// them this throws ("SVG image without natural dimensions") and no aircraft
// render at all.
const PLANE_ICON =
  "data:image/svg+xml;base64," +
  btoa(
    `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
      <path d="M32 2 L38 24 L60 34 L60 40 L38 34 L38 46 L48 54 L48 59 L32 55 L16 59 L16 54 L26 46 L26 34 L4 40 L4 34 L26 24 Z"
            fill="white"/>
    </svg>`
  );

export function buildAircraftLayers(flights, opts = {}) {
  const showLabels = opts.showLabels !== false;
  const data = flights || [];

  const icons = new IconLayer({
    id: "aircraft-icons",
    data,
    getPosition: (d) => [d.lng, d.lat, d.altitude || 0],
    getIcon: () => ({ url: PLANE_ICON, width: 64, height: 64, anchorX: 32, anchorY: 32 }),
    getSize: (d) => 16 * (d.model_scale || 1.0) * (d.on_ground === false ? 1.15 : 1.0),
    sizeUnits: "pixels",
    getAngle: (d) => 90 - (d.heading || 0),
    getColor: (d) => STATUS_COLOR[d.status] || [255, 255, 255],
    pickable: true,
    updateTriggers: {
      getPosition: data,
      getAngle: data,
      getColor: data,
      getSize: data,
    },
  });

  const layers = [icons];

  if (showLabels) {
    layers.push(
      new TextLayer({
        id: "aircraft-labels",
        data,
        getPosition: (d) => [d.lng, d.lat, (d.altitude || 0) + 8],
        getText: (d) => d.id,
        getSize: 10,
        getColor: [230, 236, 245, 220],
        getPixelOffset: [0, -16],
        fontFamily: "monospace",
        billboard: true,
        pickable: false,
        updateTriggers: { getPosition: data },
      })
    );
  }

  return layers;
}

export { STATUS_COLOR };
