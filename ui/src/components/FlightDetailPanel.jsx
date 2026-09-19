/**
 * FlightDetailPanel - opens next to a selected aircraft and tracks it as it
 * moves. `screenPosition` is recomputed every animation frame in App.jsx
 * (same loop that drives the smoothed aircraft motion - see
 * ui/src/lib/motionInterpolator.js), by projecting the aircraft's current
 * lng/lat/altitude through the active deck.gl viewport, so the box stays
 * pinned to the airframe rather than to a fixed screen location.
 */
const STATUS_LABEL = {
  scheduled: "Scheduled", pushback: "Pushback", taxi_out: "Taxiing out",
  hold_short: "Holding short", lineup: "Lined up", takeoff_roll: "Takeoff roll",
  climb: "Climbing", inbound: "Inbound", approach: "On approach", holding: "In holding pattern",
  go_around: "Go-around", final: "On final", landing_rollout: "Landing rollout",
  runway_vacate: "Vacating runway", taxi_in: "Taxiing in", turnaround: "Turnaround",
  parked: "Parked", diverted: "Diverted",
};

export default function FlightDetailPanel({ flight, details, screenPosition, onClose }) {
  if (!flight || !details || !screenPosition) return null;
  const [x, y] = screenPosition;

  // Keep the box on-screen near the aircraft rather than letting it run off
  // the edge of the viewport.
  const left = Math.min(Math.max(x + 18, 8), window.innerWidth - 300);
  const top = Math.min(Math.max(y - 40, 8), window.innerHeight - 320);

  return (
    <div className="flight-detail-panel" style={{ left, top }} onClick={(e) => e.stopPropagation()}>
      <div className="fdp-header">
        <div>
          <div className="fdp-flight-number">{details.flightNumber}</div>
          <div className="fdp-airline">{details.airline}</div>
        </div>
        <button className="fdp-close" onClick={onClose} aria-label="Close">×</button>
      </div>

      <div className="fdp-route">
        <span>{details.origin}</span>
        <span className="fdp-route-arrow">→</span>
        <span>{details.destination}</span>
      </div>

      <div className="fdp-status-badge">{STATUS_LABEL[flight.status] || flight.status}</div>

      <div className="fdp-grid">
        <FdpRow label="Callsign" value={details.callsign} />
        <FdpRow label="Aircraft" value={details.aircraftType} />
        <FdpRow label="Registration" value={details.registration} />
        <FdpRow label="Gate / Stand" value={details.gate} />
        <FdpRow label="Passengers" value={`${details.passengers} / ${details.seats}`} />
        <FdpRow label="Load factor" value={`${Math.round(details.loadFactor * 100)}%`} />
        <FdpRow label="Squawk" value={details.squawk} />
        <FdpRow label="Speed" value={`${flight.speed ?? 0} kt`} />
        <FdpRow label="Altitude" value={`${Math.round(flight.altitude || 0)} m`} />
        <FdpRow label="Heading" value={`${Math.round(flight.heading || 0)}°`} />
        {flight.cleared_to && <FdpRow label="Cleared to" value={flight.cleared_to} />}
        {flight.hold_reason && <FdpRow label="Holding for" value={flight.hold_reason} />}
      </div>
    </div>
  );
}

function FdpRow({ label, value }) {
  return (
    <div className="fdp-row">
      <span className="fdp-row-label">{label}</span>
      <span className="fdp-row-value">{value}</span>
    </div>
  );
}
