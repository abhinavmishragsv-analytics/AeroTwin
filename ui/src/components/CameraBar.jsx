/** CameraBar - bottom preset view switcher. */
const PRESETS = [
  { id: "orbit", label: "Orbit Airfield", icon: "🌐" },
  { id: "chase", label: "Chase Aircraft", icon: "✈️" },
  { id: "tower", label: "ATC Tower Cab", icon: "🗼" },
  { id: "runway", label: "Runway Cam", icon: "🛬" },
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
          {p.icon} {p.label}
        </button>
      ))}
    </div>
  );
}
