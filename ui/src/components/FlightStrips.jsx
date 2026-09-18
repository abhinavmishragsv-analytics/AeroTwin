/**
 * FlightStrips - the scrolling telemetry list: callsign, type, status,
 * current clearance, and why an aircraft is holding, if it is. This is the
 * one place in the UI where the taxi/runway clearance text produced by
 * core.routing.TaxiRoute.describe() and the ATC state machine become visible
 * in plain language, not just position.
 */
const STATUS_LABEL = {
  scheduled: "SCHEDULED", pushback: "PUSHBACK", taxi_out: "TAXI OUT",
  hold_short: "HOLD SHORT", lineup: "LINE UP", takeoff_roll: "TAKEOFF ROLL",
  climb: "CLIMB", inbound: "INBOUND", approach: "APPROACH", holding: "HOLDING",
  go_around: "GO-AROUND", final: "FINAL", landing_rollout: "ROLLOUT",
  runway_vacate: "VACATING", taxi_in: "TAXI IN", turnaround: "TURNAROUND",
  parked: "PARKED", diverted: "DIVERTED",
};

export default function FlightStrips({ flights }) {
  const active = (flights || [])
    .filter((f) => f.status !== "parked")
    .sort((a, b) => (a.status === "hold_short") - (b.status === "hold_short"));

  return (
    <div className="panel strips">
      <div className="panel-title">ACTIVE FLIGHT TELEMETRY</div>
      <div className="strips-list">
        {active.length === 0 && <div className="strips-empty">No active movements</div>}
        {active.map((f) => (
          <div key={f.id} className="strip">
            <div className="strip-row1">
              <span className="callsign">{f.id}</span>
              <span className="strip-badge">{STATUS_LABEL[f.status] || f.status}</span>
            </div>
            <div className="strip-row2">
              <span>{f.type}</span>
              <span>{f.speed} kt</span>
              <span>{Math.round(f.altitude || 0)} m</span>
              {typeof f.risk === "number" && (
                <span className={f.risk > 0.5 ? "risk bad" : "risk"}>Risk: {f.risk.toFixed(2)}</span>
              )}
            </div>
            {f.cleared_to && <div className="strip-clearance">→ {f.cleared_to}</div>}
            {f.hold_reason && <div className="strip-hold">⏸ {f.hold_reason}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
