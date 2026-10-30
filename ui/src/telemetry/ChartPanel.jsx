import { memo, useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { STEPPED, fmt, hoverBus } from "./lib";

const SYNC = uPlot.sync("aerotwin-tm");
const AXIS = "#5B6B82";
const GRID = "rgba(19,35,59,0.09)";

/**
 * One telemetry channel, one trace per compared flight, sharing a crosshair
 * with every other panel. Reference speeds, event ticks and phase bands are
 * drawn in a uPlot `draw` hook from `decor`, kept in a ref so changing them
 * never rebuilds the chart.
 */
function ChartPanel({ channel, label, unit, source, series, data, xLabel, decor, onRemove, height = 170 }) {
  const rootRef = useRef(null);
  const plotRef = useRef(null);
  const legendRef = useRef(null);
  const decorRef = useRef(decor);
  decorRef.current = decor;
  const dataRef = useRef(data);
  dataRef.current = data;
  const seriesKey = series.map((s) => `${s.id}|${s.color}|${s.dashed ? 1 : 0}`).join(",");

  useEffect(() => {
    const el = rootRef.current;
    const stepped = STEPPED.has(channel);
    const opts = {
      width: el.clientWidth || 600,
      height,
      padding: [8, 12, 0, 0],
      legend: { show: false },
      cursor: {
        sync: { key: SYNC.key },
        drag: { x: true, y: false, setScale: true },
        points: { size: 7 },
      },
      scales: {
        x: { time: false },
        // Deviation scales always show the +-1 dot "stable" band, even when
        // the aircraft hugged the beam and the data span a hundredth of a dot.
        ...(channel === "gs_dev" || channel === "loc_dev"
          ? { y: { range: (u, min, max) => [Math.min(min ?? 0, -1.5), Math.max(max ?? 0, 1.5)] } }
          : {}),
      },
      axes: [
        { stroke: AXIS, grid: { stroke: GRID, width: 1 }, ticks: { stroke: GRID }, font: "11px Hanken Grotesk, Inter, system-ui", size: 34,
          values: (u, vals) => vals.map((v) => fmt(v, 0)) },
        { stroke: AXIS, grid: { stroke: GRID, width: 1 }, ticks: { stroke: GRID }, font: "11px Hanken Grotesk, Inter, system-ui", size: 58,
          values: (u, vals) => vals.map((v) => fmt(v, Math.abs(v) < 10 && v % 1 ? 2 : 0)) },
      ],
      series: [
        {},
        ...series.map((s) => ({
          label: s.label,
          stroke: s.color,
          width: s.dashed ? 1.2 : 1.8,
          dash: s.dashed ? [5, 4] : undefined,
          spanGaps: true,
          points: { show: false },
          paths: stepped ? uPlot.paths.stepped({ align: 1 }) : undefined,
        })),
      ],
      hooks: {
        setCursor: [(u) => {
          const i = u.cursor.idx;
          hoverBus.set(i == null ? null : u.data[0][i]);
          const box = legendRef.current;
          if (!box) return;
          const cells = box.querySelectorAll("[data-si]");
          cells.forEach((c) => {
            const si = Number(c.dataset.si);
            const v = i == null ? null : u.data[si + 1]?.[i];
            c.textContent = v == null ? "" : fmt(v, Math.abs(v) < 10 ? 2 : 1);
          });
        }],
        draw: [(u) => {
          const d = decorRef.current;
          if (!d) return;
          const { ctx } = u;
          const { left, top, width, height: h } = u.bbox;
          ctx.save();
          ctx.beginPath(); ctx.rect(left, top, width, h); ctx.clip();
          const px = (x) => u.valToPos(x, "x", true);
          const py = (y) => u.valToPos(y, "y", true);
          const dpr = devicePixelRatio || 1;
          // phase bands (single flight, time axis)
          if (d.bands) {
            for (const b of d.bands) {
              ctx.fillStyle = b.color + "1c";
              const x0 = px(b.x0), x1 = px(b.x1);
              ctx.fillRect(x0, top, Math.max(1, x1 - x0), h);
              if (d.bandLabels && x1 - x0 > 46 * dpr) {
                ctx.fillStyle = b.color + "cc";
                ctx.font = `${10 * dpr}px Hanken Grotesk, Inter, system-ui`;
                ctx.fillText(b.label, x0 + 4 * dpr, top + 12 * dpr);
              }
            }
          }
          // horizontal reference lines
          for (const r of d.hlines || []) {
            const y = py(r.y);
            if (y < top || y > top + h) continue;
            ctx.strokeStyle = r.color + "aa"; ctx.lineWidth = dpr;
            ctx.setLineDash([4 * dpr, 4 * dpr]);
            ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + width, y); ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = r.color; ctx.font = `${9.5 * dpr}px Hanken Grotesk, Inter, system-ui`;
            ctx.textAlign = "right";
            ctx.fillText(r.label, left + width - 4 * dpr, y - 3 * dpr);
            ctx.textAlign = "left";
          }
          for (const b of d.hbands || []) {
            const y0 = py(b.y1), y1 = py(b.y0);
            ctx.fillStyle = b.color;
            ctx.fillRect(left, y0, width, y1 - y0);
          }
          // event ticks
          for (const e of d.events || []) {
            const x = px(e.x);
            if (x < left || x > left + width) continue;
            ctx.strokeStyle = e.color + "99"; ctx.lineWidth = dpr;
            ctx.setLineDash([2 * dpr, 3 * dpr]);
            ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + h); ctx.stroke();
            ctx.setLineDash([]);
            if (e.label) {
              ctx.save();
              ctx.translate(x - 3 * dpr, top + h - 4 * dpr);
              ctx.rotate(-Math.PI / 2);
              ctx.fillStyle = e.color; ctx.font = `${9.5 * dpr}px Hanken Grotesk, Inter, system-ui`;
              ctx.fillText(e.label, 0, 0);
              ctx.restore();
            }
          }
          if (d.zero != null) {
            const x = px(d.zero);
            ctx.strokeStyle = "rgba(19,35,59,0.45)"; ctx.lineWidth = dpr;
            ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + h); ctx.stroke();
          }
          ctx.restore();
        }],
      },
    };
    const u = new uPlot(opts, dataRef.current, el);
    plotRef.current = u;
    const ro = new ResizeObserver(() => {
      if (el.clientWidth > 0) u.setSize({ width: el.clientWidth, height });
    });
    ro.observe(el);
    el.addEventListener("dblclick", () => u.setData(dataRef.current, true));
    return () => { ro.disconnect(); u.destroy(); plotRef.current = null; };
    // Rebuild only when the set of traces changes, never on data updates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel, seriesKey, height]);

  useEffect(() => {
    const u = plotRef.current;
    if (u) u.setData(data, true);
  }, [data]);

  useEffect(() => { plotRef.current?.redraw(false); }, [decor]);

  return (
    <div className="tm-chart">
      <div className="tm-chart-head">
        <div className="tm-chart-title">
          <span>{label}</span>
          {unit && <span className="tm-unit">{unit}</span>}
          <span className={`tm-src tm-src-${source}`} title={
            source === "sim" ? "Read directly from the simulation"
              : source === "derived" ? "Computed from the simulated motion"
                : "Modelled: plausible values the simulation does not compute itself"}>{source}</span>
        </div>
        <div className="tm-legend" ref={legendRef}>
          {series.filter((s) => !s.dashed).map((s) => (
            <span key={s.id} className="tm-legend-item" style={{ color: s.color }}>
              <i style={{ background: s.color }} />{s.short}
              <b data-si={series.indexOf(s)}></b>
            </span>
          ))}
        </div>
        {onRemove && <button className="tm-x" title="Hide this chart" onClick={() => onRemove(channel)}>×</button>}
      </div>
      <div ref={rootRef} className="tm-chart-body" />
      <div className="tm-xlabel">{xLabel}</div>
    </div>
  );
}

export default memo(ChartPanel);
