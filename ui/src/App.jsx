import React, { useEffect, useState, useRef, useCallback } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Sky, PerspectiveCamera } from '@react-three/drei';
import * as THREE from 'three';
import VaboAirfield from './components/VaboAirfield';
import AircraftRenderer from './components/AircraftRenderer';

/**
 * Dynamic Multi-Mode Camera Controller
 */
function CameraRig({ mode, targetAircraftPos, targetHeading }) {
  const controlsRef = useRef();

  useFrame(({ camera }) => {
    if (mode === 'chase' && targetAircraftPos) {
      // Position camera 25 units behind and 9 units above aircraft along heading
      const heading = targetHeading || 0;
      const dist = 28;
      const height = 10;
      const camX = targetAircraftPos.x - Math.sin(heading) * dist;
      const camZ = targetAircraftPos.z - Math.cos(heading) * dist;
      const camY = targetAircraftPos.y + height;

      camera.position.lerp(new THREE.Vector3(camX, camY, camZ), 0.08);
      // Look slightly ahead of the aircraft
      const lookTarget = new THREE.Vector3(
        targetAircraftPos.x + Math.sin(heading) * 15,
        targetAircraftPos.y + 2,
        targetAircraftPos.z + Math.cos(heading) * 15
      );
      camera.lookAt(lookTarget);
    } else if (mode === 'tower') {
      // Look from VABO Tower Cab (-75, 31, 10) down Runway 04
      const towerPos = new THREE.Vector3(-75, 31, 10);
      camera.position.lerp(towerPos, 0.08);
      if (targetAircraftPos) {
        camera.lookAt(targetAircraftPos.x, targetAircraftPos.y, targetAircraftPos.z);
      } else {
        camera.lookAt(0, 5, 0);
      }
    } else if (mode === 'threshold') {
      // Low angle at Runway 04 threshold (-105, 3, -105)
      const threshPos = new THREE.Vector3(-105, 3, -105);
      camera.position.lerp(threshPos, 0.08);
      if (targetAircraftPos) {
        camera.lookAt(targetAircraftPos.x, targetAircraftPos.y, targetAircraftPos.z);
      } else {
        camera.lookAt(-50, 2, -50);
      }
    }
  });

  return (
    <OrbitControls
      ref={controlsRef}
      makeDefault
      enabled={mode === 'orbit'}
      maxPolarAngle={Math.PI / 2.05}
      minDistance={10}
      maxDistance={350}
    />
  );
}

export default function App() {
  const [twinState, setTwinState] = useState({ flights: [], time: 0 });
  const [connectionStatus, setConnectionStatus] = useState('CONNECTING');
  const [cameraMode, setCameraMode] = useState('orbit'); // 'orbit' | 'chase' | 'tower' | 'threshold'
  const [customModelUrl, setCustomModelUrl] = useState(null);
  const [customModelName, setCustomModelName] = useState(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const primaryAircraftPos = useRef(new THREE.Vector3(0, 0, 0));
  const primaryAircraftHeading = useRef(0);
  const fileInputRef = useRef(null);

  // WebSocket Live Simulation Stream
  useEffect(() => {
    let ws;
    let timer;

    const connect = () => {
      ws = new WebSocket('ws://localhost:8000/ws/twin');
      ws.onopen = () => setConnectionStatus('ONLINE');
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
      ws.onerror = () => ws.close();
    };

    connect();

    return () => {
      if (timer) clearTimeout(timer);
      if (ws) ws.close();
    };
  }, []);

  // Handle GLB File Upload via Input or Drop
  const handleFileUpload = useCallback((file) => {
    if (!file) return;
    if (file.name.endsWith('.glb') || file.name.endsWith('.gltf')) {
      const objectUrl = URL.createObjectURL(file);
      setCustomModelUrl(objectUrl);
      setCustomModelName(file.name);
    } else {
      alert('Please upload a 3D model with .glb or .gltf format.');
    }
  }, []);

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  };

  const handlePositionUpdate = useCallback((pos, heading) => {
    primaryAircraftPos.current.copy(pos);
    primaryAircraftHeading.current = heading;
  }, []);

  const primaryFlight = twinState.flights[0] || null;

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
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
    >
      {/* Hidden File Input for GLB Upload */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".glb,.gltf"
        style={{ display: 'none' }}
        onChange={(e) => {
          if (e.target.files && e.target.files[0]) {
            handleFileUpload(e.target.files[0]);
          }
        }}
      />

      {/* Drag & Drop Visual Indicator Overlay */}
      {isDragOver && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            zIndex: 50,
            background: 'rgba(2, 132, 199, 0.5)',
            border: '4px dashed #38bdf8',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            pointerEvents: 'none'
          }}
        >
          <div
            style={{
              background: '#0f172a',
              padding: '30px 50px',
              borderRadius: '16px',
              color: '#38bdf8',
              fontFamily: 'monospace',
              fontSize: '1.4rem',
              boxShadow: '0 20px 40px rgba(0,0,0,0.6)'
            }}
          >
            Drop your .GLB Aircraft model to spawn it!
          </div>
        </div>
      )}

      {/* TOP-LEFT: Main Airport HUD & Telemetry */}
      <div
        style={{
          position: 'absolute',
          top: 20,
          left: 20,
          zIndex: 10,
          background: 'rgba(15, 23, 42, 0.88)',
          backdropFilter: 'blur(12px)',
          border: '1px solid rgba(56, 189, 248, 0.3)',
          borderRadius: '14px',
          padding: '20px 24px',
          color: '#f8fafc',
          fontFamily: "'Inter', -apple-system, sans-serif",
          boxShadow: '0 12px 36px rgba(0, 0, 0, 0.6)',
          minWidth: '320px',
          maxWidth: '400px'
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, letterSpacing: '0.5px', color: '#38bdf8' }}>
              AEROTWIN • VABO
            </h2>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '2px' }}>
              Vadodara Airport 3D Digital Twin
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
          <div style={{ background: 'rgba(30, 41, 59, 0.6)', padding: '8px 12px', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>SIM TIME</div>
            <div style={{ fontSize: '1rem', fontWeight: 600, color: '#f8fafc' }}>T+{twinState.time}s</div>
          </div>
          <div style={{ background: 'rgba(30, 41, 59, 0.6)', padding: '8px 12px', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>ACTIVE TRAFFIC</div>
            <div style={{ fontSize: '1rem', fontWeight: 600, color: '#38bdf8' }}>{twinState.flights.length} Aircraft</div>
          </div>
        </div>

        {/* Active Flights List */}
        <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600, marginBottom: '6px' }}>
          AIRPORT TRAFFIC STREAM
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
                  background: f.risk > 0.7 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(15, 23, 42, 0.7)',
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
                  <div>{f.altitude || 0} ft • {f.speed || 0} kt</div>
                  <div style={{ color: f.risk > 0.7 ? '#f87171' : '#4ade80' }}>
                    Risk: {f.risk.toFixed(2)}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* TOP-RIGHT: GLB Upload & Model Customizer */}
      <div
        style={{
          position: 'absolute',
          top: 20,
          right: 20,
          zIndex: 10,
          background: 'rgba(15, 23, 42, 0.88)',
          backdropFilter: 'blur(12px)',
          border: '1px solid rgba(56, 189, 248, 0.3)',
          borderRadius: '14px',
          padding: '16px 20px',
          color: '#f8fafc',
          boxShadow: '0 12px 36px rgba(0, 0, 0, 0.6)',
          width: '280px'
        }}
      >
        <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#38bdf8', marginBottom: '8px' }}>
          3D AIRCRAFT MODEL
        </div>

        {customModelName ? (
          <div style={{ marginBottom: '12px' }}>
            <div style={{ fontSize: '0.8rem', color: '#4ade80', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>✓ Custom Active:</span>
              <strong style={{ color: '#f8fafc', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {customModelName}
              </strong>
            </div>
            <button
              onClick={() => {
                setCustomModelUrl(null);
                setCustomModelName(null);
              }}
              style={{
                marginTop: '6px',
                background: 'transparent',
                border: '1px solid rgba(239, 68, 68, 0.5)',
                color: '#f87171',
                borderRadius: '6px',
                padding: '4px 10px',
                fontSize: '0.75rem',
                cursor: 'pointer'
              }}
            >
              Reset to Default Twin Jet
            </button>
          </div>
        ) : (
          <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '12px', lineHeight: '1.4' }}>
            Currently using high-detail default passenger jet. You can upload any <strong>.glb</strong> or <strong>.gltf</strong> model.
          </div>
        )}

        <button
          onClick={() => fileInputRef.current && fileInputRef.current.click()}
          style={{
            width: '100%',
            background: 'linear-gradient(135deg, #0284c7 0%, #0369a1 100%)',
            border: 'none',
            color: '#ffffff',
            borderRadius: '8px',
            padding: '10px 14px',
            fontWeight: 600,
            fontSize: '0.85rem',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            boxShadow: '0 4px 12px rgba(2, 132, 199, 0.4)'
          }}
        >
          <span>📁</span>
          <span>{customModelName ? 'Swap .GLB Model' : 'Upload Airplane (.glb)'}</span>
        </button>
        <div style={{ fontSize: '0.7rem', color: '#64748b', textAlign: 'center', marginTop: '6px' }}>
          or drag & drop file anywhere on screen
        </div>
      </div>

      {/* BOTTOM-CENTER: Cinematic Camera Mode Switcher */}
      <div
        style={{
          position: 'absolute',
          bottom: 24,
          left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 10,
          background: 'rgba(15, 23, 42, 0.92)',
          backdropFilter: 'blur(16px)',
          border: '1px solid rgba(56, 189, 248, 0.3)',
          borderRadius: '30px',
          padding: '6px 10px',
          display: 'flex',
          gap: '8px',
          boxShadow: '0 12px 36px rgba(0, 0, 0, 0.6)'
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

      {/* 3D WebGL Canvas */}
      <Canvas shadows camera={{ position: [-80, 50, 80], fov: 48 }}>
        <PerspectiveCamera makeDefault position={[-80, 50, 80]} fov={48} />
        
        {/* Dynamic Sky and Lighting */}
        <Sky
          distance={450000}
          sunPosition={[120, 45, 120]}
          inclination={0.49}
          azimuth={0.25}
          turbidity={8}
          rayleigh={2}
        />
        <ambientLight intensity={0.65} />
        <hemisphereLight skyColor="#bae6fd" groundColor="#334155" intensity={0.4} />
        <directionalLight
          position={[100, 120, 80]}
          intensity={1.6}
          castShadow
          shadow-mapSize-width={2048}
          shadow-mapSize-height={2048}
          shadow-camera-far={400}
          shadow-camera-left={-150}
          shadow-camera-right={150}
          shadow-camera-top={150}
          shadow-camera-bottom={-150}
          shadow-bias={-0.0001}
        />

        {/* Realistic Distance Fog */}
        <fogExp2 attach="fog" args={['#0f172a', 0.0022]} />

        {/* Vadodara Airport (VABO) 3D Airfield Architecture */}
        <VaboAirfield />

        {/* Active Aircraft with Flight Dynamics & Uploaded GLB Support */}
        {twinState.flights.map((flight, idx) => (
          <AircraftRenderer
            key={flight.id}
            data={flight}
            customModelUrl={customModelUrl}
            isPrimary={idx === 0}
            onPositionUpdate={idx === 0 ? handlePositionUpdate : null}
          />
        ))}

        {/* Camera Rig (Orbit, Chase, Tower, Runway Threshold) */}
        <CameraRig
          mode={cameraMode}
          targetAircraftPos={primaryFlight ? primaryAircraftPos.current : null}
          targetHeading={primaryFlight ? primaryAircraftHeading.current : null}
        />
      </Canvas>
    </div>
  );
}
