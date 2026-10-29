import { useMemo, useState } from "react";
import { MAX_COMPARE, fmtDuration } from "./lib";

const OUTCOME = {
  landed: { text: "LANDED", cls: "ok" }, departed: { text: "DEPARTED", cls: "ok" },
  diverted: { text: "DIVERTED", cls: "bad" }, cancelled: { text: "CANCELLED", cls: "bad" },
  aborted: { text: "ENDED", cls: "dim" }, live: { text: "LIVE", cls: "live" },
};

export default function FlightPicker({ legs, direction, selected, colors, onToggle, onClear, filter, setFilter }) {
  const [q, setQ] = useState("");
  const list = useMemo(() => legs
    .filter((l) => l.direction === direction)
    .filter((l) => (filter === "all" ? true : filter === "live" ? l.live : !l.live))
    .filter((l) => !q || `${l.flight} ${l.type_name} ${l.other_airport}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => b.start_t - a.start_t), [legs, direction, filter, q]);
  const full = selected.length >= MAX_COMPARE;
  return (
    <aside className="tm-picker">
      <div className="tm-picker-head">
        <div className="tm-picker-title">{direction === "ARR" ? "Arrivals" : "Departures"}
          <span>{list.length}</span></div>
        <div className="tm-seg">
          {["completed", "live", "all"].map((f) => (
            <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>{f}</button>
          ))}
        </div>
        <input className="tm-search" placeholder="Search callsign, type, route…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="tm-picker-sub">
          <span>{selected.length}/{MAX_COMPARE} selected</span>
          {selected.length > 0 && <button className="tm-link" onClick={onClear}>clear</button>}
        </div>
      </div>
      <div className="tm-picker-list">
        {list.length === 0 && (
          <div className="tm-empty">
            {filter === "completed"
              ? `No completed ${direction === "ARR" ? "arrivals" : "departures"} yet. Flights appear here as soon as they finish; try “live” to watch one now.`
              : "Nothing here yet."}
          </div>
        )}
        {list.map((l) => {
          const on = selected.includes(l.id);
          const o = OUTCOME[l.outcome] || OUTCOME.aborted;
          const disabled = !on && full;
          return (
            <button key={l.id} className={`tm-leg ${on ? "on" : ""}`} disabled={disabled}
              style={on ? { borderColor: colors[l.id] } : undefined} onClick={() => onToggle(l.id)}>
              <span className="tm-swatch" style={{ background: on ? colors[l.id] : "transparent", borderColor: on ? colors[l.id] : "rgba(255,255,255,0.25)" }} />
              <span className="tm-leg-main">
                <span className="tm-leg-row1">
                  <b>{l.flight}</b><span className="tm-leg-type">{l.type}</span>
                  <span className={`tm-badge ${o.cls}`}>{o.text}</span>
                </span>
                <span className="tm-leg-row2">
                  {l.flight_number} · {direction === "ARR" ? "from" : "to"} {l.other_airport} · RWY {l.runway} · {fmtDuration(l.duration_s)}
                </span>
                {(l.conditions.length > 0 || l.go_arounds > 0) && (
                  <span className="tm-leg-tags">
                    {l.go_arounds > 0 && <em className="warn">go-around ×{l.go_arounds}</em>}
                    {l.conditions.map((c) => <em key={c}>{c.toLowerCase()}</em>)}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
