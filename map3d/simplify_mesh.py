#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path


PLY_TYPE_INFO = {
    "char": ("b", 1),
    "uchar": ("B", 1),
    "short": ("h", 2),
    "ushort": ("H", 2),
    "int": ("i", 4),
    "uint": ("I", 4),
    "float": ("f", 4),
    "double": ("d", 8),
    "int8": ("b", 1),
    "uint8": ("B", 1),
    "int16": ("h", 2),
    "uint16": ("H", 2),
    "int32": ("i", 4),
    "uint32": ("I", 4),
    "float32": ("f", 4),
    "float64": ("d", 8),
}


def read_ply_mesh(ply_path: Path):
    with ply_path.open("rb") as handle:
        header_lines = []
        while True:
            line = handle.readline()
            if not line:
                raise RuntimeError(f"Incomplete PLY header: {ply_path}")
            decoded = line.decode("ascii", "replace").strip()
            header_lines.append(decoded)
            if decoded == "end_header":
                break

        if not header_lines or header_lines[0] != "ply":
            raise RuntimeError(f"Not a PLY file: {ply_path}")

        fmt = None
        vertex_count = 0
        face_count = 0
        element = None
        vertex_props = []
        face_list_prop = None
        for line in header_lines:
            if line.startswith("format "):
                fmt = line.split()[1]
            elif line.startswith("element "):
                parts = line.split()
                element = parts[1]
                if element == "vertex":
                    vertex_count = int(parts[2])
                elif element == "face":
                    face_count = int(parts[2])
            elif line.startswith("property "):
                parts = line.split()
                if element == "vertex" and len(parts) >= 3 and parts[1] != "list":
                    vertex_props.append((parts[2], parts[1]))
                elif element == "face" and len(parts) >= 5 and parts[1] == "list":
                    face_list_prop = (parts[2], parts[3], parts[4])

        if vertex_count <= 0 or face_count <= 0:
            return [], []

        if fmt not in {"ascii", "binary_little_endian"}:
            raise RuntimeError(f"Unsupported PLY format: {fmt}")

        vertices = []
        prop_names = [name for name, _type in vertex_props]
        prop_index = {name: idx for idx, name in enumerate(prop_names)}

        if fmt == "ascii":
            for _ in range(vertex_count):
                line = handle.readline()
                if not line:
                    break
                values = line.decode("ascii", "replace").strip().split()
                if len(values) < 3:
                    continue
                prop_values = {name: values[i] for i, (name, _type) in enumerate(vertex_props) if i < len(values)}
                vertices.append([
                    float(prop_values.get("x", 0.0)),
                    float(prop_values.get("y", 0.0)),
                    float(prop_values.get("z", 0.0)),
                    int(float(prop_values.get("red", prop_values.get("r", 205)))),
                    int(float(prop_values.get("green", prop_values.get("g", 180)))),
                    int(float(prop_values.get("blue", prop_values.get("b", 150)))),
                ])
            raw_faces = []
            for _ in range(face_count):
                line = handle.readline()
                if not line:
                    break
                values = line.decode("ascii", "replace").strip().split()
                if not values:
                    continue
                count = int(values[0])
                if len(values) < count + 1:
                    continue
                raw_faces.append([int(v) for v in values[1:1 + count]])
        else:
            formats = []
            row_size = 0
            for _name, type_name in vertex_props:
                fmt_char, size = PLY_TYPE_INFO[type_name]
                formats.append(fmt_char)
                row_size += size
            unpacker = struct.Struct("<" + "".join(formats))
            for _ in range(vertex_count):
                raw = handle.read(row_size)
                if len(raw) != row_size:
                    break
                values = unpacker.unpack(raw)
                vertices.append([
                    float(values[prop_index.get("x", 0)]),
                    float(values[prop_index.get("y", 1)]),
                    float(values[prop_index.get("z", 2)]),
                    int(values[prop_index["red"]]) if "red" in prop_index else (int(values[prop_index["r"]]) if "r" in prop_index else 205),
                    int(values[prop_index["green"]]) if "green" in prop_index else (int(values[prop_index["g"]]) if "g" in prop_index else 180),
                    int(values[prop_index["blue"]]) if "blue" in prop_index else (int(values[prop_index["b"]]) if "b" in prop_index else 150),
                ])
            if not face_list_prop:
                return vertices, []
            count_type, value_type, _name = face_list_prop
            count_fmt, count_size = PLY_TYPE_INFO[count_type]
            value_fmt, value_size = PLY_TYPE_INFO[value_type]
            raw_faces = []
            for _ in range(face_count):
                raw_count = handle.read(count_size)
                if len(raw_count) != count_size:
                    break
                count = struct.unpack("<" + count_fmt, raw_count)[0]
                raw_values = handle.read(value_size * count)
                if len(raw_values) != value_size * count:
                    break
                values = struct.unpack("<" + value_fmt * count, raw_values)
                raw_faces.append([int(v) for v in values])

    triangulated = []
    for face in raw_faces:
        if len(face) < 3:
            continue
        if len(face) == 3:
            triangulated.append(face)
        else:
            triangulated.extend([face[0], face[i], face[i + 1]] for i in range(1, len(face) - 1))
    return vertices, triangulated


def simplify_mesh(vertices, faces, max_faces: int):
    if len(faces) <= max_faces:
        sample_faces = faces
    else:
        step = len(faces) / max_faces
        sample_faces = []
        idx = 0.0
        while int(idx) < len(faces) and len(sample_faces) < max_faces:
            sample_faces.append(faces[int(idx)])
            idx += step

    used = sorted({vertex for face in sample_faces for vertex in face})
    remap = {old: new for new, old in enumerate(used)}
    compact_vertices = [vertices[idx] for idx in used]
    compact_faces = [[remap[idx] for idx in face] for face in sample_faces]
    return compact_vertices, compact_faces


def write_binary_ply(output_path: Path, vertices, faces):
    header = "\n".join([
        "ply",
        "format binary_little_endian 1.0",
        f"element vertex {len(vertices)}",
        "property float x",
        "property float y",
        "property float z",
        "property uchar red",
        "property uchar green",
        "property uchar blue",
        f"element face {len(faces)}",
        "property list uchar int vertex_indices",
        "end_header",
        "",
    ]).encode("ascii")
    vertex_struct = struct.Struct("<fffBBB")
    face_prefix = struct.Struct("<B")
    face_struct = struct.Struct("<iii")
    with output_path.open("wb") as handle:
        handle.write(header)
        for vertex in vertices:
            handle.write(vertex_struct.pack(vertex[0], vertex[1], vertex[2], vertex[3], vertex[4], vertex[5]))
        for face in faces:
            handle.write(face_prefix.pack(3))
            handle.write(face_struct.pack(face[0], face[1], face[2]))


def main():
    parser = argparse.ArgumentParser(description="Simplify a mesh PLY for web viewing.")
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    parser.add_argument("--max-faces", type=int, default=40000)
    args = parser.parse_args()

    input_path = Path(args.input_path)
    output_path = Path(args.output_path)
    vertices, faces = read_ply_mesh(input_path)
    if not faces:
        raise SystemExit("mesh has no faces")
    vertices, faces = simplify_mesh(vertices, faces, args.max_faces)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_binary_ply(output_path, vertices, faces)
    print(f"{len(vertices)} vertices, {len(faces)} faces")


if __name__ == "__main__":
    main()
