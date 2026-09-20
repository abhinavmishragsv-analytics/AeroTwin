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
  AmbientLight,
  DirectionalLight,
  LightingEffect,
} from "@deck.gl/core";
import {
  PathLayer,
  PolygonLayer,
  ScatterplotLayer,
  TextLayer,
} from "@deck.gl/layers";

// Real airport pavement isn't a flat, uniformly-saturated fill: aprons are
// very often poured concrete (noticeably lighter and warmer than asphalt,
// chosen for fuel/load resistance under parked aircraft), while runways and
// taxiways are darker, worn asphalt. Modelling that one distinction reads as
// far more "real" against the satellite basemap than a single grey used
// everywhere - which is what made the airfield look like a CAD overlay
// rather than a photographed one.
const PAVEMENT_COLOR = {
  runway: [55, 54, 57],
  shoulder: [74, 71, 64],
  taxiway: [63, 62, 64],
  apron: [121, 118, 109],
};

// A little per-polygon variation - deterministic, not random noise that
// would shimmer frame to frame - stands in for the patch repairs, staining
// and uneven weathering every real apron has and a flat fill can't.
function jitterColor(base, seedKey) {
  let h = 0;
  for (let i = 0; i < seedKey.length; i++) h = (h * 31 + seedKey.charCodeAt(i)) | 0;
  const spread = ((h >>> 0) % 13) - 6; // -6..+6
  return base.map((c) => Math.max(0, Math.min(255, c + spread)));
}

// Real markings are painted white/yellow but read as worn and slightly
// off-tone from above, not the pure, saturated colors a CAD tool defaults
// to - pure white in particular looks distinctly synthetic against satellite
// imagery.
const PAINT_COLOR = {
  threshold: [222, 219, 206],
  aiming: [222, 219, 206],
  tdz: [222, 219, 206],
  centerline: [232, 194, 84],
};

const BUILDING_HEIGHT_SCALE = 1.0;

// A single consistent "sun" for the whole scene: extruded buildings and the
// aircraft's PBR model both pick this up automatically once it's passed to
// DeckGL's `effects` prop (see App.jsx), which is what gives them actual
// directional shading instead of the flat, shadowless look a plain material
// fill has. Angled low and from the north-west for a late-afternoon feel -
// tuned for contrast on building facades and aircraft fuselages, not for
// astronomical accuracy at any particular airport or time.
export const AIRFIELD_LIGHTING_EFFECT = new LightingEffect({
  ambient: new AmbientLight({ color: [255, 250, 240], intensity: 1.35 }),
  sun: new DirectionalLight({
    color: [255, 244, 219],
    intensity: 2.1,
    direction: [-0.7, -0.6, -1],
  }),
});

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
      getFillColor: (d, { index }) =>
        jitterColor(PAVEMENT_COLOR[d.kind] || [48, 48, 54], `${d.kind || ""}-${index}`),
      // A thin, slightly darker seam between adjoining pavement pieces reads
      // as the real tar-and-slab joints and patch edges visible in aerial
      // photos - solid fills with no stroke at all is what made the airfield
      // look like a single flat sticker laid over the satellite tile.
      getLineColor: (d) => PAVEMENT_COLOR[d.kind]?.map((c) => Math.max(0, c - 18)) || [30, 30, 34],
      getLineWidth: 1,
      lineWidthMinPixels: 1,
      stroked: true,
      filled: true,
      pickable: false,
      material: { ambient: 0.6, diffuse: 0.55, shininess: 4, specularColor: [40, 40, 40] },
    })
  );

  // --- Paint: piano keys, aiming points, TDZ bars, centreline dashes ------
  layers.push(
    new PolygonLayer({
      id: "paint",
      data: v.paint || [],
      getPolygon: (d) => d.polygon,
      getFillColor: (d) => PAINT_COLOR[d.kind] || [222, 219, 206],
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
      getFillColor: [242, 200, 40],
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
      getFillColor: [222, 219, 206],
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
      pickable: false,
      // Picked up by AIRFIELD_LIGHTING_EFFECT (see App.jsx's `effects`
      // prop): without an explicit material, deck.gl's default is nearly
      // shadowless, which is why buildings previously looked like flat
      // cut-outs rather than solid extruded volumes.
      material: { ambient: 0.35, diffuse: 0.75, shininess: 24, specularColor: [60, 60, 60] },
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

  // --- Runway designators: paint, not labels ------------------------------
  // The numerals at each threshold are painted ON the runway, so they are
  // drawn ground-aligned, sized in metres, and rotated to the runway heading.
  // Drawing them as billboarded pixel-text (what this used to do) meant they
  // stayed a fixed screen size and always faced the camera - which is why
  // they looked wrong and got clipped at the edges of their glyph cells
  // instead of lying flat on the asphalt like real markings.
  const designators = (v.labels || []).filter((d) => d.kind === "designator");
  const otherLabels = (v.labels || []).filter((d) => d.kind !== "designator");

  const TEXT_FONT = {
    fontFamily: "monospace",
    fontWeight: "bold",
    // SDF glyphs stay crisp at any scale; the generous buffer stops the
    // thick bold strokes touching the edge of their atlas cell.
    fontSettings: { sdf: true, fontSize: 64, buffer: 12, radius: 12 },
    characterSet: "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz -/.",
  };

  layers.push(
    new TextLayer({
      id: "runway-designators",
      data: designators,
      getPosition: (d) => d.position,
      getText: (d) => d.text,
      // Real runway numerals are about 20 m tall.
      getSize: 20,
      sizeUnits: "meters",
      sizeMinPixels: 8,
      // deck.gl measures angle counter-clockwise from east; the server sends a
      // compass heading, and the numerals read UP the runway.
      getAngle: (d) => 90 - (d.angle || 0),
      getColor: [255, 255, 255, 235],
      billboard: false,
      ...TEXT_FONT,
      pickable: false,
    })
  );

  // --- Other labels: stand names, which should stay readable -------------
  layers.push(
    new TextLayer({
      id: "labels",
      data: otherLabels,
      getPosition: (d) => d.position,
      getText: (d) => d.text,
      getSize: (d) => d.size || 12,
      getColor: [255, 255, 255, 220],
      billboard: true,
      ...TEXT_FONT,
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
 * Tower-cam: an elevated, bird's-eye aerial angle framed from the side of the
 * field where the ATC tower actually stands - not the previous version,
 * which put the camera's *target* at the tower and pitched it steep (80 deg),
 * which reads as standing at ground level staring down the runway, not as a
 * bird's-eye shot from the tower's side. That was the wrong read of "tower
 * cab view".
 *
 * The fix keeps the same bird's-eye family of pitch as the orbit view
 * (moderate, not near-horizontal) but frames the shot around the tower's
 * side of the airfield rather than dead-centre over the runway: the camera
 * target is blended most of the way from the airport's centre toward the
 * tower's own coordinates (from the `position` field geometry.py sends on
 * every building), and the bearing faces from the tower toward the field
 * centre, so what's "up" on screen is the direction you'd actually be
 * looking if you were watching from where the tower lives.
 *
 * Still MapView, not a true FirstPersonView eye-level camera - that would
 * mean dropping the MapLibre satellite basemap, since react-map-gl only
 * syncs to a standard Web Mercator view - so this is an aerial angle near
 * the tower's position, not a window-of-the-cab view. That's the right
 * trade for "bird's eye from the side", which is what was actually asked
 * for; it would be the wrong trade for a literal stand-in-the-cab view.
 */
export function towerViewState(layout) {
  if (!layout) return airportViewState(layout);
  const tower = (layout.buildings || []).find((b) => b.kind === "tower");
  if (!tower) return { ...airportViewState(layout), pitch: 58, zoom: 16.2 };

  const towerPos = tower.position; // [lng, lat]
  const arp = layout.arp; // [lng, lat] - the field's centre

  // Bias the framing toward the tower's side without centring on the tower
  // building itself - a shot centred exactly on the tower shows mostly the
  // tower; a shot centred on the field shows nothing of "from the tower's
  // side". 0.55 keeps most of the runway and apron in frame while still
  // reading as offset toward where the tower is.
  const blend = 0.55;
  const longitude = arp[0] + (towerPos[0] - arp[0]) * blend;
  const latitude = arp[1] + (towerPos[1] - arp[1]) * blend;
  const bearing = bearingDeg(towerPos, arp);

  return { longitude, latitude, zoom: 16.2, pitch: 58, bearing };
}
