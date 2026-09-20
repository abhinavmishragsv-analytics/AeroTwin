/**
 * WeatherFX
 * =========
 * A small, self-contained canvas-based atmosphere renderer: fog/haze, rain
 * with lightning, and wind streaks, plus a ground-stop alert vignette. Each
 * disruption the ATC console can trigger should be *visible* on the map
 * itself, not just a line of text in the weather panel.
 *
 * Deliberately a plain 2D canvas layered on top of the DeckGL/MapLibre
 * canvas, not a deck.gl layer: these are screen-space effects - fog doesn't
 * get thinner because the camera zoomed in, and rain falls past the camera,
 * not through the terrain. Spatial disruptions that DO have a real position
 * (a closed runway, a closed taxiway, the specific emergency aircraft) are
 * drawn as actual deck.gl layers instead - see lib/disruptionLayers.js.
 *
 * Every effect's strength is a *target* the renderer eases toward every
 * frame rather than a hard on/off switch, so triggering or clearing a
 * disruption fades the effect in/out instead of snapping - real weather
 * doesn't arrive or lift instantly, and a hard cut reads as a bug.
 *
 * Multiple disruptions active at once (fog + crosswind + a thunderstorm, the
 * exact combination the multi-disruption fix was built for) simply run all
 * three effects simultaneously at their own independent strengths - there is
 * no "current condition" switch here, only a set of independent targets.
 */

const TAU = Math.PI * 2;
const DEG2RAD = Math.PI / 180;

// Deterministic per-particle pseudo-random (mulberry32) so a given particle
// index always gets the same shape/phase - stable across re-seeds, no
// visible reshuffling when the particle counts don't change.
function prng(seed) {
  let t = seed >>> 0;
  return function next() {
    t = (t + 0x6d2b79f5) | 0;
    let r = Math.imul(t ^ (t >>> 15), t | 1);
    r ^= r + Math.imul(r ^ (r >>> 7), r | 61);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

const RAIN_COUNT = 260;
const WIND_STREAK_COUNT = 46;
const FOG_BLOB_COUNT = 5;

export class WeatherFXRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.width = 0;
    this.height = 0;

    // Eased (drawn) vs. target (last value the app told us) - see the file
    // doc comment above for why these are separate.
    this.state = { fog: 0, storm: 0, wind: 0, groundStop: 0 };
    this.target = { fog: 0, storm: 0, wind: 0, groundStop: 0 };
    this.windDirDeg = 0;
    this.windKt = 0;
    this.windColor = [205, 232, 255];
    this.mapBearing = 0;

    this.lightningFlash = 0;
    this.lightningBolt = null; // {x0,y0,points,ttl}
    this.lightningCooldownMs = 3500 + Math.random() * 3000;

    this._resizeHandler = () => this._resize();
    this._resize();
    window.addEventListener("resize", this._resizeHandler);

    this._seedFog();
    this._seedRain();
    this._seedWind();

    this._destroyed = false;
    this._lastT = performance.now();
    this._raf = requestAnimationFrame(this._tick);
  }

  destroy() {
    this._destroyed = true;
    cancelAnimationFrame(this._raf);
    window.removeEventListener("resize", this._resizeHandler);
  }

  /** fog/storm/wind/groundStop are each 0..1 targets; windDirDeg/windKt drive streak direction+speed. */
  setTargets({ fog = 0, storm = 0, wind = 0, groundStop = 0, windDirDeg = 0, windKt = 0, windColor }) {
    this.target.fog = fog;
    this.target.storm = storm;
    this.target.wind = wind;
    this.target.groundStop = groundStop;
    this.windDirDeg = windDirDeg;
    this.windKt = windKt;
    if (windColor) this.windColor = windColor;
  }

  setBearing(bearing) {
    this.mapBearing = bearing || 0;
  }

  _resize() {
    const parent = this.canvas.parentElement;
    const w = parent ? parent.clientWidth : window.innerWidth;
    const h = parent ? parent.clientHeight : window.innerHeight;
    this.width = w;
    this.height = h;
    this.canvas.width = Math.round(w * this.dpr);
    this.canvas.height = Math.round(h * this.dpr);
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this._diag = Math.hypot(w, h);
  }

  _seedFog() {
    const rnd = prng(1);
    this.fogBlobs = Array.from({ length: FOG_BLOB_COUNT }, () => ({
      x: rnd() * 1.4 - 0.2,
      y: 0.1 + rnd() * 0.55,
      r: 0.35 + rnd() * 0.35,
      speed: 0.004 + rnd() * 0.006,
      phase: rnd() * TAU,
    }));
  }

  _seedRain() {
    const rnd = prng(2);
    this.raindrops = Array.from({ length: RAIN_COUNT }, () => ({
      x: rnd(),
      y: rnd(),
      len: 14 + rnd() * 22,
      speed: 900 + rnd() * 500,
      alpha: 0.18 + rnd() * 0.28,
    }));
  }

  _seedWind() {
    const rnd = prng(3);
    this.windStreaks = Array.from({ length: WIND_STREAK_COUNT }, () => ({
      along: rnd(), // 0..1 progress along the travel axis, wraps
      cross: rnd() * 2 - 1, // -1..1 across the travel axis
      len: 60 + rnd() * 90,
      phase: rnd() * TAU,
      phaseSpeed: 2.4 + rnd() * 1.6,
      amp: 5 + rnd() * 7,
      speedMul: 0.7 + rnd() * 0.6,
      alpha: 0.35 + rnd() * 0.35,
    }));
  }

  _tick = (now) => {
    if (this._destroyed) return;
    const dt = Math.min(0.05, (now - this._lastT) / 1000);
    this._lastT = now;

    // Ease every effect's drawn strength toward its target. Fog eases the
    // slowest (real fog banks roll in/out over tens of seconds); wind and
    // rain ease fastest since gusts and downpour onset are quicker.
    const ease = (key, rate) => {
      this.state[key] += (this.target[key] - this.state[key]) * Math.min(1, dt * rate);
    };
    ease("fog", 0.35);
    ease("storm", 0.9);
    ease("wind", 1.1);
    ease("groundStop", 1.4);

    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);

    if (this.state.wind > 0.01) this._drawWind(ctx, dt);
    if (this.state.storm > 0.01) this._drawRain(ctx, dt);
    if (this.state.fog > 0.01) this._drawFog(ctx, dt);
    if (this.state.storm > 0.01) this._drawLightning(ctx, dt);
    if (this.state.groundStop > 0.01) this._drawGroundStop(ctx);

    this._raf = requestAnimationFrame(this._tick);
  };

  // --- Wind: squiggly streaks flowing across the screen in the compass
  // direction of the current wind, corrected for the map's own rotation so
  // the streaks point the true way regardless of how the camera is turned. -
  _drawWind(ctx, dt) {
    const screenDeg = this.windDirDeg - this.mapBearing;
    const rad = screenDeg * DEG2RAD;
    // Screen space: 0deg (north) travels "up" the screen, i.e. -y.
    const dir = { x: Math.sin(rad), y: -Math.cos(rad) };
    const perp = { x: -dir.y, y: dir.x };
    const speed = (40 + this.windKt * 5) * this.state.wind;
    const alphaScale = this.state.wind;
    const [cr, cg, cb] = this.windColor;

    ctx.lineCap = "round";
    ctx.lineWidth = 1.6;
    for (const s of this.windStreaks) {
      s.along = (s.along + (speed * s.speedMul * dt) / this._diag) % 1.15;
      s.phase += s.phaseSpeed * dt;
      // Fade in/out at the spawn and despawn edges of its travel so streaks
      // don't visibly pop into existence mid-screen.
      const edgeFade = Math.min(1, s.along / 0.08, (1.15 - s.along) / 0.15);
      const alpha = Math.max(0, edgeFade) * s.alpha * alphaScale;
      if (alpha <= 0.01) continue;

      // Spawn/travel line runs the full diagonal so it covers the screen
      // from any wind angle; cross-position spreads streaks across its width.
      const cx = this.width / 2 + perp.x * s.cross * this._diag * 0.65 - dir.x * this._diag * 0.575;
      const cy = this.height / 2 + perp.y * s.cross * this._diag * 0.65 - dir.y * this._diag * 0.575;
      const baseX = cx + dir.x * s.along * this._diag * 1.15;
      const baseY = cy + dir.y * s.along * this._diag * 1.15;

      ctx.strokeStyle = `rgba(${cr},${cg},${cb},${alpha.toFixed(3)})`;
      ctx.beginPath();
      const N = 5;
      for (let i = 0; i <= N; i++) {
        const t = i / N;
        const wave = Math.sin(t * TAU * 1.4 + s.phase) * s.amp;
        const px = baseX + dir.x * t * s.len + perp.x * wave;
        const py = baseY + dir.y * t * s.len + perp.y * wave;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();
    }
  }

  // --- Rain: fast diagonal streaks, slanted slightly by whatever wind is
  // currently blowing, looping from the top once they fall past the bottom. -
  _drawRain(ctx, dt) {
    const alphaScale = this.state.storm;
    const slant = Math.max(-0.5, Math.min(0.5, (this.windKt || 15) / 60)) *
      Math.sign(Math.sin((this.windDirDeg - this.mapBearing) * DEG2RAD) || 1);
    ctx.lineCap = "round";
    ctx.strokeStyle = `rgba(200,215,235,${(0.5 * alphaScale).toFixed(3)})`;
    ctx.lineWidth = 1.1;
    ctx.beginPath();
    for (const d of this.raindrops) {
      const dyFrac = (d.speed * dt) / this.height;
      d.y += dyFrac;
      if (d.y > 1.05) {
        d.y -= 1.15;
        d.x = Math.random();
      }
      const x = d.x * this.width;
      const y = d.y * this.height;
      ctx.moveTo(x, y);
      ctx.lineTo(x + slant * d.len, y + d.len);
    }
    ctx.stroke();

    // A soft cool-grey wash under the rain sells "storm light" even before
    // any lightning fires.
    ctx.fillStyle = `rgba(30,36,48,${(0.16 * alphaScale).toFixed(3)})`;
    ctx.fillRect(0, 0, this.width, this.height);
  }

  // --- Lightning: an occasional bright flash plus a jagged bolt, timed by
  // its own cooldown so it doesn't fire every frame while a storm is active. -
  _drawLightning(ctx, dt) {
    this.lightningCooldownMs -= dt * 1000 * (0.4 + this.state.storm);
    if (this.lightningCooldownMs <= 0 && !this.lightningBolt) {
      this.lightningBolt = this._makeBolt();
      this.lightningFlash = 1;
      this.lightningCooldownMs = 3500 + Math.random() * 5500;
    }

    if (this.lightningFlash > 0.001) {
      const flashAlpha = this.lightningFlash * 0.5 * this.state.storm;
      ctx.fillStyle = `rgba(225,235,255,${flashAlpha.toFixed(3)})`;
      ctx.fillRect(0, 0, this.width, this.height);
      this.lightningFlash *= 0.82;
      if (this.lightningFlash < 0.02) this.lightningFlash = 0;
    }

    if (this.lightningBolt) {
      const b = this.lightningBolt;
      b.ttl -= dt * 1000;
      if (b.ttl > 0) {
        ctx.strokeStyle = `rgba(235,242,255,${(0.85 * this.state.storm * Math.min(1, b.ttl / 90)).toFixed(3)})`;
        ctx.lineWidth = 2;
        ctx.beginPath();
        b.points.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
        ctx.stroke();
      } else {
        this.lightningBolt = null;
      }
    }
  }

  _makeBolt() {
    const x0 = this.width * (0.15 + Math.random() * 0.7);
    const yEnd = this.height * (0.45 + Math.random() * 0.4);
    const points = [[x0, 0]];
    let x = x0;
    let y = 0;
    while (y < yEnd) {
      y += 18 + Math.random() * 26;
      x += (Math.random() - 0.5) * 34;
      points.push([x, y]);
    }
    return { points, ttl: 110 };
  }

  // --- Fog: soft drifting radial blobs plus a top-heavy haze wash - hazier
  // toward the horizon than directly underneath the camera, which is how
  // real fog reads from an elevated angle. --------------------------------
  _drawFog(ctx, dt) {
    const a = this.state.fog;
    for (const b of this.fogBlobs) {
      b.x += b.speed * dt;
      if (b.x - b.r > 1.3) b.x = -0.3 - b.r;
      const cx = b.x * this.width;
      const cy = (b.y + Math.sin(b.phase + performance.now() * 0.00015) * 0.02) * this.height;
      const r = b.r * this._diag;
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
      g.addColorStop(0, `rgba(235,238,240,${(0.5 * a).toFixed(3)})`);
      g.addColorStop(1, "rgba(235,238,240,0)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, TAU);
      ctx.fill();
    }

    const wash = ctx.createLinearGradient(0, 0, 0, this.height);
    wash.addColorStop(0, `rgba(225,230,232,${(0.62 * a).toFixed(3)})`);
    wash.addColorStop(1, `rgba(225,230,232,${(0.22 * a).toFixed(3)})`);
    ctx.fillStyle = wash;
    ctx.fillRect(0, 0, this.width, this.height);
  }

  // --- Ground stop: a slow-pulsing red edge vignette - deliberately kept to
  // the border so it reads as an ambient alert without obscuring the field. -
  _drawGroundStop(ctx) {
    const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 900);
    const a = this.state.groundStop * (0.22 + 0.16 * pulse);
    const g = ctx.createRadialGradient(
      this.width / 2, this.height / 2, Math.min(this.width, this.height) * 0.42,
      this.width / 2, this.height / 2, Math.max(this.width, this.height) * 0.72
    );
    g.addColorStop(0, "rgba(220,40,40,0)");
    g.addColorStop(1, `rgba(220,40,40,${a.toFixed(3)})`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, this.width, this.height);
  }
}

// Distinguishes a genuine crosswind alert from a runway-direction wind shift
// with a different streak color, even though both drive the same underlying
// "wind" effect above.
const HIGH_WIND_COLOR = [205, 232, 255]; // pale blue-white
const WIND_SHIFT_COLOR = [255, 205, 120]; // amber

/**
 * Turns the twin's combined weather string + numbers into the 0..1 targets
 * WeatherFXRenderer wants. Because `twin.weather.condition` is already the
 * result of combining every simultaneously-active effect (see
 * core/twin_sim.py's `_recompute_weather` - the fix for stacking fog +
 * crosswind + a thunderstorm at once), reading it here is all that's needed
 * for this to automatically show every active disruption together, with no
 * separate bookkeeping of "which buttons are currently pressed".
 */
export function weatherFxTargets(weather, groundStop) {
  const condition = weather?.condition || "";
  const visibility = weather?.visibility_m ?? 8000;
  // Visibility below ~2000m starts to visibly haze the field; the published
  // CAT I fog minimum (350m) reads as fully socked in.
  const hasFog = condition.includes("FOG") || condition.includes("MIST");
  const fog = hasFog ? Math.max(0, Math.min(1, 1 - (visibility - 300) / 1700)) : 0;
  const storm = condition.includes("THUNDERSTORM") ? 1 : 0;
  const highWind = condition.includes("HIGH_WIND");
  const windShift = !highWind && condition.includes("WIND_SHIFT");
  const wind = highWind || windShift ? 1 : 0;

  return {
    fog,
    storm,
    wind,
    groundStop: groundStop ? 1 : 0,
    windDirDeg: weather?.wind_dir_deg || 0,
    windKt: weather?.wind_kt || 0,
    windColor: windShift ? WIND_SHIFT_COLOR : HIGH_WIND_COLOR,
  };
}
