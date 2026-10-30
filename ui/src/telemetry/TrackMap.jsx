import { memo, useMemo, useState, useSyncExternalStore } from "react";
import { hoverBus, nearest, ramp } from "./lib";

/**
 * Ground track of every compared leg, drawn on a local metric grid with the
 * runway for scale. The dot on each track follows the chart crosshair
 * (hoverBus), so scrubbing a speed trace shows where on the airfield that
 * speed happened. With a single leg selected the track can be coloured by
 * ground speed.
 */
function TrackMap({ flights }) {
  const [byspeed, setByspeed] = useState(true);
  const [zoomAirfield, setZoomAirfield] = useState(true);
  const hx = useSyncExternalStore(hoverBus.subscribe.bind(hoverBus), () => hoverBus.get());

  const geo = useMemo(() => {
    const all = [];
    flights.forEach((f) => {
      const d = f.detail;
      for (let i = 0; i < d.lat.length; i++) all.push([d.lat[i], d.lng[i]]);
    });
    if (!all.length) return null;
    const m = flights[0]?.detail.meta;
    const ref = m?.runway_threshold || all[0];
    const lat0 = ref[0], lng0 = ref[1];
    const k = Math.cos((lat0 * Math.PI) / 180);
    const proj = (lat, lng) => [(lng - lng0) * 111320 * k, -(lat - lat0) * 111320];
    let P = all.map((p) => proj(p[0], p[1]));
    let runway = null;
    if (m?.runway_threshold) {
      const a = proj(m.runway_threshold[0], m.runway_threshold[1]);
      const h = (m.runway_heading * Math.PI) / 180;
      const L = m.runway_length_m;
      runway = [a, [a[0] + Math.sin(h) * L, a[1] - Math.cos(h) * L]];
    }
    if (zoomAirfield) {
      // Frame the aerodrome: everything within 3.2 km of the runway centre.
      const c = runway ? [(runway[0][0] + runway[1][0]) / 2, (runway[0][1] + runway[1][1]) / 2] : [0, 0];
      P = P.filter((p) => Math.hypot(p[0] - c[0], p[1] - c[1]) < 3200);
      if (P.length < 2) P = all.map((p) => proj(p[0], p[1]));
    }
    if (runway) P.push(runway[0], runway[1]);
    const xs = P.map((p) => p[0]), ys = P.map((p) => p[1]);
    const pad = 80;
    const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad;
    const y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
    return { proj, runway, box: [x0, y0, x1 - x0, y1 - y0] };
  }, [flights, zoomAirfield]);

  if (!geo) return <div className="tm-empty">No track yet</div>;
  const [bx, by, bw, bh] = geo.box;
  const single = flights.length === 1;
  const sw = Math.max(bw, bh) / 380;

  return (
    <div className="tm-map">
      <div className="tm-map-head">
        <span className="tm-map-title">Ground track</span>
        <span className="tm-map-opts">
          <label className="tm-check"><input type="checkbox" checked={zoomAirfield} onChange={(e) => setZoomAirfield(e.target.checked)} /> zoom to airfield</label>
          {single && (
            <label className="tm-check"><input type="checkbox" checked={byspeed} onChange={(e) => setByspeed(e.target.checked)} /> colour by speed</label>
          )}
        </span>
      </div>
      <svg viewBox={`${bx} ${by} ${bw} ${bh}`} preserveAspectRatio="xMidYMid slice" className="tm-map-svg" style={{ overflow: "hidden" }}>
        {geo.runway && (
          <line x1={geo.runway[0][0]} y1={geo.runway[0][1]} x2={geo.runway[1][0]} y2={geo.runway[1][1]}
            stroke="#C3CCD9" strokeWidth={sw * 14} strokeLinecap="butt" />
        )}
        {geo.runway && (
          <line x1={geo.runway[0][0]} y1={geo.runway[0][1]} x2={geo.runway[1][0]} y2={geo.runway[1][1]}
            stroke="#FFFFFF" strokeWidth={sw * 1.4} strokeDasharray={`${sw * 8} ${sw * 8}`} />
        )}
        {flights.map((f) => {
          const d = f.detail;
          const P = d.lat.map((la, i) => geo.proj(la, d.lng[i]));
          if (single && byspeed) {
            const vmax = Math.max(...d.ch.gs_kt.filter((v) => v != null), 1);
            const segs = [];
            for (let i = 1; i < P.length; i++) {
              segs.push(<line key={i} x1={P[i - 1][0]} y1={P[i - 1][1]} x2={P[i][0]} y2={P[i][1]}
                stroke={ramp((d.ch.gs_kt[i] ?? 0) / vmax)} strokeWidth={sw * 2.2} strokeLinecap="round" />);
            }
            return <g key={f.id}>{segs}</g>;
          }
          return <polyline key={f.id} fill="none" stroke={f.color} strokeWidth={sw * 2} strokeLinejoin="round"
            points={P.map((p) => p.join(",")).join(" ")} opacity="0.92" />;
        })}
        {hx != null && flights.map((f) => {
          if (!f.align) return null;
          const k = nearest(f.align.x, hx);
          if (k < 0) return null;
          const i = f.align.idx[k];
          const p = geo.proj(f.detail.lat[i], f.detail.lng[i]);
          return (
            <g key={f.id}>
              <circle cx={p[0]} cy={p[1]} r={sw * 9} fill={f.color} opacity="0.25" />
              <circle cx={p[0]} cy={p[1]} r={sw * 4.2} fill={f.color} stroke="#FFFFFF" strokeWidth={sw * 1.2} />
            </g>
          );
        })}
      </svg>
      {single && byspeed && (
        <div className="tm-ramp"><span>0 kt</span><i /><span>{Math.round(Math.max(...flights[0].detail.ch.gs_kt.filter((v) => v != null), 1))} kt</span></div>
      )}
    </div>
  );
}

export default memo(TrackMap);
