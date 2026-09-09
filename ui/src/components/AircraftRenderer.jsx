import React, { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { useGLTF, Text, Box, Cylinder, Sphere } from '@react-three/drei';
import * as THREE from 'three';

/**
 * Procedural Detailed Twin-Engine Commercial Jet Model
 */
function DefaultAirplaneMesh({ isHighRisk }) {
  const strobeRef = useRef();

  useFrame(({ clock }) => {
    if (strobeRef.current) {
      // Flash strobe every 1 second
      const flash = Math.sin(clock.getElapsedTime() * 8) > 0.7;
      strobeRef.current.intensity = flash ? 3.0 : 0.0;
    }
  });

  const hullColor = isHighRisk ? '#ef4444' : '#0284c7'; // Red vs Indigo Cyan

  return (
    <group scale={0.75}>
      {/* 1. Main Cylindrical Fuselage */}
      <Cylinder
        args={[1.2, 1.2, 16, 20]}
        rotation={[Math.PI / 2, 0, 0]}
        position={[0, 1.4, 0]}
        castShadow
      >
        <meshStandardMaterial color="#f8fafc" metalness={0.4} roughness={0.25} />
      </Cylinder>

      {/* Aerodynamic Tapered Nose Cone */}
      <Cylinder
        args={[0.2, 1.2, 3.2, 20]}
        rotation={[Math.PI / 2, 0, 0]}
        position={[0, 1.35, 9.5]}
        castShadow
      >
        <meshStandardMaterial color="#f8fafc" metalness={0.4} roughness={0.25} />
      </Cylinder>

      {/* Cockpit Windshield */}
      <Box args={[1.5, 0.6, 1.2]} position={[0, 2.0, 8.8]} rotation={[-0.35, 0, 0]}>
        <meshStandardMaterial color="#0f172a" roughness={0.1} metalness={0.9} />
      </Box>

      {/* Airline Livery Stripe */}
      <Cylinder
        args={[1.22, 1.22, 10, 20]}
        rotation={[Math.PI / 2, 0, 0]}
        position={[0, 1.4, 0]}
      >
        <meshStandardMaterial color={hullColor} metalness={0.5} roughness={0.3} />
      </Cylinder>

      {/* 2. Main Swept Wings */}
      <group position={[0, 1.0, 0.5]}>
        {/* Left Wing */}
        <mesh position={[-6.5, 0, -1]} rotation={[0.08, -0.3, 0]} castShadow>
          <boxGeometry args={[11, 0.25, 2.8]} />
          <meshStandardMaterial color="#e2e8f0" metalness={0.3} roughness={0.4} />
        </mesh>
        {/* Left Winglet */}
        <mesh position={[-11.8, 0.8, -2.2]} rotation={[0, 0, 0.4]}>
          <boxGeometry args={[0.15, 1.6, 1.2]} />
          <meshStandardMaterial color={hullColor} />
        </mesh>
        {/* Port Navigation Light (Red) */}
        <mesh position={[-11.9, 0.2, -1.8]}>
          <sphereGeometry args={[0.15, 8, 8]} />
          <meshStandardMaterial color="#ef4444" emissive="#ef4444" emissiveIntensity={2.5} />
        </mesh>

        {/* Right Wing */}
        <mesh position={[6.5, 0, -1]} rotation={[0.08, 0.3, 0]} castShadow>
          <boxGeometry args={[11, 0.25, 2.8]} />
          <meshStandardMaterial color="#e2e8f0" metalness={0.3} roughness={0.4} />
        </mesh>
        {/* Right Winglet */}
        <mesh position={[11.8, 0.8, -2.2]} rotation={[0, 0, -0.4]}>
          <boxGeometry args={[0.15, 1.6, 1.2]} />
          <meshStandardMaterial color={hullColor} />
        </mesh>
        {/* Starboard Navigation Light (Green) */}
        <mesh position={[11.9, 0.2, -1.8]}>
          <sphereGeometry args={[0.15, 8, 8]} />
          <meshStandardMaterial color="#22c55e" emissive="#22c55e" emissiveIntensity={2.5} />
        </mesh>

        {/* 3. Under-Wing Turbofan Jet Engines */}
        {[-3.6, 3.6].map((xOffset, i) => (
          <group key={`engine-${i}`} position={[xOffset, -0.8, 0.5]}>
            <Cylinder args={[0.8, 0.75, 3.2, 16]} rotation={[Math.PI / 2, 0, 0]} castShadow>
              <meshStandardMaterial color="#94a3b8" metalness={0.7} roughness={0.3} />
            </Cylinder>
            {/* Front Fan Intake Spinner */}
            <mesh position={[0, 0, 1.6]}>
              <sphereGeometry args={[0.4, 12, 12]} />
              <meshStandardMaterial color="#0f172a" metalness={0.9} />
            </mesh>
            {/* Jet Pylon to Wing */}
            <Box args={[0.2, 0.8, 1.8]} position={[0, 0.6, 0]}>
              <meshStandardMaterial color="#64748b" />
            </Box>
          </group>
        ))}
      </group>

      {/* 4. Swept Vertical Stabilizer (Tail Fin) */}
      <group position={[0, 3.6, -7]}>
        <mesh rotation={[-0.45, 0, 0]} castShadow>
          <boxGeometry args={[0.2, 4.5, 3.2]} />
          <meshStandardMaterial color={hullColor} metalness={0.3} />
        </mesh>
        {/* Flashing White Strobe on Top of Fin */}
        <pointLight ref={strobeRef} position={[0, 2.5, -0.6]} color="#ffffff" distance={20} />
      </group>

      {/* 5. Horizontal Tail Stabilizers */}
      <group position={[0, 1.8, -7.5]}>
        <mesh rotation={[0, -0.2, 0]} position={[-2.8, 0, 0]} castShadow>
          <boxGeometry args={[5, 0.15, 1.8]} />
          <meshStandardMaterial color="#cbd5e1" />
        </mesh>
        <mesh rotation={[0, 0.2, 0]} position={[2.8, 0, 0]} castShadow>
          <boxGeometry args={[5, 0.15, 1.8]} />
          <meshStandardMaterial color="#cbd5e1" />
        </mesh>
      </group>

      {/* 6. Landing Gear Wheels */}
      {/* Nose Gear */}
      <group position={[0, 0.3, 7.5]}>
        <Cylinder args={[0.08, 0.08, 1.2]} position={[0, 0.5, 0]}>
          <meshStandardMaterial color="#475569" />
        </Cylinder>
        <Cylinder args={[0.3, 0.3, 0.25]} rotation={[0, 0, Math.PI / 2]}>
          <meshStandardMaterial color="#111" />
        </Cylinder>
      </group>
      {/* Main Left Gear */}
      <group position={[-2.2, 0.3, -0.5]}>
        <Cylinder args={[0.1, 0.1, 1.2]} position={[0, 0.5, 0]}>
          <meshStandardMaterial color="#475569" />
        </Cylinder>
        <Cylinder args={[0.4, 0.4, 0.35]} rotation={[0, 0, Math.PI / 2]}>
          <meshStandardMaterial color="#111" />
        </Cylinder>
      </group>
      {/* Main Right Gear */}
      <group position={[2.2, 0.3, -0.5]}>
        <Cylinder args={[0.1, 0.1, 1.2]} position={[0, 0.5, 0]}>
          <meshStandardMaterial color="#475569" />
        </Cylinder>
        <Cylinder args={[0.4, 0.4, 0.35]} rotation={[0, 0, Math.PI / 2]}>
          <meshStandardMaterial color="#111" />
        </Cylinder>
      </group>
    </group>
  );
}

/**
 * Custom Uploaded GLB Loader Component
 */
function CustomGLBModel({ url }) {
  const { scene } = useGLTF(url);
  const cloned = useMemo(() => {
    const c = scene.clone();
    // Auto-normalize bounding box scale
    const box = new THREE.Box3().setFromObject(c);
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    if (maxDim > 0) {
      const targetScale = 14 / maxDim; // Normalize to ~14 units
      c.scale.set(targetScale, targetScale, targetScale);
    }
    c.traverse((node) => {
      if (node.isMesh) {
        node.castShadow = true;
        node.receiveShadow = true;
      }
    });
    return c;
  }, [scene]);

  return <primitive object={cloned} />;
}

/**
 * Aircraft Renderer with Smooth Lerp Interpolation & Floating Telemetry HUD
 */
export default function AircraftRenderer({ data, customModelUrl, isPrimary, onPositionUpdate }) {
  const groupRef = useRef();
  const currentPos = useRef(new THREE.Vector3(data.x, data.y, data.z));
  const currentHeading = useRef(data.heading || 0);
  const currentPitch = useRef(data.pitch || 0);
  const currentRoll = useRef(data.roll || 0);

  useFrame((_, delta) => {
    if (!groupRef.current) return;

    // Smooth position lerp (10x delta for fluid 60fps tracking)
    const targetPos = new THREE.Vector3(data.x, data.y, data.z);
    currentPos.current.lerp(targetPos, Math.min(1, delta * 12));
    groupRef.current.position.copy(currentPos.current);

    // Smooth angular rotations
    currentHeading.current = THREE.MathUtils.lerp(currentHeading.current, data.heading || 0, delta * 10);
    currentPitch.current = THREE.MathUtils.lerp(currentPitch.current, data.pitch || 0, delta * 8);
    currentRoll.current = THREE.MathUtils.lerp(currentRoll.current, data.roll || 0, delta * 8);

    // Apply rotations: heading around Y, pitch around X (nose up), roll around Z
    groupRef.current.rotation.set(currentPitch.current, currentHeading.current, currentRoll.current, 'YXZ');

    // Notify camera if this is the primary tracked aircraft
    if (isPrimary && onPositionUpdate) {
      onPositionUpdate(currentPos.current, currentHeading.current);
    }
  });

  const isHighRisk = (data.risk || 0) > 0.7;

  return (
    <group ref={groupRef}>
      {/* 3D Model: Either Custom Uploaded GLB or High-Detail Default Jet */}
      {customModelUrl ? (
        <CustomGLBModel url={customModelUrl} />
      ) : (
        <DefaultAirplaneMesh isHighRisk={isHighRisk} />
      )}

      {/* Floating 3D Telemetry HUD Label */}
      <group position={[0, 4.2, 0]}>
        {/* Background Tag */}
        <Box args={[7.2, 1.4, 0.1]} position={[0, 0, 0]}>
          <meshBasicMaterial color="#0f172a" transparent opacity={0.85} />
        </Box>
        {/* Flight ID and Status */}
        <Text
          position={[0, 0.3, 0.1]}
          fontSize={0.65}
          color={isHighRisk ? '#f87171' : '#38bdf8'}
          anchorX="center"
          anchorY="middle"
        >
          {`${data.id} • ${data.status.toUpperCase()}`}
        </Text>
        {/* Speed and Altitude */}
        <Text
          position={[0, -0.3, 0.1]}
          fontSize={0.48}
          color="#f8fafc"
          anchorX="center"
          anchorY="middle"
        >
          {`ALT: ${data.altitude || 0} FT • SPD: ${data.speed || 0} KT`}
        </Text>
      </group>
    </group>
  );
}
