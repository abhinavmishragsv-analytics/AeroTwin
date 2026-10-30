/**
 * Telemetry helpers: palette, x-axis alignment, and merging of the per-flight
 * series into the single shared x array uPlot needs.
 */
// Series colours tuned for white paper: each keeps >= 3:1 against it and stays
// distinguishable for the common colour-vision deficiencies (blue / orange /
// green / magenta differ in lightness as well as hue).
export const PALETTE = ["#1F5FBF", "#E4630D", "#0E8F6E", "#C2257C", "#6A4BD1", "#0F8CA8"];
export const MAX_COMPARE = 6;

export const EVENT_OPTIONS = {
  ARR: [
    { key: "touchdown", label: "Touchdown" },
    { key: "gate_1000", label: "1000 ft gate" },
    { key: "gate_500", label: "500 ft gate" },
    { key: "runway_clear", label: "Runway vacated" },
  ],
  DEP: [
    { key: "brake_release", label: "Brake release" },
    { key: "vr", label: "Rotate (VR)" },
    { key: "liftoff", label: "Lift-off" },
    { key: "alt_1000", label: "Passing 1000 ft" },
  ],
};

// The part of each leg that is on, or lined up with, the runway - the only
// part where "distance along the runway" is a meaningful shared x axis.
export const RUNWAY_PHASES = {
  ARR: ["final", "landing_rollout"],
  DEP: ["takeoff_roll", "climb"],
};

export const PHASE_LABEL = {
  scheduled: "Scheduled", pushback: "Pushback", taxi_out: "Taxi out", hold_short: "Hold short",
  lineup: "Line-up", takeoff_roll: "Take-off roll", climb: "Climb", airborne: "Airborne",
  inbound: "Inbound", approach: "Approach", holding: "Holding", go_around: "Go-around",
  final: "Final", landing_rollout: "Rollout", runway_vacate: "Vacating", taxi_in: "Taxi in",
  turnaround: "Turnaround", parked: "Parked", diverted: "Diverted",
};

export const PHASE_COLOR = {
  pushback: "#5B6B82", taxi_out: "#6F83A0", hold_short: "#B7791F", lineup: "#C28A12",
  takeoff_roll: "#D9560B", climb: "#0E8F6E", airborne: "#0E8F6E",
  inbound: "#2F6FD0", holding: "#6A4BD1", approach: "#0F8CA8", go_around: "#C2257C",
  final: "#0B7A94", landing_rollout: "#D9560B", runway_vacate: "#C28A12", taxi_in: "#6F83A0",
  turnaround: "#5B6B82", parked: "#4A5A70", diverted: "#C83A3A", scheduled: "#5B6B82",
};

export const STEPPED = new Set(["flaps_pct", "gear", "spoilers_pct", "reverse"]);

export const ESSENTIALS = {
  ARR: ["ias_kt", "alt_ft", "vs_fpm", "gs_dev", "g_vert", "thrust_pct"],
  DEP: ["gs_kt", "alt_ft", "vs_fpm", "accel_g", "thrust_pct", "pitch"],
};

/** Merge a (possibly partial) telemetry payload into the cached copy. */
export function mergeLeg(prev, inc) {
  if (!prev || !inc.since) return inc;
  const s = inc.since;
  const cat = (a, b) => a.slice(0, s).concat(b);
  const ch = {};
  for (const k of Object.keys(inc.ch)) ch[k] = cat(prev.ch[k] || [], inc.ch[k]);
  return {
    ...inc, since: 0,
    t: cat(prev.t, inc.t), lat: cat(prev.lat, inc.lat), lng: cat(prev.lng, inc.lng),
    phase: cat(prev.phase, inc.phase), ch,
  };
}

/**
 * x values for each sample of one leg under an alignment mode.
 * Returns { x: number[], idx: number[] } (the samples that take part, with
 * strictly increasing x), or null if the leg cannot be aligned that way.
 */
export function alignLeg(d, direction, mode, eventKey) {
  if (!d) return null;
  const n = d.t.length;
  if (mode === "time") return { x: d.t.slice(), idx: [...Array(n).keys()] };
  if (mode === "event") {
    const ev = (d.events || []).find((e) => e.name === eventKey);
    if (!ev) return null;
    return { x: d.t.map((t) => t - ev.t), idx: [...Array(n).keys()] };
  }
  // runway distance
  const ok = new Set(RUNWAY_PHASES[direction]);
  const xs = d.ch.x_rwy_m;
  const x = [], idx = [];
  let last = -Infinity;
  for (let i = 0; i < n; i++) {
    if (!ok.has(d.phases[d.phase[i]])) continue;
    const v = xs[i];
    if (v == null || v <= last) continue;
    last = v; x.push(v); idx.push(i);
  }
  return x.length > 3 ? { x, idx } : null;
}

/** Build uPlot data [xs, y1, y2, ...] for one channel across selected legs. */
export function buildChannelData(flights, channel, extra) {
  const set = new Set();
  for (const f of flights) if (f.align) for (const x of f.align.x) set.add(x);
  if (extra) for (const x of extra.x) set.add(x);
  const xs = Array.from(set).sort((a, b) => a - b);
  const pos = new Map(xs.map((x, i) => [x, i]));
  const cols = flights.map((f) => {
    const col = new Array(xs.length).fill(null);
    if (f.align) {
      const y = f.detail.ch[channel];
      if (y) f.align.idx.forEach((si, k) => { col[pos.get(f.align.x[k])] = y[si]; });
    }
    return col;
  });
  if (extra) {
    const col = new Array(xs.length).fill(null);
    extra.x.forEach((x, k) => { col[pos.get(x)] = extra.y[k]; });
    cols.push(col);
  }
  return [xs, ...cols];
}

/** Index of the entry in sorted xs closest to x. */
export function nearest(xs, x) {
  let lo = 0, hi = xs.length - 1;
  if (hi < 0) return -1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] < x) lo = mid; else hi = mid;
  }
  return Math.abs(xs[lo] - x) <= Math.abs(xs[hi] - x) ? lo : hi;
}

export function fmt(v, nd = 1) {
  if (v == null || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: nd, minimumFractionDigits: 0 });
}

export function fmtDuration(s) {
  if (s == null) return "—";
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}

/** Simple hover bus so the track map follows the charts without re-rendering the page. */
export const hoverBus = {
  x: null,
  subs: new Set(),
  set(x) {
    if (x === this.x) return;
    this.x = x;
    this.subs.forEach((f) => f());
  },
  subscribe(f) { this.subs.add(f); return () => this.subs.delete(f); },
  get() { return this.x; },
};

/** Slow-to-fast ramp for the speed-coloured track, readable on white:
 *  steel blue (taxi) -> royal blue -> violet -> chart magenta (fastest). */
export function ramp(t) {
  const stops = [[132, 170, 208], [58, 128, 200], [30, 86, 168], [110, 56, 156], [194, 37, 124]];
  const x = Math.min(0.999, Math.max(0, t)) * (stops.length - 1);
  const i = Math.floor(x), f = x - i;
  const c = stops[i].map((v, k) => Math.round(v + (stops[i + 1][k] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export function toCsv(flights, channels) {
  const head = ["leg", "t_s", "phase", ...channels];
  const rows = [head.join(",")];
  for (const f of flights) {
    const d = f.detail;
    for (let i = 0; i < d.t.length; i++) {
      rows.push([f.id, d.t[i], d.phases[d.phase[i]], ...channels.map((c) => d.ch[c]?.[i] ?? "")].join(","));
    }
  }
  return rows.join("\n");
}

/** Phase bands (start/end/colour) for shading a chart behind one flight. */
export function bandsFor(detail) {
  if (!detail) return [];
  const out = [];
  let start = 0;
  for (let i = 1; i <= detail.phase.length; i++) {
    if (i === detail.phase.length || detail.phase[i] !== detail.phase[start]) {
      const name = detail.phases[detail.phase[start]];
      out.push({ x0: detail.t[start], x1: detail.t[Math.min(i, detail.t.length - 1)], label: PHASE_LABEL[name] || name, color: PHASE_COLOR[name] || "#64748b" });
      start = i;
    }
  }
  return out;
}

