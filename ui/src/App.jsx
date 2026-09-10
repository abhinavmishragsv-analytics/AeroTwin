import React, { useEffect, useState, useCallback } from 'react';
import Map from 'react-map-gl/maplibre';
import * as maplibregl from 'maplibre-gl';
import { DeckGL } from '@deck.gl/react';
import { ScenegraphLayer } from '@deck.gl/mesh-layers';
import { PathLayer, ScatterplotLayer, PolygonLayer } from '@deck.gl/layers';
import 'maplibre-gl/dist/maplibre-gl.css';

// MapTiler API Key from environment
const MAPTILER_KEY = import.meta.env.VITE_MAPTILER_KEY || 'SZbWa44ht6gE8vB8WqhV';

// FastAPI backend base URL (REST + WebSocket share the same host:port)
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const WS_URL = API_BASE.replace(/^http/, 'ws') + '/ws/twin';

// Exact Vadodara Airport (VABO) Initial Overview - also the locked orbit pivot
// (see ORBIT_PIVOT below): the camera orbits and zooms around this point and
// is never allowed to pan away from it.
const INITIAL_VIEW_STATE = {
  longitude: 73.2260,
  latitude: 22.3350,
  zoom: 15.5,
  pitch: 65,
  bearing: 44,
  minZoom: 13.5,
  maxZoom: 19,
  maxPitch: 85
};
const ORBIT_PIVOT = { longitude: INITIAL_VIEW_STATE.longitude, latitude: INITIAL_VIEW_STATE.latitude };

// Vadodara Runway 04/22 & Taxiway Alpha Geographic Paths
const AIRPORT_GEOMETRY = [
  // Runway 04/22 Centerline (2,469m)
  {
    path: [
      [73.21930, 22.32970], // Runway 04 Threshold
      [73.23610, 22.34560]  // Runway 22 Threshold
    ],
    color: [255, 255, 255, 180],
    width: 6
  },
  // Taxiway Alpha Centerline (Apron to Runway 04)
  {
    path: [
      [73.22600, 22.33550], // Stand 1
      [73.22520, 22.33470], // Apron Taxi Line
      [73.22280, 22.33250], // Alpha Midpoint
      [73.22010, 22.33020], // Runway 04 Holding Point
      [73.21930, 22.32970]  // Runway 04 Entry
    ],
    color: [250, 204, 21, 200], // Aviation Yellow
    width: 4
  }
];

// Disruptions the ATC console can inject - each maps 1:1 to core/twin_sim.py's
// inject_disruption() types. duration_minutes is a sensible default; the twin
// clamps it server-side to [0, 180].
const DISRUPTION_ACTIONS = [
  { type: 'runway_closure', duration_minutes: 15, label: 'Runway Closure', icon: '🚧' },
  { type: 'ground_stop', duration_minutes: 10, label: 'Ground Stop', icon: '🛑' },
  { type: 'fog', duration_minutes: 20, label: 'Fog / Cat III', icon: '🌫️' },
  { type: 'high_wind', duration_minutes: 15, label: 'High Crosswind', icon: '💨' },
  { type: 'clear', duration_minutes: 0, label: 'Clear All', icon: '✅' }
];

// Build a rectangular building footprint as a rotated GeoJSON-style polygon
// ([lng, lat] winding order, matching deck.gl's PolygonLayer convention).
// center is [lat, lng]; widthM/depthM are the footprint's plan dimensions in
// meters; rotationDeg rotates the rectangle clockwise from north, so a
// building can be aligned with the runway/taxiway instead of sitting as a
// plain north-south box.
function rectFootprint([lat, lng], widthM, depthM, rotationDeg = 0) {
  const rad = (rotationDeg * Math.PI) / 180;
  const halfW = widthM / 2;
  const halfD = depthM / 2;
  const metersPerDegLat = 111320;
  const metersPerDegLng = 111320 * Math.cos((lat * Math.PI) / 180);

  return [
    [-halfW, -halfD],
    [halfW, -halfD],
    [halfW, halfD],
    [-halfW, halfD]
  ].map(([e, n]) => {
    const re = e * Math.cos(rad) + n * Math.sin(rad);
    const rn = -e * Math.sin(rad) + n * Math.cos(rad);
    return [lng + re / metersPerDegLng, lat + rn / metersPerDegLat];
  });
}

// Illustrative 3D massing for VABO's terminal apron - real extruded geometry
// (not a flat texture), aligned with the runway/taxiway orientation. Footprint
// sizes and offsets are approximate, not surveyed, since the point is to give
// the twin real volumetric structures to orbit around.
const AIRPORT_BUILDINGS = [
  {
    id: 'terminal',
    name: 'Terminal Building',
    footprint: rectFootprint([22.33495, 73.22715], 65, 24, 44),
    height: 13,
    fillColor: [148, 163, 184, 235],
    lineColor: [226, 232, 240, 255]
  },
  {
    id: 'atc-tower',
    name: 'ATC Tower',
    footprint: rectFootprint([22.3363, 73.2251], 13, 13, 0),
    height: 32,
    fillColor: [100, 116, 139, 235],
    lineColor: [56, 189, 248, 255]
  },
  {
    id: 'hangar',
    name: 'Maintenance Hangar',
    footprint: rectFootprint([22.33390, 73.22820], 50, 38, 44),
    height: 11,
    fillColor: [120, 113, 108, 230],
    lineColor: [214, 211, 209, 255]
  }
];

export default function App() {
  const [twinState, setTwinState] = useState({ flights: [], time: 0 });
  const [connectionStatus, setConnectionStatus] = useState('CONNECTING');
  const [viewState, setViewState] = useState(INITIAL_VIEW_STATE);
  const [cameraMode, setCameraMode] = useState('orbit'); // 'orbit' | 'chase' | 'tower' | 'threshold'
  const [disruptionBusy, setDisruptionBusy] = useState(null);   // type currently in-flight, or null
  const [disruptionError, setDisruptionError] = useState(null);

  // Bi-directional control: POST a disruption to the FastAPI twin. The SimPy
  // simulation mutates immediately server-side and the next WebSocket frame
  // reflects it for every connected client.
  const injectDisruption = useCallback(async (action) => {
    setDisruptionBusy(action.type);
    setDisruptionError(null);
    try {
      const res = await fetch(`${API_BASE}/api/disrupt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: action.type, duration_minutes: action.duration_minutes })
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
    } catch (err) {
      setDisruptionError(err.message || 'Failed to reach twin backend');
    } finally {
      setDisruptionBusy(null);
    }
  }, []);

  // WebSocket Live Simulation Stream.
  //
  // Guarded with a `cancelled` flag against React 18 StrictMode's dev-only
  // double-invocation of effects (mount -> cleanup -> mount again): without
  // it, the first socket's onclose handler can fire after the second effect
  // run has already started a new connection, causing a spurious
  // "WebSocket is closed before the connection is established" console
  // warning and a redundant reconnect timer. This is a dev-mode-only
  // artifact - it does not happen in a production build - but guarding it
  // properly is also just correct effect hygiene either way.
  useEffect(() => {
    let ws;
    let timer;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        if (!cancelled) setConnectionStatus('ONLINE');
      };
      ws.onmessage = (e) => {
        if (cancelled) return;
        try {
          setTwinState(JSON.parse(e.data));
        } catch (err) {
          console.error('Error parsing telemetry:', err);
        }
      };
      ws.onclose = () => {
        if (cancelled) return;
        setConnectionStatus('RECONNECTING...');
        timer = setTimeout(connect, 2000);
      };
      ws.onerror = () => {
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close();
        }
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        ws.close();
      }
    };
  }, []);

  const primaryFlight = twinState.flights[0] || null;
  const twin = twinState.twin || null;

  // Dynamic Camera Modes
  useEffect(() => {
    if (cameraMode === 'orbit') {
      // Re-center on the runway pivot immediately when (re-)entering orbit
      // mode, rather than leaving the camera wherever chase/tower/threshold
      // last left it.
      setViewState({ ...INITIAL_VIEW_STATE, transitionDuration: 400 });
      return;
    }

    if (!primaryFlight) return;

    if (cameraMode === 'chase') {
      // Smoothly follow behind the aircraft as it taxis and climbs
      setViewState((prev) => ({
        ...prev,
        longitude: primaryFlight.lng,
        latitude: primaryFlight.lat,
        zoom: primaryFlight.altitude > 100 ? 15.0 : 16.5,
        pitch: 75,
        bearing: primaryFlight.heading || 44,
        transitionDuration: 120
      }));
    } else if (cameraMode === 'tower') {
      // Look from VABO ATC Tower (73.2250, 22.3362) overlooking Runway 04
      setViewState((prev) => ({
        ...prev,
        longitude: 73.2250,
        latitude: 22.3362,
        zoom: 15.6,
        pitch: 68,
        bearing: 215,
        transitionDuration: 300
      }));
    } else if (cameraMode === 'threshold') {
      // Look from Runway 04 threshold looking down the runway
      setViewState((prev) => ({
        ...prev,
        longitude: 73.2185,
        latitude: 22.3288,
        zoom: 16.8,
        pitch: 80,
        bearing: 44,
        transitionDuration: 300
      }));
    }
  }, [cameraMode, primaryFlight]);

  // MapTiler 3D Satellite Map Style with 3D Terrain Elevation
  const mapStyle = {
    version: 8,
    sources: {
      'maptiler-satellite': {
        type: 'raster',
        tiles: [
          `https://api.maptiler.com/maps/satellite/{z}/{x}/{y}.jpg?key=${MAPTILER_KEY}`
        ],
        tileSize: 256
      },
      'maptiler-terrain': {
        type: 'raster-dem',
        tiles: [
          `https://api.maptiler.com/tiles/terrain-rgb-v2/{z}/{x}/{y}.webp?key=${MAPTILER_KEY}`
        ],
        tileSize: 512,
        maxzoom: 14
      }
    },
    layers: [
      {
        id: 'satellite-tiles',
        type: 'raster',
        source: 'maptiler-satellite',
        minzoom: 0,
        maxzoom: 22
      }
    ],
    terrain: {
      source: 'maptiler-terrain',
      exaggeration: 1.5
    },
    sky: {
      'sky-color': '#0284c7',
      'sky-horizon-blend': 0.5,
      'horizon-color': '#bae6fd',
      'horizon-fog-blend': 0.5
    }
  };

  // Deck.GL Layers: 3D Buildings + Aircraft Scenegraph + Trajectory Paths
  const layers = [
    // Airfield Runway & Taxiway Centerline Guidelines
    new PathLayer({
      id: 'airport-guidelines',
      data: AIRPORT_GEOMETRY,
      getPath: (d) => d.path,
      getColor: (d) => d.color,
      getWidth: (d) => d.width,
      widthUnits: 'meters',
      billboard: false,
      pickable: false
    }),

    // Real extruded 3D building massing (terminal, ATC tower, hangar) - this is
    // what makes the twin a true volumetric 3D model rather than a flat
    // satellite photo with markers floating over it.
    new PolygonLayer({
      id: 'airport-buildings',
      data: AIRPORT_BUILDINGS,
      getPolygon: (d) => d.footprint,
      extruded: true,
      wireframe: true,
      getElevation: (d) => d.height,
      getFillColor: (d) => d.fillColor,
      getLineColor: (d) => d.lineColor,
      getLineWidth: 1,
      lineWidthUnits: 'meters',
      material: {
        ambient: 0.4,
        diffuse: 0.6,
        shininess: 32,
        specularColor: [60, 64, 70]
      },
      pickable: false
    }),

    // Ground Contact Shadow / Position Marker
    new ScatterplotLayer({
      id: 'aircraft-ground-shadow',
      data: twinState.flights,
      getPosition: (d) => [d.lng, d.lat, 0],
      getRadius: (d) => (d.altitude > 10 ? 18 : 12),
      radiusUnits: 'meters',
      getFillColor: [15, 23, 42, 140],
      stroked: true,
      getLineColor: [56, 189, 248, 200],
      getLineWidth: 2
    }),

    // 3D Airplane Model (Real GLB with PBR Materials & Dynamic Altitude Climb).
    // Position/orientation transitions are tuned to match the backend's
    // broadcast rate (core/config.py STREAM_HZ) so the client is never
    // interpolating across a gap wider than one real update.
    new ScenegraphLayer({
      id: 'aircraft-3d-model',
      data: twinState.flights,
      scenegraph: '/aircraft.glb',
      getPosition: (d) => [d.lng, d.lat, d.altitude || 0],
      getOrientation: (d) => [d.pitch || 0, -d.heading + 90, d.roll || 0],
      sizeScale: 28,
      _lighting: 'pbr',
      transitions: {
        getPosition: 90,
        getOrientation: 90
      }
    })
  ];

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        position: 'relative',
        background: '#0a0f18',
        overflow: 'hidden',
        userSelect: 'none'
      }}
    >
      {/* TOP-LEFT: Airport Telemetry HUD */}
      <div
        style={{
          position: 'absolute',
          top: 20,
          left: 20,
          zIndex: 10,
          background: 'rgba(15, 23, 42, 0.9)',
          backdropFilter: 'blur(12px)',
          border: '1px solid rgba(56, 189, 248, 0.35)',
          borderRadius: '14px',
          padding: '20px 24px',
          color: '#f8fafc',
          fontFamily: "'Inter', -apple-system, sans-serif",
          boxShadow: '0 12px 36px rgba(0, 0, 0, 0.7)',
          minWidth: '320px',
          maxWidth: '380px'
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, color: '#38bdf8' }}>
              AEROTWIN • VABO
            </h2>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '2px' }}>
              Vadodara Airport 3D Geospatial Twin
            </div>
          </div>
          <span
            style={{
              fontSize: '0.75rem',
              padding: '3px 10px',
              borderRadius: '20px',
              fontWeight: 600,
              backgroundColor: connectionStatus === 'ONLINE' ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)',
              color: connectionStatus === 'ONLINE' ? '#4ade80' : '#f87171',
              border: `1px solid ${connectionStatus === 'ONLINE' ? '#22c55e' : '#ef4444'}`
            }}
          >
            ● {connectionStatus}
          </span>
        </div>

        {/* Airport Metrics */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', margin: '12px 0' }}>
          <div style={{ background: 'rgba(30, 41, 59, 0.7)', padding: '8px 12px', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>SIM TIME</div>
            <div style={{ fontSize: '1rem', fontWeight: 600, color: '#f8fafc' }}>T+{twinState.time}s</div>
          </div>
          <div style={{ background: 'rgba(30, 41, 59, 0.7)', padding: '8px 12px', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>RUNWAY 04/22</div>
            <div
              style={{
                fontSize: '0.95rem',
                fontWeight: 600,
                color: twin?.runway_closed || twin?.ground_stop ? '#f87171' : '#4ade80'
              }}
            >
              {twin?.ground_stop ? 'GROUND STOP' : twin?.runway_closed ? 'CLOSED' : 'OPEN'}
            </div>
          </div>
          <div style={{ background: 'rgba(30, 41, 59, 0.7)', padding: '8px 12px', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>WEATHER</div>
            <div
              style={{
                fontSize: '0.95rem',
                fontWeight: 600,
                color: twin?.weather?.condition === 'CLEAR' ? '#4ade80' : '#facc15'
              }}
            >
              {twin?.weather?.condition || 'CLEAR'}
            </div>
          </div>
          <div style={{ background: 'rgba(30, 41, 59, 0.7)', padding: '8px 12px', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>QUEUE DEPTH</div>
            <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#38bdf8' }}>
              {twin?.queue_depth ?? 0} aircraft
            </div>
          </div>
        </div>

        {/* Recent Disruption Log */}
        {twin?.disruptions?.length > 0 && (
          <div style={{ marginBottom: '12px' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600, marginBottom: '6px' }}>
              ATC EVENT LOG
            </div>
            <div style={{ maxHeight: '70px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {twin.disruptions.slice(0, 3).map((d, i) => (
                <div key={i} style={{ fontSize: '0.72rem', color: '#cbd5e1' }}>
                  <span style={{ color: '#64748b' }}>T+{d.time}s</span> — {d.label}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Active Flights Stream */}
        <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600, marginBottom: '6px' }}>
          ACTIVE FLIGHT TELEMETRY
        </div>
        <div style={{ maxHeight: '180px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {twinState.flights.length === 0 ? (
            <div style={{ color: '#64748b', fontStyle: 'italic', fontSize: '0.85rem' }}>
              Spawning aircraft at Stand 1...
            </div>
          ) : (
            twinState.flights.map((f) => (
              <div
                key={f.id}
                style={{
                  padding: '8px 12px',
                  borderRadius: '8px',
                  background: f.risk > 0.7 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(15, 23, 42, 0.8)',
                  border: `1px solid ${f.risk > 0.7 ? 'rgba(239, 68, 68, 0.4)' : 'rgba(56, 189, 248, 0.2)'}`,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}
              >
                <div>
                  <span style={{ fontWeight: 700, color: '#f8fafc', marginRight: '6px' }}>{f.id}</span>
                  <span
                    style={{
                      fontSize: '0.7rem',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      background: 'rgba(56, 189, 248, 0.2)',
                      color: '#38bdf8'
                    }}
                  >
                    {f.status.toUpperCase()}
                  </span>
                </div>
                <div style={{ textAlign: 'right', fontSize: '0.75rem', color: '#94a3b8' }}>
                  <div>{f.altitude || 0}m • {f.speed || 0} kt</div>
                  <div style={{ color: f.risk > 0.7 ? '#f87171' : '#4ade80' }}>
                    Risk: {f.risk.toFixed(2)}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* BOTTOM-RIGHT: ATC Disruption Console - the "write" side of the bi-directional twin */}
      <div
        style={{
          position: 'absolute',
          bottom: 24,
          right: 20,
          zIndex: 10,
          background: 'rgba(15, 23, 42, 0.92)',
          backdropFilter: 'blur(16px)',
          border: '1px solid rgba(56, 189, 248, 0.35)',
          borderRadius: '14px',
          padding: '14px 16px',
          color: '#f8fafc',
          boxShadow: '0 12px 36px rgba(0, 0, 0, 0.7)',
          width: '220px'
        }}
      >
        <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#38bdf8', marginBottom: '10px' }}>
          🗼 ATC DISRUPTION CONSOLE
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {DISRUPTION_ACTIONS.map((action) => {
            const isClear = action.type === 'clear';
            const isBusy = disruptionBusy === action.type;
            return (
              <button
                key={action.type}
                onClick={() => injectDisruption(action)}
                disabled={disruptionBusy !== null}
                title={isClear ? 'Clear all active disruptions' : `Inject for ${action.duration_minutes} min`}
                style={{
                  background: isClear ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.12)',
                  border: `1px solid ${isClear ? 'rgba(34, 197, 94, 0.4)' : 'rgba(239, 68, 68, 0.35)'}`,
                  color: isClear ? '#4ade80' : '#fca5a5',
                  borderRadius: '8px',
                  padding: '8px 10px',
                  fontSize: '0.78rem',
                  fontWeight: 600,
                  cursor: disruptionBusy !== null ? 'wait' : 'pointer',
                  opacity: disruptionBusy !== null && !isBusy ? 0.5 : 1,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  transition: 'all 0.15s ease'
                }}
              >
                <span>{action.icon} {action.label}</span>
                {!isClear && <span style={{ color: '#94a3b8', fontWeight: 400 }}>{action.duration_minutes}m</span>}
              </button>
            );
          })}
        </div>
        {disruptionError && (
          <div style={{ fontSize: '0.7rem', color: '#f87171', marginTop: '8px' }}>
            ⚠ {disruptionError}
          </div>
        )}
        <div style={{ fontSize: '0.65rem', color: '#64748b', marginTop: '8px', lineHeight: '1.3' }}>
          Every action here mutates the live SimPy twin - watch aircraft react in real time.
        </div>
      </div>

      {/* BOTTOM-CENTER: Cinematic Camera Mode Controls */}
      <div
        style={{
          position: 'absolute',
          bottom: 24,
          left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 10,
          background: 'rgba(15, 23, 42, 0.92)',
          backdropFilter: 'blur(16px)',
          border: '1px solid rgba(56, 189, 248, 0.35)',
          borderRadius: '30px',
          padding: '6px 10px',
          display: 'flex',
          gap: '8px',
          boxShadow: '0 12px 36px rgba(0, 0, 0, 0.7)'
        }}
      >
        {[
          { id: 'orbit', label: 'Orbit Airfield', icon: '🌐' },
          { id: 'chase', label: 'Chase Aircraft', icon: '✈️' },
          { id: 'tower', label: 'ATC Tower Cab', icon: '🗼' },
          { id: 'threshold', label: 'Runway 04 Cam', icon: '🛫' }
        ].map((btn) => {
          const isActive = cameraMode === btn.id;
          return (
            <button
              key={btn.id}
              onClick={() => setCameraMode(btn.id)}
              style={{
                background: isActive ? 'linear-gradient(135deg, #0284c7, #0369a1)' : 'transparent',
                color: isActive ? '#ffffff' : '#94a3b8',
                border: 'none',
                borderRadius: '20px',
                padding: '8px 16px',
                fontSize: '0.8rem',
                fontWeight: isActive ? 700 : 500,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                transition: 'all 0.2s ease'
              }}
            >
              <span>{btn.icon}</span>
              <span>{btn.label}</span>
            </button>
          );
        })}
      </div>

      {/* MapLibre + Deck.GL 3D Geospatial Airfield */}
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: next }) => {
          if (cameraMode === 'orbit') {
            // Lock the pivot: carry through zoom/pitch/bearing from user
            // interaction, but always snap longitude/latitude back to the
            // runway pivot so panning is impossible - only orbit + zoom remain.
            setViewState({ ...next, longitude: ORBIT_PIVOT.longitude, latitude: ORBIT_PIVOT.latitude });
          }
        }}
        controller={
          cameraMode === 'orbit'
            ? {
                dragPan: false,
                dragRotate: true,
                scrollZoom: true,
                doubleClickZoom: false,
                touchZoom: true,
                touchRotate: true,
                keyboard: false
              }
            : false
        }
        layers={layers}
      >
        <Map mapLib={maplibregl} mapStyle={mapStyle} />
      </DeckGL>
    </div>
  );
}
