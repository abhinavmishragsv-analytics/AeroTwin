import React, { useEffect, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Box, Plane, Text, Sky } from '@react-three/drei';

function Aircraft({ data }) {
  const isHighRisk = data.risk > 0.7;
  return (
    <group position={[data.x, data.y + 0.5, data.z]} rotation={[0, data.heading, 0]}>
      {/* Procedural airplane wings & fuselage */}
      <Box args={[3, 0.8, 1]} castShadow>
        <meshStandardMaterial color={isHighRisk ? '#ff3333' : '#33ccff'} roughness={0.3} metalness={0.2} />
      </Box>
      <Box args={[1, 1.5, 4]} castShadow position={[0, 0, 0]}>
        <meshStandardMaterial color={isHighRisk ? '#ff3333' : '#33ccff'} roughness={0.3} metalness={0.2} />
      </Box>
      <Text position={[0, 2, 0]} fontSize={1.2} color="white" outlineColor="black" outlineWidth={0.1}>
        {`${data.id} (${data.status})`}
      </Text>
    </group>
  );
}

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
          console.error('Error parsing twin state:', err);
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

  return (
    <div style={{ width: '100vw', height: '100vh', background: '#0a0a0a', position: 'relative', overflow: 'hidden' }}>
      {/* Heads-Up Display Panel */}
      <div
        style={{
          position: 'absolute',
          top: 20,
          left: 20,
          zIndex: 10,
          color: '#00ffcc',
          fontFamily: "'Courier New', Courier, monospace",
          background: 'rgba(10, 15, 20, 0.85)',
          padding: '24px',
          border: '1px solid #00ffcc',
          borderRadius: '8px',
          boxShadow: '0 8px 32px rgba(0, 255, 204, 0.15)',
          backdropFilter: 'blur(8px)',
          minWidth: '320px',
          maxWidth: '420px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <h2 style={{ margin: 0, fontSize: '1.25rem', letterSpacing: '1px' }}>AeroTwin: VABO Digital Twin</h2>
          <span
            style={{
              fontSize: '0.75rem',
              padding: '2px 8px',
              borderRadius: '4px',
              backgroundColor: connectionStatus === 'ONLINE' ? 'rgba(0,255,204,0.2)' : 'rgba(255,51,51,0.2)',
              color: connectionStatus === 'ONLINE' ? '#00ffcc' : '#ff3333',
              border: `1px solid ${connectionStatus === 'ONLINE' ? '#00ffcc' : '#ff3333'}`,
            }}
          >
            {connectionStatus}
          </span>
        </div>

        <p style={{ margin: '4px 0', fontSize: '0.9rem', color: '#e0e0e0' }}>
          Simulation Time: <strong style={{ color: '#00ffcc' }}>T+{twinState.time} ticks</strong>
        </p>
        <p style={{ margin: '4px 0', fontSize: '0.9rem', color: '#e0e0e0' }}>
          Active Apron/Runway Traffic: <strong style={{ color: '#00ffcc' }}>{twinState.flights.length} flights</strong>
        </p>

        <hr style={{ borderColor: 'rgba(0, 255, 204, 0.3)', margin: '14px 0' }} />

        <div style={{ maxHeight: '240px', overflowY: 'auto' }}>
          {twinState.flights.length === 0 ? (
            <div style={{ color: '#888', fontStyle: 'italic', fontSize: '0.85rem' }}>Waiting for flight telemetry...</div>
          ) : (
            twinState.flights.map((f) => (
              <div
                key={f.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  margin: '4px 0',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  background: f.risk > 0.7 ? 'rgba(255, 51, 51, 0.15)' : 'rgba(0, 255, 204, 0.05)',
                  color: f.risk > 0.7 ? '#ff5555' : '#ffffff',
                  fontSize: '0.85rem',
                }}
              >
                <span><strong>{f.id}</strong> | {f.status.toUpperCase()}</span>
                <span>Risk: <strong>{f.risk.toFixed(2)}</strong></span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* 3D WebGL Canvas */}
      <Canvas shadows camera={{ position: [-40, 30, 40], fov: 50 }}>
        <Sky sunPosition={[100, 20, 100]} />
        <ambientLight intensity={0.5} />
        <directionalLight
          position={[50, 50, 20]}
          castShadow
          intensity={1.5}
          shadow-mapSize-width={2048}
          shadow-mapSize-height={2048}
        />

        {/* VABO Tarmac / Ground */}
        <Plane args={[200, 200]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
          <meshStandardMaterial color="#1a1a1a" roughness={0.8} />
        </Plane>

        {/* Runway 04/22 Indicator */}
        <Plane
          args={[140, 4]}
          rotation={[-Math.PI / 2, 0, Math.PI / 4]}
          position={[0, 0.1, 0]}
          receiveShadow
        >
          <meshStandardMaterial color="#333333" roughness={0.6} />
        </Plane>

        {/* Dynamic Aircraft */}
        {twinState.flights.map((flight) => (
          <Aircraft key={flight.id} data={flight} />
        ))}

        <OrbitControls makeDefault maxPolarAngle={Math.PI / 2.1} />
      </Canvas>
    </div>
  );
}
