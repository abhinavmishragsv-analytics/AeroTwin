import { memo, useEffect, useRef, useState } from "react";
/**
 * HUD - top-left status card: airport identity, sim clock, runway state,
 * weather, queue depth. Pure display; all values come from the twin frame.
 *
 * The SEPARATION metric carries an (i) tooltip: core.atc.SeparationMonitor
 * now keeps a log of individual violation incidents (see its `log` field),
 * not just a running count, and this is where that log becomes visible.
 */
function HUD({ airportName, icao, connected, frame }) {
  const twin = frame?.twin;
  const rwy = twin?.runway;
  const separation = twin?.separation;
  const [showViolations, setShowViolations] = useState(false);
  const popoverRef = useRef(null);

  useEffect(() => {
    if (!showViolations) return undefined;
    const onDocClick = (e) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) {
        setShowViolations(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [showViolations]);

  const violationCount = separation
    ? separation.ground_violations + separation.airborne_violations
    : 0;

  return (
    <div className="panel hud">
      <div className="hud-title">
        <span className="brand">AEROTWIN</span>
        <span className="dot">•</span>
        <span className="icao">{icao}</span>
        <span className={`status-pill ${connected ? "online" : "offline"}`}>
          {connected ? "ONLINE" : "CONNECTING"}
        </span>
      </div>
      <div className="hud-sub">{airportName || "…"}</div>

      <div className="hud-grid">
        <Metric label="SIM TIME" value={frame ? `T+${frame.time.toFixed(1)}s` : "—"} />
        <Metric
          label={`RUNWAY ${rwy?.name || ""}`}
          value={rwy ? (rwy.closed ? "CLOSED" : `ACTIVE ${rwy.active_end}`) : "—"}
          tone={rwy?.closed ? "bad" : "good"}
        />
        <Metric
          label="WEATHER"
          value={twin?.weather?.condition || "—"}
          tone={twin?.weather?.condition === "CLEAR" ? "good" : "warn"}
        />
        <Metric label="QUEUE DEPTH" value={twin ? `${twin.queue_depth} aircraft` : "—"} />
        <Metric label="AIRBORNE" value={twin ? twin.airborne : "—"} />
        <div className="metric metric-separation">
          <div className="metric-label">
            SEPARATION
            {separation && (
              <button
                className="info-icon"
                onClick={() => setShowViolations((v) => !v)}
                aria-label="Show separation violation log"
              >
                i
              </button>
            )}
          </div>
          <div className={`metric-value ${violationCount > 0 ? "bad" : "good"}`}>
            {separation ? `${violationCount} violations` : "—"}
          </div>

          {showViolations && (
            <div className="violations-popover" ref={popoverRef}>
              <div className="violations-popover-title">Separation violations</div>
              <div className="violations-popover-list">
                {(!separation.log || separation.log.length === 0) && (
                  <div className="violations-empty">No incidents recorded</div>
                )}
                {(separation.log || []).map((v, i) => (
                  <div key={i} className="violation-row">
                    <div className="violation-row-top">
                      <span className={`violation-kind ${v.kind}`}>{v.kind.toUpperCase()}</span>
                      <span className="violation-time">{v.time != null ? `T+${v.time}s` : "—"}</span>
                    </div>
                    <div className="violation-pair">{v.a} ↔ {v.b}</div>
                    <div className="violation-distance">
                      {v.distance_m} m apart (min {v.min_required_m} m)
                      {v.vertical_m != null && ` · Δalt ${v.vertical_m} m`}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value, tone }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${tone || ""}`}>{value}</div>
    </div>
  );
}


// Memoised: these panels are fed a throttled frame (see App.jsx), so
// skipping re-render when their props are identical keeps DOM work off the
// hot path entirely.
export default memo(HUD);
