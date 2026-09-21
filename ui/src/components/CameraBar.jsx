import { IconGlobe, IconPlane, IconRunway, IconTower } from "./icons";
/** CameraBar - bottom preset view switcher. */
const PRESETS = [
  { id: "orbit", label: "Orbit Airfield", Icon: IconGlobe },
  { id: "chase", label: "Chase Aircraft", Icon: IconPlane },
  { id: "tower", label: "ATC Tower Cab", Icon: IconTower },
  { id: "runway", label: "Runway Cam", Icon: IconRunway },
];

export default function CameraBar({ active, onSelect }) {
  return (
    <div className="camera-bar">
      {PRESETS.map((p) => (
        <button
          key={p.id}
          className={`camera-btn ${active === p.id ? "active" : ""}`}
          onClick={() => onSelect(p.id)}
        >
          <p.Icon size={14} className="btn-icon" />
          <span>{p.label}</span>
        </button>
      ))}
    </div>
  );
}
