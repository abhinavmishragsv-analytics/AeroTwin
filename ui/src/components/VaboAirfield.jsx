import React, { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Box, Cylinder, Plane, Text } from '@react-three/drei';
import * as THREE from 'three';

/**
 * 3D Architectural Model of Vadodara Airport (VABO)
 * - Integrated Terminal with curved aerodynamic roof canopy & aerobridges
 * - Air Traffic Control (ATC) Tower with rotating radar
 * - Runway 04/22 with piano keys, numerals, centerline, and runway edge lighting
 * - Taxiway Alpha, Bravo & holding point markings
 * - 6 Aircraft Apron Parking Stands with Ground Service Equipment
 * - Maintenance Hangars, Fire Station, and Windsock
 */
export default function VaboAirfield() {
  const radarRef = useRef();
  const windsockRef = useRef();

  useFrame((_, delta) => {
    if (radarRef.current) {
      radarRef.current.rotation.y += delta * 2.5;
    }
    if (windsockRef.current) {
      windsockRef.current.rotation.y = Math.sin(Date.now() * 0.001) * 0.15 + Math.PI / 4;
    }
  });

  // Runway Edge Lights (aligned along 45° angle)
  const runwayLights = useMemo(() => {
    const lights = [];
    const angle = Math.PI / 4;
    const halfWidth = 7.5;
    // Runway spans roughly from (-110, -110) to (110, 110)
    for (let d = -110; d <= 110; d += 10) {
      const cx = d * Math.sin(angle);
      const cz = d * Math.cos(angle);
      // Left edge
      lights.push({
        x: cx - halfWidth * Math.cos(angle),
        z: cz + halfWidth * Math.sin(angle),
        color: '#fffae0'
      });
      // Right edge
      lights.push({
        x: cx + halfWidth * Math.cos(angle),
        z: cz - halfWidth * Math.sin(angle),
        color: '#fffae0'
      });
    }
    return lights;
  }, []);

  return (
    <group>
      {/* 1. Surrounding Grass Terrain */}
      <Plane args={[450, 450]} rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.05, 0]} receiveShadow>
        <meshStandardMaterial color="#2d4026" roughness={0.9} />
      </Plane>

      {/* 2. Concrete Apron / Airfield Pavement */}
      <Plane
        args={[100, 75]}
        rotation={[-Math.PI / 2, 0, 0]}
        position={[-35, 0.01, -20]}
        receiveShadow
      >
        <meshStandardMaterial color="#3b3f42" roughness={0.7} />
      </Plane>

      {/* 3. RUNWAY 04/22 (Length: 250m, Width: 15m, Heading: 45°) */}
      <group position={[0, 0.02, 0]} rotation={[0, -Math.PI / 4, 0]}>
        {/* Asphalt Runway Surface */}
        <Box args={[15, 0.05, 250]} receiveShadow>
          <meshStandardMaterial color="#1f2326" roughness={0.85} />
        </Box>

        {/* Runway Centerline Dashes */}
        {Array.from({ length: 22 }).map((_, i) => (
          <Plane
            key={`centerline-${i}`}
            args={[0.8, 5]}
            rotation={[-Math.PI / 2, 0, 0]}
            position={[0, 0.06, -100 + i * 10]}
          >
            <meshBasicMaterial color="#ffffff" />
          </Plane>
        ))}

        {/* Threshold 04 Piano Keys */}
        <group position={[0, 0.06, -112]}>
          {[-5, -3.5, -2, -0.5, 1, 2.5, 4, 5.5].map((x, i) => (
            <Plane key={`piano-04-${i}`} args={[0.9, 10]} rotation={[-Math.PI / 2, 0, 0]} position={[x, 0, 0]}>
              <meshBasicMaterial color="#ffffff" />
            </Plane>
          ))}
          {/* Numeral "04" */}
          <Text
            rotation={[-Math.PI / 2, 0, 0]}
            position={[0, 0.01, 14]}
            fontSize={5}
            color="#ffffff"
            anchorX="center"
            anchorY="middle"
          >
            04
          </Text>
        </group>

        {/* Threshold 22 Piano Keys */}
        <group position={[0, 0.06, 112]}>
          {[-5, -3.5, -2, -0.5, 1, 2.5, 4, 5.5].map((x, i) => (
            <Plane key={`piano-22-${i}`} args={[0.9, 10]} rotation={[-Math.PI / 2, 0, 0]} position={[x, 0, 0]}>
              <meshBasicMaterial color="#ffffff" />
            </Plane>
          ))}
          {/* Numeral "22" */}
          <Text
            rotation={[-Math.PI / 2, 0, Math.PI]}
            position={[0, 0.01, -14]}
            fontSize={5}
            color="#ffffff"
            anchorX="center"
            anchorY="middle"
          >
            22
          </Text>
        </group>

        {/* Touchdown Zone Aiming Markings */}
        <Plane args={[2.5, 16]} rotation={[-Math.PI / 2, 0, 0]} position={[-3.5, 0.06, -70]}>
          <meshBasicMaterial color="#ffffff" />
        </Plane>
        <Plane args={[2.5, 16]} rotation={[-Math.PI / 2, 0, 0]} position={[3.5, 0.06, -70]}>
          <meshBasicMaterial color="#ffffff" />
        </Plane>
        <Plane args={[2.5, 16]} rotation={[-Math.PI / 2, 0, 0]} position={[-3.5, 0.06, 70]}>
          <meshBasicMaterial color="#ffffff" />
        </Plane>
        <Plane args={[2.5, 16]} rotation={[-Math.PI / 2, 0, 0]} position={[3.5, 0.06, 70]}>
          <meshBasicMaterial color="#ffffff" />
        </Plane>
      </group>

      {/* 4. Runway Edge Lights */}
      {runwayLights.map((l, idx) => (
        <group key={`rw-light-${idx}`} position={[l.x, 0.2, l.z]}>
          <Cylinder args={[0.1, 0.1, 0.4]} position={[0, 0.2, 0]}>
            <meshStandardMaterial color="#444" />
          </Cylinder>
          <mesh position={[0, 0.4, 0]}>
            <sphereGeometry args={[0.18, 8, 8]} />
            <meshStandardMaterial color={l.color} emissive={l.color} emissiveIntensity={1.8} />
          </mesh>
        </group>
      ))}

      {/* 5. TAXIWAY ALPHA (Connecting Apron to Runway 04 Threshold) */}
      <group>
        {/* Taxiway Pavement */}
        <Box args={[14, 0.04, 85]} position={[-60, 0.02, -60]} rotation={[0, -Math.PI / 4, 0]} receiveShadow>
          <meshStandardMaterial color="#282c30" roughness={0.8} />
        </Box>
        {/* Yellow Taxiway Centerline */}
        <Plane args={[0.5, 82]} rotation={[-Math.PI / 2, 0, -Math.PI / 4]} position={[-60, 0.06, -60]}>
          <meshBasicMaterial color="#fcd34d" />
        </Plane>

        {/* Runway 04 Holding Position Line (Double Solid, Double Dashed) */}
        <group position={[-78, 0.07, -78]} rotation={[0, Math.PI / 4, 0]}>
          <Plane args={[14, 0.4]} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, -0.6]}>
            <meshBasicMaterial color="#ef4444" />
          </Plane>
          <Plane args={[14, 0.4]} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0.6]}>
            <meshBasicMaterial color="#fcd34d" />
          </Plane>
        </group>
      </group>

      {/* 6. VADODARA INTEGRATED TERMINAL BUILDING */}
      <group position={[-35, 0, 15]}>
        {/* Main Concourse Structure */}
        <Box args={[70, 7, 22]} position={[0, 3.5, 0]} castShadow receiveShadow>
          <meshStandardMaterial color="#d1d5db" metalness={0.3} roughness={0.4} />
        </Box>

        {/* Iconic Sweeping Curved Aerodynamic Canopy Roof (VABO Style) */}
        <Cylinder
          args={[26, 26, 76, 32, 1, false, 0, Math.PI]}
          position={[0, 7.8, -2]}
          rotation={[0, 0, Math.PI / 2]}
          scale={[0.25, 1, 1]}
          castShadow
        >
          <meshStandardMaterial color="#0f766e" metalness={0.6} roughness={0.3} />
        </Cylinder>

        {/* Large Glass Curtain Facade */}
        <Box args={[66, 5, 0.5]} position={[0, 3.5, -11.2]}>
          <meshStandardMaterial
            color="#38bdf8"
            transparent
            opacity={0.65}
            roughness={0.1}
            metalness={0.9}
          />
        </Box>

        {/* Terminal Signage: "VADODARA AIRPORT" */}
        <Text
          position={[0, 7.5, -11.5]}
          fontSize={1.8}
          color="#f8fafc"
          anchorX="center"
          anchorY="middle"
        >
          VADODARA AIRPORT (VABO)
        </Text>

        {/* Aerobridge / Jet Bridge 1 (Serving Stand 1) */}
        <group position={[15, 0, -11]}>
          <Box args={[2.8, 3, 14]} position={[0, 2.8, -7]} castShadow>
            <meshStandardMaterial color="#94a3b8" metalness={0.4} />
          </Box>
          <Cylinder args={[0.4, 0.4, 3]} position={[-1, 1.5, -13]} castShadow>
            <meshStandardMaterial color="#475569" />
          </Cylinder>
          <Cylinder args={[0.4, 0.4, 3]} position={[1, 1.5, -13]} castShadow>
            <meshStandardMaterial color="#475569" />
          </Cylinder>
          {/* Rotunda */}
          <Cylinder args={[1.6, 1.6, 3.2]} position={[0, 2.8, -14]}>
            <meshStandardMaterial color="#64748b" />
          </Cylinder>
        </group>

        {/* Aerobridge / Jet Bridge 2 (Serving Stand 2) */}
        <group position={[-15, 0, -11]}>
          <Box args={[2.8, 3, 14]} position={[0, 2.8, -7]} castShadow>
            <meshStandardMaterial color="#94a3b8" metalness={0.4} />
          </Box>
          <Cylinder args={[0.4, 0.4, 3]} position={[-1, 1.5, -13]} castShadow>
            <meshStandardMaterial color="#475569" />
          </Cylinder>
          <Cylinder args={[0.4, 0.4, 3]} position={[1, 1.5, -13]} castShadow>
            <meshStandardMaterial color="#475569" />
          </Cylinder>
          <Cylinder args={[1.6, 1.6, 3.2]} position={[0, 2.8, -14]}>
            <meshStandardMaterial color="#64748b" />
          </Cylinder>
        </group>

        {/* Landside Vehicle Drop-off Canopy */}
        <Box args={[72, 0.6, 10]} position={[0, 5, 14]} castShadow>
          <meshStandardMaterial color="#334155" />
        </Box>
        {[-30, -10, 10, 30].map((x, idx) => (
          <Cylinder key={`col-${idx}`} args={[0.3, 0.3, 5]} position={[x, 2.5, 18]} castShadow>
            <meshStandardMaterial color="#94a3b8" />
          </Cylinder>
        ))}
      </group>

      {/* 7. AIR TRAFFIC CONTROL (ATC) TOWER */}
      <group position={[-75, 0, 10]}>
        {/* Tower Concrete Shaft */}
        <Cylinder args={[3, 4, 28, 8]} position={[0, 14, 0]} castShadow receiveShadow>
          <meshStandardMaterial color="#e2e8f0" roughness={0.6} />
        </Cylinder>
        {/* Upper Cab Support Ring */}
        <Cylinder args={[5, 3.2, 3, 12]} position={[0, 28.5, 0]} castShadow>
          <meshStandardMaterial color="#475569" />
        </Cylinder>
        {/* 360-degree Glass Cab */}
        <Cylinder args={[4.8, 4.8, 3.5, 12]} position={[0, 31, 0]}>
          <meshStandardMaterial color="#0284c7" transparent opacity={0.7} roughness={0.1} />
        </Cylinder>
        {/* Roof Dome */}
        <Cylinder args={[5.2, 5, 0.8, 12]} position={[0, 33, 0]} castShadow>
          <meshStandardMaterial color="#1e293b" />
        </Cylinder>
        {/* Rotating Radar Scanner */}
        <group ref={radarRef} position={[0, 34, 0]}>
          <Cylinder args={[0.15, 0.15, 2]} position={[0, 1, 0]}>
            <meshStandardMaterial color="#94a3b8" />
          </Cylinder>
          <Box args={[3.2, 0.7, 0.2]} position={[0, 2.2, 0]}>
            <meshStandardMaterial color="#ef4444" />
          </Box>
        </group>
        {/* Tower Label */}
        <Text position={[0, 24, 4.2]} fontSize={1.4} color="#1e293b" anchorX="center">
          VABO TOWER
        </Text>
      </group>

      {/* 8. APRON PARKING STANDS (Stands 1 - 4) */}
      {[
        { id: 1, pos: [-30, 0.03, -15] },
        { id: 2, pos: [-48, 0.03, -15] },
        { id: 3, pos: [-12, 0.03, -15] },
        { id: 4, pos: [-65, 0.03, -15] }
      ].map((stand) => (
        <group key={`stand-${stand.id}`} position={stand.pos}>
          {/* Yellow Lead-in Taxi Guideline */}
          <Plane args={[0.4, 26]} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, -3]}>
            <meshBasicMaterial color="#fcd34d" />
          </Plane>
          {/* Stand Stop Bar */}
          <Plane args={[5, 0.4]} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 3]}>
            <meshBasicMaterial color="#ef4444" />
          </Plane>
          {/* Stand Number Decal */}
          <Text
            rotation={[-Math.PI / 2, 0, 0]}
            position={[0, 0.03, 5]}
            fontSize={2.2}
            color="#fcd34d"
            anchorX="center"
          >
            {`STAND ${stand.id}`}
          </Text>
        </group>
      ))}

      {/* 9. GROUND SERVICE EQUIPMENT (GSE) on Apron */}
      {/* Pushback Tug */}
      <group position={[-30, 0.5, -9]} rotation={[0, Math.PI, 0]}>
        <Box args={[2.4, 1, 3.8]} position={[0, 0.5, 0]} castShadow>
          <meshStandardMaterial color="#eab308" roughness={0.4} />
        </Box>
        <Box args={[2.2, 0.8, 1.4]} position={[0, 1.2, -0.4]} castShadow>
          <meshStandardMaterial color="#1e293b" />
        </Box>
        {/* Wheels */}
        {[-1.2, 1.2].map((x, i) =>
          [-1.2, 1.2].map((z, j) => (
            <Cylinder key={`tug-w-${i}-${j}`} args={[0.4, 0.4, 0.4]} position={[x, 0.1, z]} rotation={[0, 0, Math.PI / 2]}>
              <meshStandardMaterial color="#111" />
            </Cylinder>
          ))
        )}
      </group>

      {/* Fuel Tanker Truck */}
      <group position={[-20, 0.8, -18]} rotation={[0, -Math.PI / 3, 0]}>
        <Box args={[2.2, 1.8, 7]} position={[0, 1, 0]} castShadow>
          <meshStandardMaterial color="#ffffff" metalness={0.3} />
        </Box>
        <Cylinder args={[1.1, 1.1, 4.5]} position={[0, 1.4, -0.8]} rotation={[Math.PI / 2, 0, 0]} castShadow>
          <meshStandardMaterial color="#ffffff" metalness={0.4} />
        </Cylinder>
        <Text position={[1.15, 1.4, -0.8]} rotation={[0, Math.PI / 2, 0]} fontSize={0.6} color="#ef4444">
          AVIATION FUEL
        </Text>
      </group>

      {/* 10. MAINTENANCE HANGAR COMPLEX */}
      <group position={[30, 0, -45]} rotation={[0, -Math.PI / 4, 0]}>
        <Box args={[34, 12, 28]} position={[0, 6, 0]} castShadow receiveShadow>
          <meshStandardMaterial color="#64748b" metalness={0.5} roughness={0.4} />
        </Box>
        {/* Arched Roof */}
        <Cylinder
          args={[17, 17, 28, 24, 1, false, 0, Math.PI]}
          position={[0, 12, 0]}
          rotation={[0, 0, Math.PI / 2]}
          scale={[0.3, 1, 1]}
          castShadow
        >
          <meshStandardMaterial color="#334155" metalness={0.7} roughness={0.3} />
        </Cylinder>
        {/* Large Hangar Accordion Doors */}
        <Box args={[28, 9, 0.5]} position={[0, 4.5, 14.2]}>
          <meshStandardMaterial color="#cbd5e1" metalness={0.4} roughness={0.3} />
        </Box>
        <Text position={[0, 10.5, 14.5]} fontSize={1.6} color="#f8fafc" anchorX="center">
          VABO AIRCRAFT MAINTENANCE
        </Text>
      </group>

      {/* 11. WINDSOCK */}
      <group ref={windsockRef} position={[-65, 0, -110]}>
        <Cylinder args={[0.1, 0.15, 7]} position={[0, 3.5, 0]} castShadow>
          <meshStandardMaterial color="#cbd5e1" />
        </Cylinder>
        <Cylinder args={[0.5, 0.2, 2.5]} position={[0, 6.8, 1]} rotation={[Math.PI / 2, 0, 0]}>
          <meshStandardMaterial color="#ea580c" />
        </Cylinder>
      </group>
    </group>
  );
}
