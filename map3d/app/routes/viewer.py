import json
import math
import re
import struct
import subprocess
from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, request, url_for

from .. import db
from ..models import Asset, Frame

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


def enrich_cameras_with_urls(cameras):
    storage_paths = [normalize_model_image_path(camera["path"]) for camera in cameras]
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
        frame_info = by_storage_path.get(normalized_path, {})
        preview_path = frame_info.get("preview_path")
        frame_id = frame_info.get("frame_id")
        camera["storage_path"] = normalized_path
        camera["image_url"] = url_for("gallery.serve_data", filepath=normalized_path)
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


def sparse_viewer_payload(model_dir):
    export_dir = ensure_txt_export(model_dir)
    points = sample_points(export_dir / "points3D.txt")
    cameras = enrich_cameras_with_urls(parse_images_txt(export_dir / "images.txt"))
    return {
        "geometry": "sparse",
        "points": points,
        "cameras": cameras,
        "bounds": compute_bounds(points, cameras),
    }


def dense_viewer_payload(workspace_dir, model_dir):
    dense_ply = workspace_dir / "dense" / "fused.ply"
    if not dense_ply.exists():
        raise RuntimeError(f"No dense point cloud found yet at {dense_ply}")
    points = read_ply_vertices(dense_ply)
    cameras = enrich_cameras_with_urls(parse_images_txt(ensure_txt_export(model_dir) / "images.txt"))
    return {
        "geometry": "dense",
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
    active_model = next((item for item in models if item["id"] == requested_model_id), models[0])
    dense_available = (workspace_dir / "dense" / "fused.ply").exists()
    if requested_geometry not in {"sparse", "dense"}:
        requested_geometry = "sparse"

    try:
        if requested_geometry == "dense":
            payload = dense_viewer_payload(workspace_dir, active_model["path"])
        else:
            payload = sparse_viewer_payload(active_model["path"])
        viewer_error = None
    except RuntimeError as exc:
        payload = sparse_viewer_payload(active_model["path"])
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
    )
