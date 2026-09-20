/**
 * Aircraft Layer
 * ==============
 * Renders the live `flights` array using the repo's real aircraft.glb - the
 * same optimized model (17 draw calls, 2.9 MB, PBR materials, Z-up corrected)
 * that shipped in the original build - via deck.gl's ScenegraphLayer, not a
 * flat billboard icon. This is a 3D digital twin: aircraft are meshes with
 * pitch/roll/heading and altitude, not sprites.
 *
 * Orientation formula and sizeScale are carried over unchanged from the
 * original App.jsx (git history: 92e8316, 4d799e2, 9b113df) - that's tuned,
 * hard-won knowledge (the axis-convention fix and the 540-draw-call
 * optimization pass both live in the .glb itself and in this orientation
 * mapping), not something to rederive from scratch.
 */
import { ScenegraphLayer } from "@deck.gl/mesh-layers";
import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";

const STATUS_TINT = {
  hold_short: [255, 210, 160],
  lineup: [255, 190, 130],
  takeoff_roll: [255, 230, 150],
  go_around: [255, 170, 220],
  final: [255, 235, 180],
  diverted: [255, 130, 130],
};

// A modest fuselage-length trim (see getScale below) - 1.0 would be the
// model's true proportions; smaller shortens it. 0.88 reads as "slightly
// shorter", not a visibly different aircraft.
const FUSELAGE_LENGTH_FACTOR = 0.88;

export function buildAircraftLayers(flights, opts = {}) {
  const showLabels = opts.showLabels !== false;
  const data = flights || [];
  const selectedId = opts.selectedId || null;

  const layers = [
    // Ground shadow, drawn first so the model always renders over it. A
    // flat dark ellipse straight beneath each aircraft, sized off the same
    // model_scale driving the glTF itself and fading out with altitude -
    // a parked or taxiing aircraft with nothing grounding it to the apron
    // was the single biggest reason the fleet read as "pasted on" rather
    // than sitting on the pavement.
    new ScatterplotLayer({
      id: "aircraft-shadow",
      data,
      getPosition: (d) => [d.lng, d.lat, 0.05],
      getRadius: (d) => (d.model_scale || 1.0) * 16,
      getFillColor: (d) => {
        const alt = d.altitude || 0;
        const alpha = Math.max(0, 1 - alt / 55) * 130;
        return [10, 10, 12, alpha];
      },
      radiusUnits: "meters",
      stroked: false,
      filled: true,
      pickable: false,
      updateTriggers: { getPosition: data, getFillColor: data },
    }),
    new ScenegraphLayer({
      id: "aircraft-3d-model",
      data,
      scenegraph: "/aircraft.glb",
      getPosition: (d) => [d.lng, d.lat, d.altitude || 0],
      // pitch/roll come straight from the simulation's kinematic model
      // (core/twin_sim.py _traverse); heading is compass bearing, converted
      // to the model's own forward axis with the -heading+90 term.
      getOrientation: (d) => [d.pitch || 0, -(d.heading || 0) + 90, d.roll || 0],
      getScale: (d) => {
        const s = (d.model_scale || 1.0) * 28;
        // Non-uniform on purpose: the model's local axes are X=fuselage
        // length, Y=wingspan, Z=height (measured and recorded when the GLB
        // was optimized - see git history on this file's predecessor,
        // commit 9b113df). Shortening only X trims the fuselage without
        // also shrinking the wingspan or height, which a uniform scale
        // would do. FUSELAGE_LENGTH_FACTOR is the one knob to touch if this
        // needs to be shorter or longer still.
        return [s * FUSELAGE_LENGTH_FACTOR, s, s];
      },
      getColor: (d) =>
        d.id === selectedId
          ? [120, 200, 255, 255]
          : [...(STATUS_TINT[d.status] || [255, 255, 255]), 255],
      sizeScale: 1,
      _lighting: "pbr",
      pickable: true,
      // Selection itself is handled by DeckGL's top-level onClick in
      // App.jsx (it needs to tell a hit on THIS layer apart from a click on
      // the airfield beneath it, which is also pickable-adjacent); this
      // layer only needs to stay pickable and reflect the current selection
      // in its color.
      // No deck.gl `transitions` here on purpose: `data` already arrives
      // pre-interpolated every animation frame (see
      // ui/src/lib/motionInterpolator.js), which is smoother than tweening
      // linearly between two 15 Hz broadcast snapshots and would otherwise
      // fight with that interpolation instead of complementing it.
      updateTriggers: {
        getPosition: data,
        getOrientation: data,
        getColor: [selectedId, data.map((d) => d.status).join(",")],
      },
    }),
  ];

  if (showLabels) {
    layers.push(
      new TextLayer({
        id: "aircraft-labels",
        data,
        getPosition: (d) => [d.lng, d.lat, (d.altitude || 0) + 10],
        getText: (d) => d.id,
        getSize: 10,
        getColor: [230, 236, 245, 220],
        getPixelOffset: [0, -18],
        fontFamily: "monospace",
        billboard: true,
        pickable: false,
        updateTriggers: { getPosition: data },
      })
    );
  }

  return layers;
}
