import json
import struct
import numpy as np
import os

# Create a detailed, multi-colored low-poly commercial jet
# Coordinates: +X is Right Wing, -X is Left Wing, +Y is Up, +Z is Nose, -Z is Tail
vertices = []
normals = []
colors = []
indices = []

def add_box(center, size, color_rgb):
    cx, cy, cz = center
    dx, dy, dz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    start_idx = len(vertices)

    corners = [
        # Front face (+Z)
        (cx - dx, cy - dy, cz + dz), (cx + dx, cy - dy, cz + dz),
        (cx + dx, cy + dy, cz + dz), (cx - dx, cy + dy, cz + dz),
        # Back face (-Z)
        (cx + dx, cy - dy, cz - dz), (cx - dx, cy - dy, cz - dz),
        (cx - dx, cy + dy, cz - dz), (cx + dx, cy + dy, cz - dz),
        # Top face (+Y)
        (cx - dx, cy + dy, cz + dz), (cx + dx, cy + dy, cz + dz),
        (cx + dx, cy + dy, cz - dz), (cx - dx, cy + dy, cz - dz),
        # Bottom face (-Y)
        (cx - dx, cy - dy, cz - dz), (cx + dx, cy - dy, cz - dz),
        (cx + dx, cy - dy, cz + dz), (cx - dx, cy - dy, cz + dz),
        # Right face (+X)
        (cx + dx, cy - dy, cz + dz), (cx + dx, cy - dy, cz - dz),
        (cx + dx, cy + dy, cz - dz), (cx + dx, cy + dy, cz + dz),
        # Left face (-X)
        (cx - dx, cy - dy, cz - dz), (cx - dx, cy - dy, cz + dz),
        (cx - dx, cy + dy, cz + dz), (cx - dx, cy + dy, cz - dz)
    ]

    face_normals = [
        (0, 0, 1), (0, 0, 1), (0, 0, 1), (0, 0, 1),
        (0, 0, -1), (0, 0, -1), (0, 0, -1), (0, 0, -1),
        (0, 1, 0), (0, 1, 0), (0, 1, 0), (0, 1, 0),
        (0, -1, 0), (0, -1, 0), (0, -1, 0), (0, -1, 0),
        (1, 0, 0), (1, 0, 0), (1, 0, 0), (1, 0, 0),
        (-1, 0, 0), (-1, 0, 0), (-1, 0, 0), (-1, 0, 0)
    ]

    r, g, b = color_rgb
    for c, n in zip(corners, face_normals):
        vertices.append(c)
        normals.append(n)
        colors.append((r, g, b, 1.0))

    for face in range(6):
        base = start_idx + face * 4
        indices.append((base, base + 1, base + 2))
        indices.append((base, base + 2, base + 3))

WHITE = (0.95, 0.96, 0.98)
BLUE = (0.05, 0.45, 0.85)
DARK = (0.12, 0.15, 0.20)
SILVER = (0.75, 0.78, 0.82)
RED = (0.9, 0.15, 0.15)
GREEN = (0.15, 0.85, 0.25)

# 1. Fuselage (White Passenger Tube)
add_box((0, 1.2, 0), (2.0, 2.0, 22.0), WHITE)
# Blue belly & livery accent
add_box((0, 0.3, 0), (2.05, 0.6, 22.1), BLUE)

# 2. Nose Cone (Aerodynamic taper)
add_box((0, 1.0, 12.0), (1.6, 1.5, 2.5), WHITE)
add_box((0, 0.9, 13.8), (0.9, 0.9, 1.5), DARK) # Radome tip

# 3. Cockpit Windshield (Dark Glass)
add_box((0, 1.8, 11.2), (1.8, 0.6, 1.4), DARK)

# 4. Main Swept Wings (Span 26m)
# Left Wing
add_box((-7.5, 0.8, -1.0), (13.0, 0.35, 3.8), SILVER)
# Left Winglet (Blue)
add_box((-14.2, 1.8, -1.8), (0.2, 2.2, 1.6), BLUE)
# Port Nav Light (Red)
add_box((-14.3, 0.9, -1.2), (0.25, 0.25, 0.4), RED)

# Right Wing
add_box((7.5, 0.8, -1.0), (13.0, 0.35, 3.8), SILVER)
# Right Winglet (Blue)
add_box((14.2, 1.8, -1.8), (0.2, 2.2, 1.6), BLUE)
# Starboard Nav Light (Green)
add_box((14.3, 0.9, -1.2), (0.25, 0.25, 0.4), GREEN)

# 5. Twin Turbofan Jet Engines under wings
# Left Engine
add_box((-4.2, -0.2, 0.5), (1.5, 1.5, 4.2), SILVER)
add_box((-4.2, -0.2, 2.6), (1.3, 1.3, 0.4), DARK) # Intake spinner
# Right Engine
add_box((4.2, -0.2, 0.5), (1.5, 1.5, 4.2), SILVER)
add_box((4.2, -0.2, 2.6), (1.3, 1.3, 0.4), DARK) # Intake spinner

# 6. Vertical Tail Fin (Swept Blue Stabilizer)
add_box((0, 4.5, -9.5), (0.3, 5.5, 4.5), BLUE)

# 7. Horizontal Tailplanes
add_box((-4.2, 1.8, -10.0), (6.5, 0.25, 2.4), SILVER)
add_box((4.2, 1.8, -10.0), (6.5, 0.25, 2.4), SILVER)

verts_arr = np.array(vertices, dtype=np.float32)
norms_arr = np.array(normals, dtype=np.float32)
cols_arr = np.array(colors, dtype=np.float32)
indices_arr = np.array(indices, dtype=np.uint16).flatten()

pos_min = verts_arr.min(axis=0).tolist()
pos_max = verts_arr.max(axis=0).tolist()

vert_bytes = verts_arr.tobytes()
norm_bytes = norms_arr.tobytes()
col_bytes = cols_arr.tobytes()
idx_bytes = indices_arr.tobytes()

idx_pad = (4 - (len(idx_bytes) % 4)) % 4
idx_bytes += b'\x00' * idx_pad

bin_buffer = idx_bytes + vert_bytes + norm_bytes + col_bytes
bin_pad = (4 - (len(bin_buffer) % 4)) % 4
bin_buffer += b'\x00' * bin_pad

idx_offset = 0
vert_offset = len(idx_bytes)
norm_offset = vert_offset + len(vert_bytes)
col_offset = norm_offset + len(norm_bytes)

gltf_dict = {
    "asset": {"version": "2.0", "generator": "AeroTwin High-Detail GLB"},
    "scenes": [{"nodes": [0]}],
    "nodes": [{"mesh": 0, "name": "AeroTwin_Commercial_Jet"}],
    "meshes": [
        {
            "name": "AircraftMesh",
            "primitives": [
                {
                    "attributes": {
                        "POSITION": 1,
                        "NORMAL": 2,
                        "COLOR_0": 3
                    },
                    "indices": 0,
                    "mode": 4
                }
            ]
        }
    ],
    "buffers": [{"byteLength": len(bin_buffer)}],
    "bufferViews": [
        {"buffer": 0, "byteOffset": idx_offset, "byteLength": len(idx_bytes), "target": 34963},
        {"buffer": 0, "byteOffset": vert_offset, "byteLength": len(vert_bytes), "target": 34962},
        {"buffer": 0, "byteOffset": norm_offset, "byteLength": len(norm_bytes), "target": 34962},
        {"buffer": 0, "byteOffset": col_offset, "byteLength": len(col_bytes), "target": 34962}
    ],
    "accessors": [
        {
            "bufferView": 0,
            "byteOffset": 0,
            "componentType": 5123, # UNSIGNED_SHORT
            "count": len(indices_arr),
            "type": "SCALAR",
            "min": [int(indices_arr.min())],
            "max": [int(indices_arr.max())]
        },
        {
            "bufferView": 1,
            "byteOffset": 0,
            "componentType": 5126, # FLOAT
            "count": len(verts_arr),
            "type": "VEC3",
            "min": pos_min,
            "max": pos_max
        },
        {
            "bufferView": 2,
            "byteOffset": 0,
            "componentType": 5126, # FLOAT
            "count": len(norms_arr),
            "type": "VEC3"
        },
        {
            "bufferView": 3,
            "byteOffset": 0,
            "componentType": 5126, # FLOAT
            "count": len(cols_arr),
            "type": "VEC4"
        }
    ]
}

json_str = json.dumps(gltf_dict)
json_bytes = json_str.encode('utf-8')
json_pad = (4 - (len(json_bytes) % 4)) % 4
json_bytes += b' ' * json_pad

header_len = 12
chunk0_hdr_len = 8
chunk1_hdr_len = 8
total_len = header_len + chunk0_hdr_len + len(json_bytes) + chunk1_hdr_len + len(bin_buffer)

glb_data = struct.pack('<4sII', b'glTF', 2, total_len)
glb_data += struct.pack('<II', len(json_bytes), 0x4E4F534A) + json_bytes
glb_data += struct.pack('<II', len(bin_buffer), 0x004E4942) + bin_buffer

os.makedirs('ui/public', exist_ok=True)
with open('ui/public/aircraft.glb', 'wb') as f:
    f.write(glb_data)

print(f"Generated realistic aircraft.glb ({len(glb_data)} bytes)")
