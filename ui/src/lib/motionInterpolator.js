/**
 * Motion Interpolator
 * ====================
 * High-Performance Client-Side Entity Interpolation Engine (60 FPS)
 *
 * Why aircraft looked choppy & hitched, and how this fixes it:
 * -------------------------------------------------------------
 * 1. Network updates arrive at STREAM_HZ (~15 Hz, ~66.7ms between frames).
 *    Previous interpolator sampled at `now = performance.now()`, which was
 *    ALWAYS ahead of the newest packet in the history buffer. This forced
 *    it into constant extrapolation (`t > 1`). For a cubic spline, extrapolating
 *    past t=1 causes the curve to rapidly bend/reverse, and when the next real
 *    packet arrived 66ms later, the position violently snapped forward.
 *
 * 2. True Entity Interpolation:
 *    We introduce an interpolation delay:
 *        renderTime = atMs - INTERPOLATION_DELAY_MS
 *    With INTERPOLATION_DELAY_MS = 100ms (~1.5 packet intervals), renderTime
 *    consistently falls BETWEEN two snapshots A and B that have ALREADY arrived:
 *        A.t <= renderTime <= B.t
 *    Therefore, normalized parameter u = (renderTime - A.t) / (B.t - A.t)
 *    is strictly bounded in [0.0, 1.0].
 *
 * 3. Time-Aware Cubic Hermite Spline:
 *    Using central-difference velocity tangents scaled by the actual segment
 *    time delta, the cubic Hermite curve guarantees C1 continuity (continuous
 *    first derivative / velocity) across segment transitions. It naturally
 *    produces linear motion along straight taxiways and smooth curved arcs
 *    through turns, with ZERO cubic divergence.
 *
 * 4. Shortest-Arc Slerp for Heading:
 *    Headings are interpolated using spherical shortest-arc lerp in [0, 360).
 *
 * 5. Stationary Locking & Dead Reckoning:
 *    - Aircraft with near-zero displacement (< 0.05m) are locked to their exact
 *      coordinates to prevent floating-point drift while parked or holding.
 *    - If network packets are delayed and the buffer runs dry, we extrapolate
 *      linearly along the current velocity vector (capped at 250ms), rather
 *      than diverging with a cubic polynomial.
 *
 * 6. Output Object Reuse:
 *    sample() runs every animation frame (up to 60/s) for every tracked
 *    aircraft. Before this, every single call spread a brand-new object per
 *    aircraft (`{...raw, lat, lng, ...}`) even for aircraft sitting still on
 *    a stand - at a busy airport that's dozens of allocations a second doing
 *    nothing but generating garbage-collector work, and it also meant deck.gl
 *    saw a "new" aircraft list every frame regardless of whether anything
 *    had actually moved, forcing it to redo more attribute/buffer work than
 *    it needed to. `_emit()` below now caches the last output per aircraft
 *    id and returns that exact same reference when every value that would
 *    go into a new object (position, orientation, speed, and the underlying
 *    `raw` telemetry reference) is unchanged from last call - which for a
 *    parked or holding aircraft is every call until it actually moves again.
 *    Moving aircraft are unaffected: their lat/lng change every tick by
 *    construction, so the cache check fails and a fresh object is produced,
 *    exactly as before.
 */

const HISTORY_LEN = 8;
const INTERPOLATION_DELAY_MS = 100;
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

export class MotionInterpolator {
  constructor() {
    this.histories = new Map(); // id -> [{t, lat, lng, altitude, heading, pitch, roll, raw}]
    // id -> the last object sample() produced for it, plus the exact inputs
    // that produced it - see section 6 of the file doc comment above.
    this.lastSampled = new Map();
  }

  reset() {
    this.histories.clear();
    this.lastSampled.clear();
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
      if (last && last.t === atMs) continue;

      h.push({
        t: atMs,
        lat: f.lat,
        lng: f.lng,
        altitude: f.altitude || 0,
        heading: f.heading || 0,
        pitch: f.pitch || 0,
        roll: f.roll || 0,
        speed: f.speed || 0,
        raw: f,
      });

      if (h.length > HISTORY_LEN) {
        h.shift();
      }
    }

    for (const id of this.histories.keys()) {
      if (!seen.has(id)) {
        this.histories.delete(id);
        this.lastSampled.delete(id);
      }
    }
  }

  /**
   * Return the cached output object for `id` if every value that would go
   * into a freshly-spread object is identical to last call, otherwise build
   * and cache a new one. `raw` is compared by reference (a new one only
   * ever arrives via ingest(), at STREAM_HZ, not every rAF tick), the rest
   * by value - IEEE-754 arithmetic is deterministic, so the same inputs to
   * the interpolation math above always produce bit-identical outputs and
   * this can never falsely reuse a stale frame.
   */
  _emit(id, raw, lat, lng, altitude, heading, pitch, roll, speed) {
    const cached = this.lastSampled.get(id);
    if (
      cached &&
      cached.raw === raw &&
      cached.lat === lat &&
      cached.lng === lng &&
      cached.altitude === altitude &&
      cached.heading === heading &&
      cached.pitch === pitch &&
      cached.roll === roll &&
      cached.speed === speed
    ) {
      return cached.output;
    }
    const output = { ...raw, lat, lng, altitude, heading, pitch, roll, speed };
    this.lastSampled.set(id, { raw, lat, lng, altitude, heading, pitch, roll, speed, output });
    return output;
  }

  /** Sample every tracked aircraft's smoothed state at wall-clock time `atMs`. */
  sample(atMs) {
    const renderTime = atMs - INTERPOLATION_DELAY_MS;
    const out = [];

    for (const [id, h] of this.histories.entries()) {
      if (h.length === 0) continue;

      // Single snapshot: return as-is
      if (h.length === 1) {
        const s = h[0];
        out.push(this._emit(id, s.raw, s.lat, s.lng, s.altitude, s.heading, s.pitch, s.roll, s.speed));
        continue;
      }

      const first = h[0];
      const last = h[h.length - 1];

      // Case A: Render time is earlier than the earliest buffered packet
      if (renderTime <= first.t) {
        out.push(this._emit(
          id, first.raw, first.lat, first.lng, first.altitude, first.heading, first.pitch, first.roll, first.speed
        ));
        continue;
      }

      // Case B: Network lag / packet delay - buffer underrun (renderTime > last.t)
      if (renderTime >= last.t) {
        const prev = h[h.length - 2];
        const dt = Math.min(MAX_EXTRAPOLATION_MS, renderTime - last.t);
        const span = Math.max(1, last.t - prev.t);
        const rate = dt / span;

        // Linear dead-reckoning along the velocity vector
        const lat = last.lat + (last.lat - prev.lat) * rate;
        const lng = last.lng + (last.lng - prev.lng) * rate;
        const altitude = Math.max(0, last.altitude + (last.altitude - prev.altitude) * rate);

        out.push(this._emit(id, last.raw, lat, lng, altitude, last.heading, last.pitch, last.roll, last.speed));
        continue;
      }

      // Case C: Standard playback - renderTime sits between h[i] and h[i+1]
      let i = 0;
      for (let k = 0; k < h.length - 1; k++) {
        if (h[k].t <= renderTime && renderTime <= h[k + 1].t) {
          i = k;
          break;
        }
      }

      const a = h[i];
      const b = h[i + 1];
      const span = Math.max(1, b.t - a.t);
      const u = Math.max(0.0, Math.min(1.0, (renderTime - a.t) / span));

      // Check if aircraft is stationary (parked or holding)
      const dlat = b.lat - a.lat;
      const dlng = b.lng - a.lng;
      const distSq = dlat * dlat + dlng * dlng;
      if (distSq < 1e-10) {
        out.push(this._emit(id, b.raw, a.lat, a.lng, a.altitude, a.heading, a.pitch, a.roll, 0));
        continue;
      }

      // 4-point window for Hermite cubic tangents: p0, a, b, p3
      const p0 = h[Math.max(0, i - 1)];
      const p3 = h[Math.min(h.length - 1, i + 2)];

      // Central difference velocity at A and B, scaled by span
      const spanA = Math.max(1, b.t - p0.t);
      const scaleA = span / spanA;
      const mAlat = (b.lat - p0.lat) * scaleA;
      const mAlng = (b.lng - p0.lng) * scaleA;
      const mAalt = (b.altitude - p0.altitude) * scaleA;

      const spanB = Math.max(1, p3.t - a.t);
      const scaleB = span / spanB;
      const mBlat = (p3.lat - a.lat) * scaleB;
      const mBlng = (p3.lng - a.lng) * scaleB;
      const mBalt = (p3.altitude - a.altitude) * scaleB;

      // Hermite basis functions
      const u2 = u * u;
      const u3 = u2 * u;
      const h00 = 2 * u3 - 3 * u2 + 1;
      const h10 = u3 - 2 * u2 + u;
      const h01 = -2 * u3 + 3 * u2;
      const h11 = u3 - u2;

      const lat = h00 * a.lat + h10 * mAlat + h01 * b.lat + h11 * mBlat;
      const lng = h00 * a.lng + h10 * mAlng + h01 * b.lng + h11 * mBlng;
      const altitude = Math.max(0, h00 * a.altitude + h10 * mAalt + h01 * b.altitude + h11 * mBalt);

      const heading = lerpHeading(a.heading, b.heading, u);
      const pitch = lerp(a.pitch, b.pitch, u);
      const roll = lerp(a.roll, b.roll, u);
      const speed = Math.round(lerp(a.speed || 0, b.speed || 0, u));

      out.push(this._emit(id, b.raw, lat, lng, altitude, heading, pitch, roll, speed));
    }

    return out;
  }
}
