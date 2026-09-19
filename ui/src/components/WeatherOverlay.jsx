import { memo } from "react";
/** WeatherOverlay - small top-right readout of the live weather driving ATC minima. */
function WeatherOverlay({ weather, windAssessment, activeEnd }) {
  if (!weather) return null;
  const w = windAssessment?.[activeEnd];
  return (
    <div className="panel weather">
      <div className="panel-title">WEATHER</div>
      <div className="weather-row">Visibility: {weather.visibility_m} m</div>
      <div className="weather-row">Ceiling: {weather.ceiling_ft} ft</div>
      <div className="weather-row">
        Wind: {Math.round(weather.wind_dir_deg)}° / {Math.round(weather.wind_kt)} kt
      </div>
      {w && (
        <div className="weather-row">
          Headwind {w.headwind_kt >= 0 ? "+" : ""}
          {w.headwind_kt} kt · Crosswind {w.crosswind_kt} kt
          {!w.usable && <span className="bad"> — OUT OF LIMITS</span>}
        </div>
      )}
    </div>
  );
}


// Memoised: these panels are fed a throttled frame (see App.jsx), so
// skipping re-render when their props are identical keeps DOM work off the
// hot path entirely.
export default memo(WeatherOverlay);
