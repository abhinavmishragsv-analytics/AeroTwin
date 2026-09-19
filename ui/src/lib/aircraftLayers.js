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
import { TextLayer } from "@deck.gl/layers";

const STATUS_TINT = {
  hold_short: [255, 210, 160],
  lineup: [255, 190, 130],
  takeoff_roll: [255, 230, 150],
  go_around: [255, 170, 220],
  final: [255, 235, 180],
  diverted: [255, 130, 130],
};

// Position/orientation transitions are tuned to the backend's broadcast rate
// (core/config.py STREAM_HZ, default 15 Hz) in milliseconds, so the client is
// never interpolating across a gap wider than one real update - faster than
// that and motion stutters between frames, slower and it lags visibly behind.
// Hardcoded rather than fetched: it's a rendering constant, not live state,
// and matches the server default (override AEROTWIN_STREAM_HZ on both ends
// together if you ever change it).
const STREAM_HZ = 15.0;
const FRAME_MS = Math.round(1000 / STREAM_HZ);

export function buildAircraftLayers(flights, opts = {}) {
  const showLabels = opts.showLabels !== false;
  const data = flights || [];

  const layers = [
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
        return [s, s, s];
      },
      getColor: (d) => [...(STATUS_TINT[d.status] || [255, 255, 255]), 255],
      sizeScale: 1,
      _lighting: "pbr",
      pickable: true,
      transitions: {
        getPosition: FRAME_MS * 3,
        getOrientation: FRAME_MS * 3,
      },
      updateTriggers: {
        getPosition: data,
        getOrientation: data,
        getScale: data,
        getColor: data,
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
