import json
import math
import re
import struct
import subprocess
from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, request, url_for

from .. import db
from ..models import Asset, Frame
from ..model_tools import model_workspace_dir

bp = Blueprint("viewer", __name__)

ANALYZER_LINE_RE = re.compile(r"(?:\]\s*)?([A-Za-z][A-Za-z ]+):\s+(.+)$")


def reconstruction_root():
    return Path(current_app.config["DATA_DIR"]) / "derived" / "reconstructions"


def reconstruction_set_root():
    return Path(current_app.config["DATA_DIR"]) / "derived" / "reconstruction_sets"


def sparse_model_dirs(workspace_dir):
    sparse_dir = workspace_dir / "sparse"
    if not sparse_dir.exists():
        return []
    return sorted(
        [
            path
            for path in sparse_dir.iterdir()
            if path.is_dir() and (path / "points3D.bin").exists() and (path / "images.bin").exists()
        ],
        key=lambda path: path.name,
    )


def read_selection_summary(name):
    selection_path = reconstruction_set_root() / name / "selection.json"
    if not selection_path.exists():
        return {}
    try:
        data = json.loads(selection_path.read_text())
    except json.JSONDecodeError:
        return {}
    return {
        "count": data.get("count"),
        "building_name": data.get("building_name"),
        "first_session": data.get("first_session"),
        "last_session": data.get("last_session"),
        "first_time": data.get("first_time"),
        "last_time": data.get("last_time"),
    }


def read_reconstruction_manifest(name):
    manifest_path = reconstruction_set_root() / name / "manifest.tsv"
    mapping = {}
    if not manifest_path.exists():
        return mapping
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return mapping
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        target_name, _asset_id, _asset_type, _import_source, storage_path = parts[:5]
        if target_name and storage_path:
            mapping[target_name] = storage_path
    return mapping


def analyze_model(model_dir):
    result = subprocess.run(
        ["colmap", "model_analyzer", "--path", str(model_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    stats = {}
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    for line in output.splitlines():
        match = ANALYZER_LINE_RE.search(line)
        if not match:
            continue
        key = match.group(1).strip().lower().replace(" ", "_")
        value = match.group(2).strip()
        stats[key] = value
    return stats


def parse_int(value, default=0):
    try:
        return int(str(value).split()[0].replace(",", ""))
    except (TypeError, ValueError, AttributeError):
        return default


def parse_float(value, default=0.0):
    try:
        return float(str(value).replace("px", "").strip())
    except (TypeError, ValueError, AttributeError):
        return default


def summarize_workspace(workspace_dir):
    models = []
    for model_dir in sparse_model_dirs(workspace_dir):
        stats = analyze_model(model_dir)
        models.append({
            "id": model_dir.name,
            "path": model_dir,
            "registered_images": parse_int(stats.get("registered_images")),
            "points": parse_int(stats.get("points")),
            "mean_error_px": parse_float(stats.get("mean_reprojection_error")),
        })
    models.sort(key=lambda item: (item["registered_images"], item["points"]), reverse=True)
    return models


def best_model(workspace_dir):
    models = summarize_workspace(workspace_dir)
    return models[0] if models else None


def ensure_txt_export(model_dir):
    export_dir = model_dir / "viewer_txt"
    points_txt = export_dir / "points3D.txt"
    images_txt = export_dir / "images.txt"
    cameras_txt = export_dir / "cameras.txt"
    source_points = model_dir / "points3D.bin"

    needs_export = (
        not points_txt.exists()
        or not images_txt.exists()
        or not cameras_txt.exists()
        or points_txt.stat().st_mtime < source_points.stat().st_mtime
    )
    if needs_export:
        export_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                "colmap",
                "model_converter",
                "--input_path",
                str(model_dir),
                "--output_path",
                str(export_dir),
                "--output_type",
                "TXT",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "COLMAP model_converter failed")
    return export_dir


def quaternion_to_rotation_matrix(qw, qx, qy, qz):
    return [
        [
            1 - 2 * (qy * qy + qz * qz),
            2 * (qx * qy - qz * qw),
            2 * (qx * qz + qy * qw),
        ],
        [
            2 * (qx * qy + qz * qw),
            1 - 2 * (qx * qx + qz * qz),
            2 * (qy * qz - qx * qw),
        ],
        [
            2 * (qx * qz - qy * qw),
            2 * (qy * qz + qx * qw),
            1 - 2 * (qx * qx + qy * qy),
        ],
    ]


def camera_center(qw, qx, qy, qz, tx, ty, tz):
    rotation = quaternion_to_rotation_matrix(qw, qx, qy, qz)
    translation = [tx, ty, tz]
    return [
        -(rotation[0][0] * translation[0] + rotation[1][0] * translation[1] + rotation[2][0] * translation[2]),
        -(rotation[0][1] * translation[0] + rotation[1][1] * translation[1] + rotation[2][1] * translation[2]),
        -(rotation[0][2] * translation[0] + rotation[1][2] * translation[1] + rotation[2][2] * translation[2]),
    ]


def parse_images_txt(images_txt):
    cameras = []
    lines = images_txt.read_text().splitlines()
    for line in lines:
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 10:
            continue
        if len(parts) > 10 and "." in parts[0]:
            continue
        image_id = int(parts[0])
        qw, qx, qy, qz = map(float, parts[1:5])
        tx, ty, tz = map(float, parts[5:8])
        name = " ".join(parts[9:])
        cameras.append({
            "id": image_id,
            "name": Path(name).name,
            "path": name,
            "center": camera_center(qw, qx, qy, qz, tx, ty, tz),
        })
    return cameras


def normalize_model_image_path(path_str):
    path = Path(path_str)
    parts = list(path.parts)
    if "originals" in parts:
        return str(Path(*parts[parts.index("originals"):]))
    return path.name


def enrich_cameras_with_urls(cameras, image_name_map=None):
    storage_paths = []
    resolved_storage = {}
    for camera in cameras:
        normalized_path = normalize_model_image_path(camera["path"])
        storage_path = image_name_map.get(normalized_path, normalized_path) if image_name_map else normalized_path
        resolved_storage[camera["id"]] = storage_path
        storage_paths.append(storage_path)
    if not storage_paths:
        return cameras

    rows = (
        db.session.query(Asset.storage_path, Frame.preview_path, Frame.id)
        .join(Frame, Frame.asset_id == Asset.id)
        .filter(Asset.storage_path.in_(storage_paths))
        .all()
    )
    by_storage_path = {
        storage_path: {"preview_path": preview_path, "frame_id": frame_id}
        for storage_path, preview_path, frame_id in rows
    }

    for camera in cameras:
        normalized_path = normalize_model_image_path(camera["path"])
        storage_path = resolved_storage.get(camera["id"], normalized_path)
        frame_info = by_storage_path.get(storage_path, {})
        preview_path = frame_info.get("preview_path")
        frame_id = frame_info.get("frame_id")
        camera["storage_path"] = storage_path
        camera["image_url"] = url_for("gallery.serve_data", filepath=storage_path)
        camera["preview_url"] = url_for("gallery.serve_data", filepath=preview_path) if preview_path else camera["image_url"]
        camera["frame_url"] = url_for("gallery.frame_detail", frame_id=frame_id) if frame_id else None
    return cameras


def sample_points(points_txt, max_points=8000):
    raw_points = []
    with points_txt.open() as handle:
        for line in handle:
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            raw_points.append([
                float(parts[1]),
                float(parts[2]),
                float(parts[3]),
                int(parts[4]),
                int(parts[5]),
                int(parts[6]),
            ])

    if len(raw_points) <= max_points:
        return raw_points

    step = len(raw_points) / max_points
    sampled = []
    index = 0.0
    while int(index) < len(raw_points) and len(sampled) < max_points:
        sampled.append(raw_points[int(index)])
        index += step
    return sampled


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


def read_ply_vertices(ply_path, max_points=25000):
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
        in_vertex = False
        vertex_props = []
        for line in header_lines:
            if line.startswith("format "):
                fmt = line.split()[1]
            elif line.startswith("element "):
                parts = line.split()
                in_vertex = parts[1] == "vertex"
                if in_vertex:
                    vertex_count = int(parts[2])
            elif in_vertex and line.startswith("property "):
                parts = line.split()
                if len(parts) >= 3 and parts[1] != "list":
                    vertex_props.append((parts[2], parts[1]))

        if vertex_count <= 0:
            return []

        if fmt == "ascii":
            vertices = []
            step = max(1, vertex_count // max_points)
            for idx in range(vertex_count):
                line = handle.readline()
                if not line:
                    break
                if idx % step != 0:
                    continue
                values = line.decode("ascii", "replace").strip().split()
                if len(values) < 3:
                    continue
                prop_values = {name: values[i] for i, (name, _type) in enumerate(vertex_props) if i < len(values)}
                vertices.append([
                    float(prop_values.get("x", 0.0)),
                    float(prop_values.get("y", 0.0)),
                    float(prop_values.get("z", 0.0)),
                    int(float(prop_values.get("red", prop_values.get("r", 255)))),
                    int(float(prop_values.get("green", prop_values.get("g", 180)))),
                    int(float(prop_values.get("blue", prop_values.get("b", 120)))),
                ])
            return vertices

        if fmt != "binary_little_endian":
            raise RuntimeError(f"Unsupported PLY format: {fmt}")

        formats = []
        row_size = 0
        for _name, type_name in vertex_props:
            fmt_char, size = PLY_TYPE_INFO[type_name]
            formats.append(fmt_char)
            row_size += size
        unpacker = struct.Struct("<" + "".join(formats))
        prop_names = [name for name, _type in vertex_props]
        prop_index = {name: idx for idx, name in enumerate(prop_names)}
        step = max(1, vertex_count // max_points)
        vertices = []
        for idx in range(vertex_count):
            raw = handle.read(row_size)
            if len(raw) != row_size:
                break
            if idx % step != 0:
                continue
            values = unpacker.unpack(raw)
            vertices.append([
                float(values[prop_index.get("x", 0)]),
                float(values[prop_index.get("y", 1)]),
                float(values[prop_index.get("z", 2)]),
                int(values[prop_index["red"]]) if "red" in prop_index else (int(values[prop_index["r"]]) if "r" in prop_index else 255),
                int(values[prop_index["green"]]) if "green" in prop_index else (int(values[prop_index["g"]]) if "g" in prop_index else 180),
                int(values[prop_index["blue"]]) if "blue" in prop_index else (int(values[prop_index["b"]]) if "b" in prop_index else 120),
            ])
        return vertices


def read_ply_mesh(ply_path, max_faces=12000):
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
            return {"vertices": [], "faces": []}

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
                return {"vertices": vertices, "faces": []}
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

        if not raw_faces:
            return {"vertices": vertices, "faces": []}

        step = max(1, len(raw_faces) // max_faces)
        sampled_raw_faces = [face for idx, face in enumerate(raw_faces) if idx % step == 0]
        triangulated = []
        used_vertices = set()
        for face in sampled_raw_faces:
            if len(face) < 3:
                continue
            if len(face) == 3:
                tris = [face]
            else:
                tris = [[face[0], face[i], face[i + 1]] for i in range(1, len(face) - 1)]
            for tri in tris:
                triangulated.append(tri)
                used_vertices.update(tri)

        if not triangulated:
            return {"vertices": [], "faces": []}

        used_order = sorted(used_vertices)
        remap = {old_idx: new_idx for new_idx, old_idx in enumerate(used_order)}
        compact_vertices = [vertices[idx] for idx in used_order if 0 <= idx < len(vertices)]
        compact_faces = [[remap[idx] for idx in tri] for tri in triangulated if all(idx in remap for idx in tri)]
        return {
            "vertices": compact_vertices,
            "faces": compact_faces,
        }


def ply_header_counts(ply_path):
    counts = {"vertex": 0, "face": 0}
    try:
        with ply_path.open("rb") as handle:
            while True:
                line = handle.readline()
                if not line:
                    break
                decoded = line.decode("ascii", "replace").strip()
                if decoded.startswith("element vertex "):
                    counts["vertex"] = int(decoded.split()[-1])
                elif decoded.startswith("element face "):
                    counts["face"] = int(decoded.split()[-1])
                elif decoded == "end_header":
                    break
    except Exception:
        return counts
    return counts


def textured_mesh_paths(workspace_dir, variant="web"):
    candidate_dirs = []
    if variant == "full":
        candidate_dirs = [workspace_dir / "texturing_delaunay"]
    elif variant == "web":
        candidate_dirs = [workspace_dir / "texturing", workspace_dir / "texturing_web"]
    else:
        candidate_dirs = [
            workspace_dir / "texturing",
            workspace_dir / "texturing_web",
            workspace_dir / "texturing_delaunay",
        ]
    for texturing_dir in candidate_dirs:
        obj_path = texturing_dir / "textured.obj"
        mtl_path = texturing_dir / "textured.mtl"
        texture_path = texturing_dir / "texture.png"
        if obj_path.exists() and mtl_path.exists() and texture_path.exists():
            return {
                "obj": obj_path,
                "mtl": mtl_path,
                "texture": texture_path,
                "variant": variant,
            }
    return None


def read_obj_mesh(obj_path, max_faces=40000):
    vertices = []
    uvs = []
    raw_faces = []

    with obj_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not line or line.startswith("#"):
                continue
            if line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif line.startswith("vt "):
                parts = line.split()
                if len(parts) >= 3:
                    uvs.append([float(parts[1]), float(parts[2])])
            elif line.startswith("f "):
                items = []
                for token in line.split()[1:]:
                    chunks = token.split("/")
                    if not chunks or not chunks[0]:
                        continue
                    v_idx = int(chunks[0])
                    vt_idx = int(chunks[1]) if len(chunks) > 1 and chunks[1] else 0
                    items.append((v_idx, vt_idx))
                if len(items) >= 3:
                    raw_faces.append(items)

    if not raw_faces or not vertices:
        return {"vertices": [], "faces": [], "uvs": []}

    step = max(1, len(raw_faces) // max_faces)
    sampled_raw_faces = [face for idx, face in enumerate(raw_faces) if idx % step == 0]

    compact_vertices = []
    compact_uvs = []
    compact_faces = []
    remap = {}

    def resolve_obj_index(idx, count):
        if idx > 0:
            return idx - 1
        if idx < 0:
            return count + idx
        return None

    for face in sampled_raw_faces:
        if len(face) == 3:
            triangles = [face]
        else:
            triangles = [[face[0], face[i], face[i + 1]] for i in range(1, len(face) - 1)]
        for tri in triangles:
            compact_face = []
            for v_idx_raw, vt_idx_raw in tri:
                v_idx = resolve_obj_index(v_idx_raw, len(vertices))
                vt_idx = resolve_obj_index(vt_idx_raw, len(uvs)) if vt_idx_raw else None
                key = (v_idx, vt_idx)
                if key not in remap:
                    remap[key] = len(compact_vertices)
                    vx, vy, vz = vertices[v_idx]
                    compact_vertices.append([vx, vy, vz, 205, 180, 150])
                    if vt_idx is not None and 0 <= vt_idx < len(uvs):
                        compact_uvs.append(uvs[vt_idx])
                    else:
                        compact_uvs.append([0.0, 0.0])
                compact_face.append(remap[key])
            compact_faces.append(compact_face)

    return {
        "vertices": compact_vertices,
        "faces": compact_faces,
        "uvs": compact_uvs,
    }


def best_mesh_path(workspace_dir):
    candidates = [
        workspace_dir / "dense" / "meshed-web.ply",
        workspace_dir / "dense" / "meshed-poisson.ply",
        workspace_dir / "dense" / "meshed-delaunay.ply",
    ]
    for path in candidates:
        if path.exists() and ply_header_counts(path)["face"] > 0:
            return path
    return None


def mesh_source_label(mesh_path):
    if mesh_path is None:
        return None
    name = mesh_path.name
    if name == "textured.obj":
        return "textured"
    if name == "meshed-web.ply":
        return "web"
    if name == "meshed-poisson.ply":
        return "poisson"
    if name == "meshed-delaunay.ply":
        return "delaunay"
    return name


def compute_bounds(points, cameras):
    bounds = {
        "min": [math.inf, math.inf, math.inf],
        "max": [-math.inf, -math.inf, -math.inf],
    }
    for point in points:
        for axis in range(3):
            bounds["min"][axis] = min(bounds["min"][axis], point[axis])
            bounds["max"][axis] = max(bounds["max"][axis], point[axis])
    for camera in cameras:
        for axis in range(3):
            bounds["min"][axis] = min(bounds["min"][axis], camera["center"][axis])
            bounds["max"][axis] = max(bounds["max"][axis], camera["center"][axis])
    if not points and not cameras:
        return {"min": [-1, -1, -1], "max": [1, 1, 1]}
    return bounds


def sparse_viewer_payload(model_dir, image_name_map=None):
    export_dir = ensure_txt_export(model_dir)
    points = sample_points(export_dir / "points3D.txt")
    cameras = enrich_cameras_with_urls(parse_images_txt(export_dir / "images.txt"), image_name_map=image_name_map)
    return {
        "geometry": "sparse",
        "points": points,
        "cameras": cameras,
        "bounds": compute_bounds(points, cameras),
    }


def dense_viewer_payload(workspace_dir, model_dir, image_name_map=None):
    dense_ply = workspace_dir / "dense" / "fused.ply"
    if not dense_ply.exists():
        raise RuntimeError(f"No dense point cloud found yet at {dense_ply}")
    points = read_ply_vertices(dense_ply)
    cameras = enrich_cameras_with_urls(parse_images_txt(ensure_txt_export(model_dir) / "images.txt"), image_name_map=image_name_map)
    return {
        "geometry": "dense",
        "points": points,
        "cameras": cameras,
        "bounds": compute_bounds(points, cameras),
        "dense_point_count": len(points),
    }


def mesh_viewer_payload(workspace_dir, model_dir, image_name_map=None, mesh_variant="web"):
    textured = textured_mesh_paths(workspace_dir, mesh_variant)
    texture_url = None
    mesh_filename = None
    mesh_source = None
    if textured:
        mesh = read_obj_mesh(textured["obj"])
        texture_url = url_for("gallery.serve_data", filepath=str(textured["texture"].relative_to(Path(current_app.config["DATA_DIR"]))))
        mesh_filename = textured["obj"].name
        mesh_source = f"{mesh_source_label(textured['obj'])}-{mesh_variant}"
    else:
        if mesh_variant == "full":
            mesh_ply = workspace_dir / "dense" / "meshed-delaunay.ply"
            if not mesh_ply.exists() or ply_header_counts(mesh_ply)["face"] <= 0:
                mesh_ply = None
        else:
            mesh_ply = best_mesh_path(workspace_dir)
        if mesh_ply is None:
            raise RuntimeError(f"No usable mesh found yet in {workspace_dir / 'dense'}")
        mesh = read_ply_mesh(mesh_ply)
        mesh_filename = mesh_ply.name
        mesh_source = f"{mesh_source_label(mesh_ply)}-{mesh_variant}" if mesh_variant else mesh_source_label(mesh_ply)
    cameras = enrich_cameras_with_urls(parse_images_txt(ensure_txt_export(model_dir) / "images.txt"), image_name_map=image_name_map)
    points = mesh["vertices"]
    return {
        "geometry": "mesh",
        "points": points,
        "faces": mesh["faces"],
        "uvs": mesh.get("uvs", []),
        "cameras": cameras,
        "bounds": compute_bounds(points, cameras),
        "mesh_face_count": len(mesh["faces"]),
        "mesh_vertex_count": len(mesh["vertices"]),
        "mesh_source": mesh_source,
        "mesh_filename": mesh_filename,
        "texture_url": texture_url,
    }


def parse_model_camera_params(camera_path):
    try:
        data = json.loads(camera_path.read_text())
    except Exception:
        return []
    cameras = []
    for item in data.get("extrinsics", []):
        matrix = item.get("matrix")
        if not matrix or len(matrix) < 3:
            continue
        center = [
            float(matrix[0][3]),
            float(matrix[1][3]),
            float(matrix[2][3]),
        ]
        cameras.append({
            "id": item.get("camera_id"),
            "name": str(item.get("camera_id")),
            "path": "",
            "center": center,
            "storage_path": "",
            "image_url": None,
            "preview_url": None,
            "frame_url": None,
        })
    return cameras


def model_point_payload(result_dir, geometry="points"):
    ply_name = "points.ply" if geometry == "points" else "gaussians.ply"
    ply_path = result_dir / ply_name
    if not ply_path.exists():
        raise RuntimeError(f"No model {geometry} found yet at {ply_path}")
    points = read_ply_vertices(ply_path)
    camera_path = result_dir / "camera_params.json"
    cameras = parse_model_camera_params(camera_path) if camera_path.exists() else []
    return {
        "geometry": geometry,
        "points": points,
        "cameras": cameras,
        "bounds": compute_bounds(points, cameras),
        "dense_point_count": len(points),
    }


@bp.route("/viewer")
def viewer_index():
    recon_root = reconstruction_root()
    workspaces = []
    for workspace_dir in sorted([path for path in recon_root.iterdir() if path.is_dir()]):
        models = summarize_workspace(workspace_dir)
        selection = read_selection_summary(workspace_dir.name)
        workspaces.append({
            "name": workspace_dir.name,
            "models": models,
            "best_model": models[0] if models else None,
            "selection": selection,
            "log_exists": (workspace_dir / "reconstruct.log").exists(),
            "dense_exists": (workspace_dir / "dense" / "fused.ply").exists(),
            "mesh_exists": textured_mesh_paths(workspace_dir, "web") is not None or textured_mesh_paths(workspace_dir, "full") is not None or best_mesh_path(workspace_dir) is not None,
        })
    workspaces.sort(
        key=lambda item: (
            item["best_model"]["registered_images"] if item["best_model"] else -1,
            item["best_model"]["points"] if item["best_model"] else -1,
            item["name"],
        ),
        reverse=True,
    )
    return render_template("viewer_index.html", workspaces=workspaces)


@bp.route("/viewer/<name>")
def viewer_detail(name):
    workspace_dir = reconstruction_root() / name
    if not workspace_dir.is_dir():
        abort(404)

    models = summarize_workspace(workspace_dir)
    if not models:
        return render_template(
            "viewer_detail.html",
            workspace_name=name,
            models=[],
            active_model=None,
            payload_json="{}",
            selection=read_selection_summary(name),
            viewer_error="No sparse models found yet in this reconstruction workspace.",
        )

    requested_model_id = request.args.get("model")
    requested_geometry = request.args.get("geometry", "sparse")
    requested_mesh_variant = request.args.get("mesh_variant", "web")
    if requested_mesh_variant not in {"web", "full"}:
        requested_mesh_variant = "web"
    active_model = next((item for item in models if item["id"] == requested_model_id), models[0])
    image_name_map = read_reconstruction_manifest(name)
    dense_ply = workspace_dir / "dense" / "fused.ply"
    mesh_textured = textured_mesh_paths(workspace_dir, requested_mesh_variant)
    mesh_ply = best_mesh_path(workspace_dir)
    dense_available = dense_ply.exists() and ply_header_counts(dense_ply)["vertex"] > 0
    mesh_available = mesh_textured is not None or mesh_ply is not None or textured_mesh_paths(workspace_dir, "full") is not None
    if requested_geometry not in {"sparse", "dense", "mesh"}:
        requested_geometry = "sparse"

    try:
        if requested_geometry == "mesh":
            payload = mesh_viewer_payload(workspace_dir, active_model["path"], image_name_map=image_name_map, mesh_variant=requested_mesh_variant)
        elif requested_geometry == "dense":
            payload = dense_viewer_payload(workspace_dir, active_model["path"], image_name_map=image_name_map)
        else:
            payload = sparse_viewer_payload(active_model["path"], image_name_map=image_name_map)
        viewer_error = None
    except RuntimeError as exc:
        payload = sparse_viewer_payload(active_model["path"], image_name_map=image_name_map)
        requested_geometry = "sparse"
        viewer_error = str(exc)

    return render_template(
        "viewer_detail.html",
        workspace_name=name,
        models=models,
        active_model=active_model,
        payload_json=json.dumps(payload),
        selection=read_selection_summary(name),
        viewer_error=viewer_error,
        active_geometry=requested_geometry,
        dense_available=dense_available,
        mesh_available=mesh_available,
        active_mesh_variant=requested_mesh_variant,
        mesh_variant_links=[
            {"id": "web", "label": "Mesh Web", "url": url_for('viewer.viewer_detail', name=name, model=active_model["id"] if active_model else None, geometry='mesh', mesh_variant='web'), "active": requested_geometry == "mesh" and requested_mesh_variant == "web"},
            {"id": "full", "label": "Mesh Full", "url": url_for('viewer.viewer_detail', name=name, model=active_model["id"] if active_model else None, geometry='mesh', mesh_variant='full'), "active": requested_geometry == "mesh" and requested_mesh_variant == "full"},
        ],
        geometry_links=[
            {"id": "sparse", "label": "Sparse", "url": url_for('viewer.viewer_detail', name=name, model=active_model["id"] if active_model else None, geometry='sparse'), "active": requested_geometry == "sparse"},
            *([{"id": "dense", "label": "Dense", "url": url_for('viewer.viewer_detail', name=name, model=active_model["id"] if active_model else None, geometry='dense'), "active": requested_geometry == "dense"}] if dense_available else []),
            *([{"id": "mesh", "label": "Mesh", "url": url_for('viewer.viewer_detail', name=name, model=active_model["id"] if active_model else None, geometry='mesh', mesh_variant=requested_mesh_variant), "active": requested_geometry == "mesh"}] if mesh_available else []),
        ],
        viewer_kind="reconstruction",
    )


@bp.route("/model-viewer/<int:session_id>/<backend>")
def model_viewer_detail(session_id, backend):
    data_dir = Path(current_app.config["DATA_DIR"])
    workspace_dir = model_workspace_dir(data_dir, session_id, backend)
    result_dir = workspace_dir / "outputs" / "result"
    if not result_dir.is_dir():
        abort(404)

    requested_geometry = request.args.get("geometry", "points")
    if requested_geometry not in {"points", "gaussians"}:
        requested_geometry = "points"
    gaussians_available = (result_dir / "gaussians.ply").exists()
    points_available = (result_dir / "points.ply").exists()
    if requested_geometry == "gaussians" and not gaussians_available:
        requested_geometry = "points"

    try:
        payload = model_point_payload(result_dir, requested_geometry)
        viewer_error = None
    except RuntimeError as exc:
        payload = {"geometry": "points", "points": [], "cameras": [], "bounds": {"min": [-1, -1, -1], "max": [1, 1, 1]}}
        viewer_error = str(exc)

    summary = {
        "building_name": f"Experimental model · {backend}",
        "count": payload.get("dense_point_count", 0),
        "first_session": session_id,
        "last_session": session_id,
    }

    return render_template(
        "viewer_detail.html",
        workspace_name=f"session_{session_id:04d}/{backend}",
        models=[],
        active_model=None,
        payload_json=json.dumps(payload),
        selection=summary,
        viewer_error=viewer_error,
        active_geometry=requested_geometry,
        dense_available=False,
        mesh_available=False,
        geometry_links=[
            *([{"id": "points", "label": "Points", "url": url_for('viewer.model_viewer_detail', session_id=session_id, backend=backend, geometry='points'), "active": requested_geometry == "points"}] if points_available else []),
            *([{"id": "gaussians", "label": "Gaussians", "url": url_for('viewer.model_viewer_detail', session_id=session_id, backend=backend, geometry='gaussians'), "active": requested_geometry == "gaussians"}] if gaussians_available else []),
        ],
        viewer_kind="model",
    )
