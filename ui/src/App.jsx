import React, { useEffect, useState } from 'react';
import Map from 'react-map-gl/maplibre';
import * as maplibregl from 'maplibre-gl';
import { DeckGL } from '@deck.gl/react';
import { ScenegraphLayer } from '@deck.gl/mesh-layers';
import 'maplibre-gl/dist/maplibre-gl.css';

// REPLACE THIS WITH YOUR MAPTILER API KEY
const MAPTILER_KEY = import.meta.env.VITE_MAPTILER_KEY || 'SZbWa44ht6gE8vB8WqhV';

const INITIAL_VIEW_STATE = {
  longitude: 73.2263,
  latitude: 22.3362,
  zoom: 15,
  pitch: 65,
  bearing: 45
};

export default function App() {
  const [twinState, setTwinState] = useState({ flights: [], time: 0 });
  const [connectionStatus, setConnectionStatus] = useState('CONNECTING');

  useEffect(() => {
    let ws;
    let timer;

    const connect = () => {
      ws = new WebSocket('ws://localhost:8000/ws/twin');
      ws.onopen = () => {
        setConnectionStatus('ONLINE');
      };
      ws.onmessage = (e) => {
        try {
          const parsed = JSON.parse(e.data);
          setTwinState(parsed);
        } catch (err) {
          console.error('Error parsing telemetry JSON:', err);
        }
      };
      ws.onclose = () => {
        setConnectionStatus('RECONNECTING...');
        timer = setTimeout(connect, 2000);
      };
      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      if (timer) clearTimeout(timer);
      if (ws) ws.close();
    };
  }, []);

  const layers = [
    new ScenegraphLayer({
      id: 'aircraft-3d-layer',
      data: twinState.flights,
      scenegraph: '/aircraft.glb', // Free aircraft.glb located in ui/public/
      getPosition: (d) => [d.lng, d.lat, 0],
      getOrientation: (d) => [0, -d.heading + 90, 90],
      sizeScale: 25,
      getColor: (d) => (d.risk > 0.7 ? [255, 50, 50] : [50, 200, 255]),
      transitions: {
        getPosition: 500,
        getOrientation: 500
      }
    })
  ];

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative', background: '#111' }}>
      <div
        style={{
          position: 'absolute',
          top: 20,
          left: 20,
          zIndex: 10,
          background: 'rgba(15, 23, 42, 0.9)',
          padding: '20px',
          borderRadius: '12px',
          color: '#22d3ee',
          fontFamily: 'monospace',
          border: '1px solid rgba(34, 211, 238, 0.3)',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.5)',
          minWidth: '280px',
          maxWidth: '380px'
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <h2 style={{ margin: 0, fontSize: '1.2rem' }}>AeroTwin: VABO Live</h2>
          <span
            style={{
              fontSize: '0.75rem',
              padding: '2px 8px',
              borderRadius: '4px',
              border: `1px solid ${connectionStatus === 'ONLINE' ? '#22d3ee' : '#ef4444'}`,
              color: connectionStatus === 'ONLINE' ? '#22d3ee' : '#ef4444'
            }}
          >
            {connectionStatus}
          </span>
        </div>
        <p style={{ margin: '4px 0' }}>Sim Time: T+{twinState.time}</p>
        <p style={{ margin: '4px 0' }}>Active Traffic: {twinState.flights.length}</p>
        <hr style={{ borderColor: 'rgba(34, 211, 238, 0.2)', margin: '12px 0' }} />
        <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
          {twinState.flights.length === 0 ? (
            <div style={{ color: '#94a3b8', fontStyle: 'italic', fontSize: '0.85rem' }}>Waiting for flight telemetry...</div>
          ) : (
            twinState.flights.map((f) => (
              <div
                key={f.id}
                style={{
                  margin: '4px 0',
                  padding: '2px 4px',
                  color: f.risk > 0.7 ? '#ef4444' : '#f1f5f9',
                  display: 'flex',
                  justifyContent: 'space-between'
                }}
              >
                <span>{f.id} - {f.status}</span>
                <span>(Risk: {f.risk.toFixed(2)})</span>
              </div>
            ))
          )}
        </div>
      </div>

      <DeckGL controller={true} initialViewState={INITIAL_VIEW_STATE} layers={layers}>
        <Map
          mapLib={maplibregl}
          mapStyle={`https://api.maptiler.com/maps/satellite/style.json?key=${MAPTILER_KEY}`}
        />
      </DeckGL>
    </div>
  );
}
