import { memo, useState } from "react";
import CollapseToggle from "./CollapseToggle";
import {
  IconCheckCircle, IconCone, IconFog, IconHaze, IconNoEntry,
  IconOctagonStop, IconSiren, IconStorm, IconWarningTriangle, IconWind,
} from "./icons";
/**
 * AtcConsole - the write side of the bi-directional twin. Each button posts
 * a disruption to POST /api/airports/{icao}/disrupt and the live simulation
 * reacts within a frame: aircraft hold short, arrivals go around, ground
 * traffic re-routes around a closed taxiway.
 */
const ACTIONS = [
  { type: "runway_closure", label: "Runway Closure", minutes: 15, Icon: IconCone },
  { type: "ground_stop", label: "Ground Stop", minutes: 10, Icon: IconOctagonStop },
  { type: "fog", label: "Fog / Below CAT I", minutes: 20, Icon: IconFog },
  { type: "low_visibility", label: "Low Visibility", minutes: 15, Icon: IconHaze },
  { type: "high_wind", label: "High Crosswind", minutes: 15, Icon: IconWind },
  { type: "thunderstorm", label: "Thunderstorm", minutes: 10, Icon: IconStorm },
  { type: "taxiway_closure", label: "Close Taxiway A", minutes: 10, Icon: IconNoEntry, target: "A" },
  { type: "emergency_arrival", label: "Emergency Arrival", minutes: 0, Icon: IconSiren },
];

function AtcConsole({ onDisrupt, disruptions }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className={`panel console ${collapsed ? "collapsed" : ""}`}>
      <div className="panel-header">
        <div className="panel-title warn">
          <IconWarningTriangle size={13} className="title-icon" /> ATC DISRUPTION CONSOLE
        </div>
        <CollapseToggle collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      </div>
      {!collapsed && (
        <>
          <div className="console-grid">
            {ACTIONS.map((a) => (
              <button
                key={a.type}
                className="console-btn"
                onClick={() => onDisrupt(a.type, a.minutes, a.target)}
              >
                <a.Icon size={15} className="btn-icon" />
                <span>{a.label} {a.minutes > 0 ? `${a.minutes}m` : ""}</span>
              </button>
            ))}
            <button className="console-btn clear" onClick={() => onDisrupt("clear", 0)}>
              <IconCheckCircle size={15} className="btn-icon" />
              <span>Clear All</span>
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
          <div className="console-note">
            Every action here mutates the live SimPy twin. Weather effects (fog, crosswind,
            thunderstorm, ...) stack - trigger several at once and each runs on its own timer.
          </div>
        </>
      )}
    </div>
  );
}


// Memoised: these panels are fed a throttled frame (see App.jsx), so
// skipping re-render when their props are identical keeps DOM work off the
// hot path entirely.
export default memo(AtcConsole);
