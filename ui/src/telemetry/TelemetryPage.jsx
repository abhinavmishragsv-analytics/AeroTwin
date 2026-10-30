/**
 * TelemetryPage - flight-data analysis for the twin.
 *
 * Opened in its own tab from the map (see App.jsx). It attaches to the SAME
 * simulation as the map tab through the session id in the URL, lists every
 * recorded leg, and lets you overlay up to six legs of ONE direction.
 *
 * Arrivals and departures are separate worlds on purpose: an approach and a
 * take-off share no phases, no sensible x axis and almost no KPIs, so the page
 * never lets you mix them (there are two tabs, each with its own selection).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE, fetchAirports, fetchTelemetryLeg, fetchTelemetryLegs, fetchTelemetrySchema,
  sessionFromQuery, slugFromPath, telemetrySocketUrl,
} from "../lib/api";
import ChartPanel from "./ChartPanel";
import FlightPicker from "./FlightPicker";
import KpiTable from "./KpiTable";
import TrackMap from "./TrackMap";
import {
  ESSENTIALS, EVENT_OPTIONS, MAX_COMPARE, PALETTE, alignLeg, bandsFor, buildChannelData, fmt, fmtDuration, mergeLeg, toCsv,
} from "./lib";
import "./telemetry.css";

const GROUP_LABEL = {
  speed: "Speed", path: "Flight path", attitude: "Attitude", loads: "Loads", approach: "Approach",
  wind: "Wind", engines: "Engines", fuel: "Fuel & weight", config: "Configuration", brakes: "Brakes", risk: "Risk",
};
const GROUP_ORDER = ["speed", "path", "attitude", "loads", "approach", "wind", "engines", "fuel", "config", "brakes", "risk"];
const DIR_HIDDEN = { DEP: new Set(["gs_dev", "loc_dev"]) };

export default function TelemetryPage() {
  const identifier = slugFromPath() || "vabo";
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const session = sessionFromQuery();
  const initialLeg = params.get("leg");
  const initialDir = initialLeg?.endsWith(":DEP") ? "DEP" : "ARR";

  const [airportName, setAirportName] = useState("");
  const [schema, setSchema] = useState([]);
  const [legs, setLegs] = useState({});            // id -> summary
  const [simTime, setSimTime] = useState(0);
  const [error, setError] = useState(null);
  const [wsState, setWsState] = useState("connecting");
  const [direction, setDirection] = useState(initialDir);
  const [filter, setFilter] = useState(initialLeg ? "all" : "completed");
  const [selected, setSelected] = useState({ ARR: initialDir === "ARR" && initialLeg ? [initialLeg] : [], DEP: initialDir === "DEP" && initialLeg ? [initialLeg] : [] });
  const [cache, setCache] = useState({});          // id -> detail
  const [mode, setMode] = useState("event");
  const [eventKey, setEventKey] = useState({ ARR: "touchdown", DEP: "brake_release" });
  const [visible, setVisible] = useState({ ARR: ESSENTIALS.ARR, DEP: ESSENTIALS.DEP });
  const colorsRef = useRef({});
  const wsRef = useRef(null);
  const fetching = useRef(new Set());

  useEffect(() => { document.title = "AeroTwin · Telemetry"; }, []);

  // -- one-off loads ---------------------------------------------------------
  useEffect(() => {
    fetchTelemetrySchema().then((d) => setSchema(d.channels)).catch((e) => setError(String(e.message || e)));
    fetchAirports().then((d) => {
      const a = (d.airports || []).find((x) => x.slug === identifier || x.icao.toLowerCase() === identifier.toLowerCase());
      if (a) setAirportName(`${a.city} (${a.iata})`);
    }).catch(() => {});
    fetchTelemetryLegs(identifier, session, null, "all").then((d) => {
      setLegs(Object.fromEntries(d.legs.map((l) => [l.id, l])));
      setSimTime(d.time);
    }).catch((e) => setError(e.message === "session_not_found" ? "session_not_found" : String(e.message || e)));
  }, [identifier, session]);

  // -- live socket ----------------------------------------------------------
  useEffect(() => {
    let closed = false, timer = null;
    const connect = () => {
      const ws = new WebSocket(telemetrySocketUrl(identifier, session));
      wsRef.current = ws;
      ws.onopen = () => setWsState("live");
      ws.onclose = () => { setWsState("offline"); if (!closed) timer = setTimeout(connect, 1500); };
      ws.onmessage = (evt) => {
        const msg = JSON.parse(evt.data);
        if (msg.kind === "error") { setError(msg.error); return; }
        if (msg.kind === "legs" || msg.kind === "legs_delta") {
          setSimTime(msg.time);
          setLegs((prev) => {
            const next = msg.kind === "legs" ? {} : { ...prev };
            msg.legs.forEach((l) => { next[l.id] = l; });
            return next;
          });
        } else if (msg.kind === "leg") {
          setCache((prev) => ({ ...prev, [msg.data.id]: mergeLeg(prev[msg.data.id], msg.data) }));
        }
      };
    };
    connect();
    return () => { closed = true; clearTimeout(timer); wsRef.current?.close(); };
  }, [identifier, session]);

  // -- fetch details for selected legs; subscribe live ones -------------------
  const selIds = selected[direction];
  const allSel = useMemo(() => [...selected.ARR, ...selected.DEP], [selected]);
  useEffect(() => {
    allSel.forEach((id) => {
      const have = cache[id];
      const sum = legs[id];
      const stale = have && have.live && sum && !sum.live;
      if (sum && (!have || stale) && !fetching.current.has(id)) {
        fetching.current.add(id);
        fetchTelemetryLeg(identifier, session, id)
          .then((d) => setCache((p) => ({ ...p, [id]: d })))
          .catch(() => {})
          .finally(() => fetching.current.delete(id));
      }
    });
  }, [allSel, cache, legs, identifier, session]);

  const liveSelKey = allSel.filter((id) => legs[id]?.live).sort().join("|");
  useEffect(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ op: "subscribe", legs: liveSelKey ? liveSelKey.split("|") : [] }));
  }, [liveSelKey, wsState]);

  // -- colours: stable per leg for the life of the page -----------------------
  // Colours are handed out per direction, from the legs already selected
  // there, so the first leg you pick on either tab is always blue.
  const colorOf = (id, among = selIds) => {
    if (colorsRef.current[id]) return colorsRef.current[id];
    const used = new Set(among.map((x) => colorsRef.current[x]).filter(Boolean));
    colorsRef.current[id] = PALETTE.find((c) => !used.has(c)) || PALETTE[0];
    return colorsRef.current[id];
  };
  const toggle = useCallback((id) => {
    setSelected((s) => {
      const cur = s[direction];
      if (cur.includes(id)) { delete colorsRef.current[id]; return { ...s, [direction]: cur.filter((x) => x !== id) }; }
      if (cur.length >= MAX_COMPARE) return s;
      colorOf(id, cur);
      return { ...s, [direction]: [...cur, id] };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [direction]);
  const clear = () => setSelected((s) => { s[direction].forEach((id) => delete colorsRef.current[id]); return { ...s, [direction]: [] }; });
  const pickLatest = (n) => {
    const ids = Object.values(legs).filter((l) => l.direction === direction && !l.live && ["landed", "departed"].includes(l.outcome))
      .sort((a, b) => b.start_t - a.start_t).slice(0, n).map((l) => l.id);
    selIds.forEach((x) => delete colorsRef.current[x]);
    const placed = [];
    ids.forEach((x) => { colorOf(x, placed); placed.push(x); });
    setSelected((s) => ({ ...s, [direction]: ids }));
  };

  // -- derived data -------------------------------------------------------------
  const eKey = eventKey[direction];
  const flights = useMemo(() => selIds.filter((id) => cache[id]).map((id) => {
    const detail = cache[id];
    return { id, color: colorsRef.current[id] || PALETTE[0], detail, align: alignLeg(detail, direction, mode, eKey) };
  }), [selIds, cache, direction, mode, eKey]);

  const channels = useMemo(() => schema.filter((c) => !(DIR_HIDDEN[direction]?.has(c.name))), [schema, direction]);
  const byName = useMemo(() => Object.fromEntries(schema.map((c) => [c.name, c])), [schema]);
  const vis = visible[direction];
  const setVis = (list) => setVisible((v) => ({ ...v, [direction]: list }));
  const toggleGroup = (g) => {
    const names = channels.filter((c) => c.group === g).map((c) => c.name);
    const allOn = names.every((n) => vis.includes(n));
    setVis(allOn ? vis.filter((n) => !names.includes(n)) : [...vis, ...names.filter((n) => !vis.includes(n))]);
  };

  const xLabel = mode === "time" ? "seconds since the leg began"
    : mode === "event" ? `seconds relative to ${EVENT_OPTIONS[direction].find((e) => e.key === eKey)?.label.toLowerCase()}`
      : direction === "ARR" ? "metres along the runway from the threshold (negative = on approach)" : "metres along the runway from brake release";

  const models = useMemo(() => {
    if (!flights.length) return [];
    const single = flights.length === 1;
    const order = new Map(schema.map((c, i) => [c.name, i]));
    return vis.filter((n) => byName[n]).sort((a, b) => order.get(a) - order.get(b)).map((name) => {
      const meta = byName[name];
      const series = flights.map((f) => ({ id: f.id, label: f.detail.flight, short: single ? meta.label : f.detail.flight, color: f.color }));
      let extra = null;
      if (mode === "runway" && direction === "ARR" && name === "alt_ft") {
        const x = [], y = [];
        for (let v = -9000; v <= 0; v += 100) { x.push(v); y.push(-v * Math.tan((3 * Math.PI) / 180) * 3.28084); }
        extra = { x, y };
        series.push({ id: "gs3", label: "3° glideslope", short: "3° path", color: "#6B7A90", dashed: true });
      }
      const data = buildChannelData(flights, name, extra);
      const decor = { hlines: [], events: [], hbands: [] };
      if (name === "ias_kt" || name === "gs_kt") {
        flights.forEach((f) => {
          const r = f.detail.meta.refs;
          if (direction === "ARR") decor.hlines.push({ y: r.vapp, color: f.color, label: `Vapp ${f.detail.meta.type}` });
          else decor.hlines.push({ y: r.vr, color: f.color, label: `VR ${f.detail.meta.type}` });
        });
      }
      if (name === "vs_fpm" && direction === "ARR") decor.hlines.push({ y: -1000, color: "#B7791F", label: "stabilised-approach limit" });
      if (name === "gs_dev" || name === "loc_dev") decor.hbands.push({ y0: -1, y1: 1, color: "rgba(14,143,110,0.10)" });
      if (mode === "time") {
        const keep = direction === "ARR" ? ["go_around", "touchdown", "runway_clear"] : ["brake_release", "liftoff", "alt_1000"];
        flights.forEach((f) => (f.detail.events || []).filter((e) => keep.includes(e.name)).forEach((e) =>
          decor.events.push({ x: e.t, color: f.color, label: single || e.name === "touchdown" || e.name === "liftoff" ? e.label : null })));
        if (single) {
          decor.bands = bandsFor(flights[0].detail);
          decor.bandLabels = true;
        }
      } else if (mode === "event") {
        decor.zero = 0;
        if (single) {
          const ev = (flights[0].detail.events || []).find((e) => e.name === eKey);
          if (ev) {
            decor.bands = bandsFor(flights[0].detail).map((b) => ({ ...b, x0: b.x0 - ev.t, x1: b.x1 - ev.t }));
            decor.bandLabels = true;
          }
        }
      } else {
        decor.zero = 0;
      }
      return { name, meta, series, data, decor };
    });
  }, [flights, vis, byName, schema, mode, direction, eKey]);

  const notAligned = flights.filter((f) => !f.align);
  const anyLive = flights.some((f) => f.detail.live);
  const liveCount = Object.values(legs).filter((l) => l.live).length;
  const counts = useMemo(() => {
    const c = { ARR: 0, DEP: 0 };
    Object.values(legs).forEach((l) => { if (!l.live) c[l.direction] += 1; });
    return c;
  }, [legs]);

  const exportCsv = () => {
    const blob = new Blob([toCsv(flights, schema.map((c) => c.name))], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `aerotwin-${direction === "ARR" ? "arrivals" : "departures"}-${flights.map((f) => f.detail.flight).join("_")}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  // -- render -----------------------------------------------------------------
  if (error === "session_not_found") {
    return (
      <div className="tm-root tm-center">
        <div className="tm-card-msg">
          <h2>That simulation has ended</h2>
          <p>Telemetry is attached to a running twin. Reload the map tab (it starts a fresh simulation) and open Telemetry from there.</p>
          <a className="tm-btn" href={`/${identifier}`}>Open the map</a>
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="tm-root tm-center">
        <div className="tm-card-msg"><h2>Can't reach the twin</h2><p>{error}</p><p className="tm-dim">API: {API_BASE}</p></div>
      </div>
    );
  }

  return (
    <div className="tm-root">
      <header className="tm-header">
        <div className="tm-brand">
          <Mark />
          <span className="tm-logo">AeroTwin</span>
          <span className="tm-sep" aria-hidden="true">/</span>
          <h1 className="tm-title">Flight telemetry</h1>
          {airportName && <span className="tm-airport">{airportName}</span>}
        </div>
        <div className="tm-dirs" role="tablist">
          {[["ARR", "Arrivals", "↓"], ["DEP", "Departures", "↑"]].map(([d, label, arrow]) => (
            <button key={d} role="tab" aria-selected={direction === d} className={direction === d ? "on" : ""} onClick={() => setDirection(d)}>
              <span className="tm-arrow">{arrow}</span>{label}<small>{counts[d]}</small>
            </button>
          ))}
        </div>
        <div className="tm-head-right">
          <span className={`tm-conn ${wsState}`}><i />{wsState === "live" ? `sim T+${fmtDuration(simTime)} · ${liveCount} live` : wsState}</span>
          <button className="tm-btn ghost" onClick={() => window.close()} title="Close this tab and return to the map">Back to map</button>
        </div>
      </header>

      <div className="tm-body">
        <FlightPicker legs={Object.values(legs)} direction={direction} selected={selIds}
          colors={Object.fromEntries(selIds.map((id) => [id, colorsRef.current[id]]))}
          onToggle={toggle} onClear={clear} filter={filter} setFilter={setFilter} />

        <main className="tm-main">
          <div className="tm-toolbar">
            <div className="tm-group">
              <span className="tm-label">Align by</span>
              <div className="tm-seg">
                <button className={mode === "event" ? "on" : ""} onClick={() => setMode("event")}>Event</button>
                <button className={mode === "time" ? "on" : ""} onClick={() => setMode("time")}>Time</button>
                <button className={mode === "runway" ? "on" : ""} onClick={() => setMode("runway")}>Runway distance</button>
              </div>
              {mode === "event" && (
                <select className="tm-select" value={eKey} onChange={(e) => setEventKey((k) => ({ ...k, [direction]: e.target.value }))}>
                  {EVENT_OPTIONS[direction].map((e) => <option key={e.key} value={e.key}>{e.label}</option>)}
                </select>
              )}
            </div>
            <div className="tm-group tm-chips">
              {GROUP_ORDER.filter((g) => channels.some((c) => c.group === g)).map((g) => {
                const names = channels.filter((c) => c.group === g).map((c) => c.name);
                const n = names.filter((x) => vis.includes(x)).length;
                return (
                  <button key={g} className={`tm-chip ${n === names.length ? "on" : n ? "part" : ""}`} onClick={() => toggleGroup(g)}
                    title={`${n}/${names.length} channels shown`}>{GROUP_LABEL[g]}</button>
                );
              })}
              <button className="tm-chip reset" onClick={() => setVis(ESSENTIALS[direction])}>Essentials</button>
            </div>
            <div className="tm-group">
              {anyLive && <span className="tm-livebadge"><i />Live</span>}
              <button className="tm-btn ghost" disabled={!flights.length} onClick={exportCsv}>Export CSV</button>
            </div>
          </div>

          {flights.length === 0 && selIds.length > 0 ? (
            <div className="tm-pending">Waiting for <b>{selIds.join(", ")}</b> to start recording… it appears as soon as the aircraft begins moving.</div>
          ) : flights.length === 0 ? (
            <div className="tm-hero">
              <HeroProfile direction={direction} />
              <h2>{direction === "ARR" ? "Analyse arrivals" : "Analyse departures"}</h2>
              <p>
                {direction === "ARR"
                  ? "Approach profile, stabilised-approach gates, touchdown, rollout, braking and taxi-in."
                  : "Pushback, taxi-out, hold time, take-off roll, rotation, lift-off and initial climb."}
                {" "}Pick up to {MAX_COMPARE} flights on the left to overlay them. {direction === "ARR" ? "Departures" : "Arrivals"} are kept in their own tab, since the two can't be compared like for like.
              </p>
              <div className="tm-hero-actions">
                <button className="tm-btn" disabled={!counts[direction]} onClick={() => pickLatest(3)}>Compare the latest 3 completed</button>
                <button className="tm-btn ghost" disabled={!counts[direction]} onClick={() => pickLatest(1)}>Open the latest one</button>
              </div>
              {!counts[direction] && <p className="tm-dim">Nothing has {direction === "ARR" ? "landed" : "departed"} yet in this simulation. Give it a minute, or switch the list to “live”.</p>}
            </div>
          ) : (
            <>
              <div className="tm-cards">
                {flights.map((f) => <FlightCard key={f.id} f={f} direction={direction} />)}
              </div>
              {notAligned.length > 0 && (
                <div className="tm-note">
                  {notAligned.map((f) => f.detail.flight).join(", ")}: no {mode === "event" ? EVENT_OPTIONS[direction].find((e) => e.key === eKey)?.label.toLowerCase() : "runway segment"} on {notAligned.length > 1 ? "these legs" : "this leg"} (go-around, diversion, or not reached yet), so {notAligned.length > 1 ? "they are" : "it is"} left off the charts. Try aligning by Time.
                </div>
              )}
              <div className="tm-row">
                <div className="tm-panel"><div className="tm-panel-title">Key metrics</div><KpiTable flights={flights} /></div>
                <div className="tm-panel tm-panel-map"><TrackMap flights={flights} runwayOnly={false} /></div>
              </div>
              <div className="tm-charts">
                {models.map((m) => (
                  <ChartPanel key={m.name} channel={m.name} label={m.meta.label} unit={m.meta.unit} source={m.meta.source}
                    series={m.series} data={m.data} decor={m.decor} xLabel={xLabel}
                    onRemove={(n) => setVis(vis.filter((x) => x !== n))} />
                ))}
                {models.length === 0 && <div className="tm-empty">No charts selected. Turn on a channel group above.</div>}
              </div>
              <div className="tm-foot">
                <span><b className="tm-src tm-src-sim">sim</b> read from the simulation</span>
                <span><b className="tm-src tm-src-derived">derived</b> computed from the simulated motion</span>
                <span><b className="tm-src tm-src-model">model</b> plausible values the simulation doesn't compute itself (engines, fuel, weights, brakes, configuration)</span>
                <span className="tm-dim">Drag on a chart to zoom, double-click to reset.</span>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function FlightCard({ f, direction }) {
  const m = f.detail.meta;
  const conds = m.conditions || [];
  return (
    <div className="tm-fcard" style={{ "--tab": f.color }}>
      <div className="tm-fcard-top">
        <span className="tm-swatch" style={{ background: f.color, borderColor: f.color }} />
        <b>{f.detail.flight}</b>
        {f.detail.live ? <span className="tm-badge live">Live</span> : <span className="tm-badge ok">{f.detail.outcome}</span>}
      </div>
      <div className="tm-fcard-sub">{m.type_name} · {m.flight_number}</div>
      <div className="tm-fcard-grid">
        <span>{direction === "ARR" ? "From" : "To"}</span><b>{m.other_airport}</b>
        <span>Runway</span><b>{m.runway}</b>
        <span>Stand</span><b>{m.stand || "—"}</b>
        <span>Pax</span><b>{m.pax}/{m.seats}</b>
        <span>Reg.</span><b>{m.registration}</b>
        <span>Samples</span><b>{fmt(f.detail.n, 0)}</b>
      </div>
      {(conds.length > 0 || m.go_arounds > 0) && (
        <div className="tm-leg-tags">
          {m.go_arounds > 0 && <em className="warn">go-around ×{m.go_arounds}</em>}
          {conds.map((c) => <em key={c}>{c.toLowerCase()}</em>)}
        </div>
      )}
    </div>
  );
}

/** Small compass-rose mark: graticule circle, cardinal ticks, magenta needle. */
function Mark() {
  return (
    <svg className="tm-mark" viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
      <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M16 1.5v5M16 25.5v5M1.5 16h5M25.5 16h5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M16 6.5l3.2 9.5L16 25.5 12.8 16z" fill="var(--magenta)" />
      <circle cx="16" cy="16" r="1.7" fill="var(--paper)" />
    </svg>
  );
}

/**
 * A drawn altitude-against-distance profile: what the page measures, shown
 * before there is anything to plot. Arrivals: glideslope with the 1000 / 500 ft
 * gates, flare, touchdown and rollout. Departures: roll, rotate, lift-off and
 * climb. Purely illustrative - not to scale.
 */
function HeroProfile({ direction }) {
  const arr = direction === "ARR";
  return (
    <svg className="tm-profile" viewBox="0 0 560 150" role="img"
      aria-label={arr ? "Illustration of an approach, flare, touchdown and rollout" : "Illustration of a take-off roll, rotation and climb"}>
      <line x1="10" y1="118" x2="550" y2="118" className="pf-ground" />
      {arr ? (
        <>
          <rect x="296" y="115" width="236" height="6" rx="1" className="pf-runway" />
          <line x1="304" y1="118" x2="524" y2="118" className="pf-centre" />
          <path d="M20 20L290 111Q298 116 306 118" className="pf-path" />
          <path d="M306 118L470 118" className="pf-roll" markerEnd="url(#pf-arrow)" />
          <g className="pf-dot"><circle cx="150" cy="64" r="4" /><circle cx="222" cy="88" r="4" /><circle cx="306" cy="118" r="5" className="pf-key" /></g>
          <g className="pf-text">
            <text x="138" y="50" textAnchor="end">1000 ft gate</text>
            <text x="210" y="74" textAnchor="end">500 ft gate</text>
            <text x="296" y="106" textAnchor="end">Touchdown</text>
            <text x="410" y="138" textAnchor="middle">Rollout and braking</text>
            <text x="20" y="46">Approach on a 3° path</text>
          </g>
        </>
      ) : (
        <>
          <rect x="30" y="115" width="260" height="6" rx="1" className="pf-runway" />
          <line x1="38" y1="118" x2="282" y2="118" className="pf-centre" />
          <path d="M52 118L250 118" className="pf-roll" markerEnd="url(#pf-arrow)" />
          <path d="M272 118C330 112 392 82 540 26" className="pf-path" />
          <g className="pf-dot"><circle cx="52" cy="118" r="4" /><circle cx="250" cy="118" r="4" /><circle cx="272" cy="118" r="5" className="pf-key" /><circle cx="440" cy="58" r="4" /></g>
          <g className="pf-text">
            <text x="52" y="136">Brake release</text>
            <text x="244" y="106" textAnchor="end">Rotate</text>
            <text x="284" y="136">Lift-off</text>
            <text x="428" y="42" textAnchor="end">Climbing through 1000 ft</text>
            <text x="150" y="106" textAnchor="middle">Take-off roll</text>
          </g>
        </>
      )}
      <defs>
        <marker id="pf-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1.5L8.5 5 1 8.5z" className="pf-arrowhead" />
        </marker>
      </defs>
    </svg>
  );
}
