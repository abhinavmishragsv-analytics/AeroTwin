/**
 * AtcConsole - the write side of the bi-directional twin. Each button posts
 * a disruption to POST /api/airports/{icao}/disrupt and the live simulation
 * reacts within a frame: aircraft hold short, arrivals go around, ground
 * traffic re-routes around a closed taxiway.
 */
const ACTIONS = [
  { type: "runway_closure", label: "Runway Closure", minutes: 15, icon: "🚧" },
  { type: "ground_stop", label: "Ground Stop", minutes: 10, icon: "🛑" },
  { type: "fog", label: "Fog / Below CAT I", minutes: 20, icon: "🌫️" },
  { type: "low_visibility", label: "Low Visibility", minutes: 15, icon: "🌁" },
  { type: "high_wind", label: "High Crosswind", minutes: 15, icon: "💨" },
  { type: "thunderstorm", label: "Thunderstorm", minutes: 10, icon: "⛈️" },
  { type: "taxiway_closure", label: "Close Taxiway A", minutes: 10, icon: "🚫", target: "A" },
  { type: "emergency_arrival", label: "Emergency Arrival", minutes: 0, icon: "🚨" },
];

export default function AtcConsole({ onDisrupt, disruptions }) {
  return (
    <div className="panel console">
      <div className="panel-title warn">⚠ ATC DISRUPTION CONSOLE</div>
      <div className="console-grid">
        {ACTIONS.map((a) => (
          <button
            key={a.type}
            className="console-btn"
            onClick={() => onDisrupt(a.type, a.minutes, a.target)}
          >
            {a.icon} {a.label} {a.minutes > 0 ? `${a.minutes}m` : ""}
          </button>
        ))}
        <button className="console-btn clear" onClick={() => onDisrupt("clear", 0)}>
          ✅ Clear All
        </button>
      </div>
      {disruptions?.length > 0 && (
        <div className="console-log">
          {disruptions.slice(0, 4).map((d, i) => (
            <div key={i} className="log-line">
              T+{d.time.toFixed(0)}s — {d.label}
            </div>
          ))}
        </div>
      )}
      <div className="console-note">Every action here mutates the live SimPy twin.</div>
    </div>
  );
}
