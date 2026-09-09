import json
import struct
import numpy as np
import os

# Low-poly airplane: Fuselage (cylinder-like), Wings, Tail fin
vertices = []
indices = []

def add_box(center, size):
    # center: (x,y,z), size: (dx, dy, dz)
    cx, cy, cz = center
    dx, dy, dz = size[0]/2, size[1]/2, size[2]/2
    start_idx = len(vertices)
    
    # 8 corners
    corners = [
        (cx - dx, cy - dy, cz - dz),
        (cx + dx, cy - dy, cz - dz),
        (cx + dx, cy + dy, cz - dz),
        (cx - dx, cy + dy, cz - dz),
        (cx - dx, cy - dy, cz + dz),
        (cx + dx, cy - dy, cz + dz),
        (cx + dx, cy + dy, cz + dz),
        (cx - dx, cy + dy, cz + dz),
    ]
    vertices.extend(corners)
    
    # 12 triangles (6 faces)
    faces = [
        # Front (-z)
        (0, 1, 2), (0, 2, 3),
        # Back (+z)
        (4, 6, 5), (4, 7, 6),
        # Left (-x)
        (0, 3, 7), (0, 7, 4),
        # Right (+x)
        (1, 5, 6), (1, 6, 2),
        # Top (+y)
        (3, 2, 6), (3, 6, 7),
        # Bottom (-y)
        (0, 4, 5), (0, 5, 1)
    ]
    for tri in faces:
        indices.append((start_idx + tri[0], start_idx + tri[1], start_idx + tri[2]))

# Fuselage: along Y or Z axis. In aircraft coords: nose at +Y or +Z, wings along X
# Fuselage: width 1.2, height 1.2, length 12
add_box((0, 0.6, 0), (1.2, 1.2, 12.0))
# Cockpit / Nose taper
add_box((0, 0.4, 6.5), (0.8, 0.8, 1.5))
# Main Wings: span 14.0, thickness 0.2, chord 2.4
add_box((0, 0.5, 0.5), (14.0, 0.2, 2.4))
# Tail Stabilizer (horizontal): span 5.0, thickness 0.15, chord 1.2
add_box((0, 0.7, -5.2), (5.0, 0.15, 1.2))
# Vertical Fin: width 0.15, height 2.2, chord 1.6
add_box((0, 1.7, -5.2), (0.15, 2.2, 1.6))

verts_arr = np.array(vertices, dtype=np.float32)
indices_arr = np.array(indices, dtype=np.uint16).flatten()

pos_min = verts_arr.min(axis=0).tolist()
pos_max = verts_arr.max(axis=0).tolist()

vert_bytes = verts_arr.tobytes()
idx_bytes = indices_arr.tobytes()

# Align idx_bytes to 4 bytes
idx_pad = (4 - (len(idx_bytes) % 4)) % 4
idx_bytes += b'\x00' * idx_pad

bin_buffer = idx_bytes + vert_bytes
bin_pad = (4 - (len(bin_buffer) % 4)) % 4
bin_buffer += b'\x00' * bin_pad

gltf_dict = {
    "asset": {"version": "2.0", "generator": "AeroTwin GLB Builder"},
    "scenes": [{"nodes": [0]}],
    "nodes": [{"mesh": 0, "name": "Aircraft"}],
    "meshes": [
        {
            "name": "AircraftMesh",
            "primitives": [
                {
                    "attributes": {"POSITION": 1},
                    "indices": 0,
                    "mode": 4,
                    "material": 0
                }
            ]
        }
    ],
    "materials": [
        {
            "name": "AircraftMat",
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.9, 0.95, 1.0, 1.0],
                "metallicFactor": 0.2,
                "roughnessFactor": 0.4
            }
        }
    ],
    "buffers": [
        {
            "byteLength": len(bin_buffer)
        }
    ],
    "bufferViews": [
        {
            "buffer": 0,
            "byteOffset": 0,
            "byteLength": len(idx_bytes),
            "target": 34963 # ELEMENT_ARRAY_BUFFER
        },
        {
            "buffer": 0,
            "byteOffset": len(idx_bytes),
            "byteLength": len(vert_bytes),
            "target": 34962 # ARRAY_BUFFER
        }
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

# glb header: magic(0x46546C67), version(2), length
glb_data = struct.pack('<4sII', b'glTF', 2, total_len)
# chunk 0: JSON
glb_data += struct.pack('<II', len(json_bytes), 0x4E4F534A) + json_bytes
# chunk 1: BIN
glb_data += struct.pack('<II', len(bin_buffer), 0x004E4942) + bin_buffer

os.makedirs('ui/public', exist_ok=True)
with open('ui/public/aircraft.glb', 'wb') as f:
    f.write(glb_data)

print(f"Generated valid aircraft.glb ({len(glb_data)} bytes)")
