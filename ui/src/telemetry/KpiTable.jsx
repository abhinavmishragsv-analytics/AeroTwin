import { fmt } from "./lib";

/** Side-by-side KPIs. Best value per row is green, worst amber (only when the
 *  KPI has a direction: "low" or "high" is better) and only with 2+ legs. */
export default function KpiTable({ flights }) {
  if (!flights.length) return null;
  const keys = [];
  const info = {};
  flights.forEach((f) => f.detail.kpis.forEach((k) => {
    if (!info[k.key]) { info[k.key] = k; keys.push(k.key); }
  }));
  return (
    <div className="tm-kpi-wrap">
      <table className="tm-kpi">
        <thead>
          <tr>
            <th>Metric</th>
            {flights.map((f) => (
              <th key={f.id}><i style={{ background: f.color }} />{f.detail.flight}<small>{f.detail.meta.type}</small></th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => {
            const k = info[key];
            const vals = flights.map((f) => f.detail.kpis.find((x) => x.key === key));
            const nums = vals.map((v) => (typeof v?.value === "number" ? v.value : null));
            const valid = nums.filter((v) => v != null);
            let best = null, worst = null;
            if (k.better && valid.length > 1 && Math.min(...valid) !== Math.max(...valid)) {
              best = k.better === "low" ? Math.min(...valid) : Math.max(...valid);
              worst = k.better === "low" ? Math.max(...valid) : Math.min(...valid);
            }
            return (
              <tr key={key}>
                <td>{k.label}{k.note && <span className="tm-kpi-note" title={k.note}>ⓘ</span>}</td>
                {vals.map((v, i) => {
                  const val = v?.value;
                  const cls = nums[i] != null && nums[i] === best ? "best" : nums[i] != null && nums[i] === worst ? "worst" : "";
                  const strongNo = val === "NO";
                  return (
                    <td key={flights[i].id} className={`${cls} ${strongNo ? "worst" : ""} ${val === "YES" ? "best" : ""}`}
                      title={v?.note || undefined}>
                      {val == null ? "—" : typeof val === "string" ? val : fmt(val, Math.abs(val) < 10 ? 2 : 1)}
                      {v?.unit && val != null && typeof val !== "string" ? <small> {v.unit}</small> : null}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
