import React, { Suspense, lazy } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { isTelemetryPath } from './lib/api';
import './index.css';

// The telemetry page (charts, uPlot) is a separate chunk: the 3D map page
// never pays for it.
const TelemetryPage = lazy(() => import('./telemetry/TelemetryPage.jsx'));

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {isTelemetryPath() ? (
      <Suspense fallback={<div className="tm-loading">Loading telemetry…</div>}>
        <TelemetryPage />
      </Suspense>
    ) : (
      <App />
    )}
  </React.StrictMode>
);
