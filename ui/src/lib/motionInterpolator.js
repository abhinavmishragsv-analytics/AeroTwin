/**
 * Motion Interpolator
 * ====================
 * Why aircraft looked blocky, and why this isn't a server problem alone
 * -----------------------------------------------------------------------
 * The server smooths the taxiway path itself now (see core/geo.py's
 * smooth_path), but that only fixes the *shape* of the route. The other
 * half of the blockiness was about *time*: the twin broadcasts a position
 * 15 times a second (STREAM_HZ) and deck.gl's built-in `transitions` on
 * ScenegraphLayer only ever tweens LINEARLY between the two most recent
 * broadcast values. At a corner - or during a fast approach, where the
 * time-compressed sim can cover a lot of ground between two broadcasts -
 * a two-point linear tween is exactly what "snapping" looks like: the
 * nose direction jumps the instant a new frame arrives instead of easing
 * through the turn.
 *
 * This replaces that with real entity interpolation, the technique
 * networked games use to make remote players move smoothly despite a
 * low, uneven update rate: keep a short history of the last few broadcast
 * states per aircraft, and every animation frame (60 fps, decoupled from
 * the 15 Hz network tick) fit a Catmull-Rom spline through that history
 * and sample it at the current render time. The result moves through an
 * actual curve, not a straight line, and keeps moving smoothly between
 * network updates instead of freezing until the next one arrives.
 */

const HISTORY_LEN = 4;
// If the network stalls, keep extrapolating along the last known curve for
// a little while rather than freezing mid-turn - but only briefly; beyond
// this we'd rather hold position than guess wildly.
const MAX_EXTRAPOLATION_MS = 250;

function headingDelta(a, b) {
  return (((b - a + 180) % 360) + 360) % 360 - 180;
}

function lerpHeading(a, b, t) {
  return (a + headingDelta(a, b) * t + 360) % 360;
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

// Uniform Catmull-Rom through p1..p2 at t in [0, 1] (t may run slightly
// outside that range for brief extrapolation past the last sample - the
// same cubic just keeps extending along its current tangent, which reads
// as "still moving the way it was" rather than a hard stop).
function catmullRom(p0, p1, p2, p3, t) {
  const t2 = t * t;
  const t3 = t2 * t;
  return (
    0.5 *
    (2 * p1 +
      (-p0 + p2) * t +
      (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
      (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
  );
}

export class MotionInterpolator {
  constructor() {
    this.histories = new Map(); // id -> [{t, lat, lng, altitude, heading, pitch, roll, raw}]
  }

  reset() {
    this.histories.clear();
  }

  /** Record a broadcast frame's flights at wall-clock time `atMs`. */
  ingest(flights, atMs) {
    const seen = new Set();
    for (const f of flights || []) {
      seen.add(f.id);
      let h = this.histories.get(f.id);
      if (!h) {
        h = [];
        this.histories.set(f.id, h);
      }
      const last = h[h.length - 1];
      // A duplicate broadcast (same position/time) contributes nothing to
      // the curve and can make the spline degenerate - skip it.
      if (last && last.t === atMs) continue;
      h.push({
        t: atMs,
        lat: f.lat,
        lng: f.lng,
        altitude: f.altitude || 0,
        heading: f.heading || 0,
        pitch: f.pitch || 0,
        roll: f.roll || 0,
        raw: f,
      });
      if (h.length > HISTORY_LEN) h.shift();
    }
    for (const id of this.histories.keys()) {
      if (!seen.has(id)) this.histories.delete(id);
    }
  }

  /** Sample every tracked aircraft's smoothed state at wall-clock time `atMs`. */
  sample(atMs) {
    const out = [];
    for (const h of this.histories.values()) {
      if (h.length === 0) continue;
      if (h.length === 1) {
        const s = h[0];
        out.push({ ...s.raw, lat: s.lat, lng: s.lng, altitude: s.altitude,
                    heading: s.heading, pitch: s.pitch, roll: s.roll });
        continue;
      }

      let i = h.length - 2;
      for (let k = 0; k < h.length - 1; k++) {
        if (h[k].t <= atMs) i = k;
      }
      const a = h[i];
      const b = h[i + 1];
      const span = Math.max(1, b.t - a.t);
      let t = (atMs - a.t) / span;
      if (t > 1) {
        const overshootMs = (t - 1) * span;
        if (overshootMs > MAX_EXTRAPOLATION_MS) {
          t = 1 + MAX_EXTRAPOLATION_MS / span;
        }
      } else if (t < 0) {
        t = 0;
      }

      const p0 = h[Math.max(0, i - 1)];
      const p3 = h[Math.min(h.length - 1, i + 2)];

      const lat = catmullRom(p0.lat, a.lat, b.lat, p3.lat, t);
      const lng = catmullRom(p0.lng, a.lng, b.lng, p3.lng, t);
      const altitude = catmullRom(p0.altitude, a.altitude, b.altitude, p3.altitude, t);
      const pitch = lerp(a.pitch, b.pitch, Math.min(1.3, Math.max(0, t)));
      const roll = lerp(a.roll, b.roll, Math.min(1.3, Math.max(0, t)));
      const heading = lerpHeading(a.heading, b.heading, Math.min(1.3, Math.max(0, t)));

      out.push({ ...b.raw, lat, lng, altitude, heading, pitch, roll });
    }
    return out;
  }
}
