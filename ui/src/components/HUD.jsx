/**
 * HUD - top-left status card: airport identity, sim clock, runway state,
 * weather, queue depth. Pure display; all values come from the twin frame.
 */
export default function HUD({ airportName, icao, connected, frame }) {
  const twin = frame?.twin;
  const rwy = twin?.runway;
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
        <Metric
          label="SEPARATION"
          value={
            twin
              ? `${twin.separation.ground_violations + twin.separation.airborne_violations} violations`
              : "—"
          }
          tone={
            twin && twin.separation.ground_violations + twin.separation.airborne_violations > 0
              ? "bad"
              : "good"
          }
        />
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
