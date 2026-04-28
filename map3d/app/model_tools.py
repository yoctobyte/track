import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import Asset, Frame, Session
from .storage import get_absolute_path


MODEL_BACKENDS = ("hyworld", "lyra")


@dataclass
class ModelRunInfo:
    backend: str
    workspace_dir: Path
    status: str
    input_kind: str
    points_exists: bool
    gaussians_exists: bool
    camera_exists: bool
    colmap_exists: bool
    rendered_exists: bool
    mesh_exists: bool
    run_script: Path | None
    result_dir: Path | None
    points_path: Path | None
    gaussians_path: Path | None
    camera_path: Path | None
    timing_path: Path | None


def model_reconstruction_root(data_dir: Path) -> Path:
    return data_dir / "derived" / "model_reconstructions"


def model_workspace_dir(data_dir: Path, session_id: int, backend: str) -> Path:
    return model_reconstruction_root(data_dir) / f"session_{session_id:04d}" / backend


def read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def session_model_runs(data_dir: Path, session_id: int) -> list[ModelRunInfo]:
    runs: list[ModelRunInfo] = []
    for backend in MODEL_BACKENDS:
        workspace = model_workspace_dir(data_dir, session_id, backend)
        if not workspace.exists():
            continue
        job = read_json_file(workspace / "job.json")
        status_data = read_json_file(workspace / "status.json")
        result_dir = workspace / "outputs" / "result"
        sparse_dir = result_dir / "sparse" / "0"
        runs.append(ModelRunInfo(
            backend=backend,
            workspace_dir=workspace,
            status=status_data.get("status") or job.get("status") or "prepared",
            input_kind=job.get("input", {}).get("kind", ""),
            points_exists=(result_dir / "points.ply").exists(),
            gaussians_exists=(result_dir / "gaussians.ply").exists(),
            camera_exists=(result_dir / "camera_params.json").exists(),
            colmap_exists=sparse_dir.exists(),
            rendered_exists=(result_dir / "rendered" / "rendered_rgb.mp4").exists(),
            mesh_exists=(result_dir / "mesh.ply").exists() or (result_dir / "mesh.glb").exists(),
            run_script=(workspace / "scripts" / "run-backend.sh") if (workspace / "scripts" / "run-backend.sh").exists() else None,
            result_dir=result_dir if result_dir.exists() else None,
            points_path=(result_dir / "points.ply") if (result_dir / "points.ply").exists() else None,
            gaussians_path=(result_dir / "gaussians.ply") if (result_dir / "gaussians.ply").exists() else None,
            camera_path=(result_dir / "camera_params.json") if (result_dir / "camera_params.json").exists() else None,
            timing_path=(result_dir / "pipeline_timing.json") if (result_dir / "pipeline_timing.json").exists() else None,
        ))
    return runs


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


def colmap_pose_to_c2w(qw, qx, qy, qz, tx, ty, tz):
    rotation = quaternion_to_rotation_matrix(qw, qx, qy, qz)
    translation = [tx, ty, tz]
    rotation_t = [
        [rotation[0][0], rotation[1][0], rotation[2][0]],
        [rotation[0][1], rotation[1][1], rotation[2][1]],
        [rotation[0][2], rotation[1][2], rotation[2][2]],
    ]
    center = [
        -(rotation_t[0][0] * translation[0] + rotation_t[0][1] * translation[1] + rotation_t[0][2] * translation[2]),
        -(rotation_t[1][0] * translation[0] + rotation_t[1][1] * translation[1] + rotation_t[1][2] * translation[2]),
        -(rotation_t[2][0] * translation[0] + rotation_t[2][1] * translation[1] + rotation_t[2][2] * translation[2]),
    ]
    return [
        [rotation_t[0][0], rotation_t[0][1], rotation_t[0][2], center[0]],
        [rotation_t[1][0], rotation_t[1][1], rotation_t[1][2], center[1]],
        [rotation_t[2][0], rotation_t[2][1], rotation_t[2][2], center[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def camera_intrinsics_from_colmap(model_name: str, width: int, height: int, params: list[float]):
    if model_name in {"SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL", "SIMPLE_RADIAL_FISHEYE"} and len(params) >= 3:
        f, cx, cy = params[:3]
        fx = fy = f
    elif model_name in {"PINHOLE", "OPENCV", "OPENCV_FISHEYE", "FULL_OPENCV"} and len(params) >= 4:
        fx, fy, cx, cy = params[:4]
    else:
        fx = fy = max(width, height) * 1.2
        cx = width / 2.0
        cy = height / 2.0
    return [
        [float(fx), 0.0, float(cx)],
        [0.0, float(fy), float(cy)],
        [0.0, 0.0, 1.0],
    ]


def export_colmap_camera_prior(model_dir: Path, output_path: Path, *, colmap_bin: str = "colmap") -> bool:
    if not model_dir.exists():
        return False
    export_dir = output_path.parent / "_colmap_txt"
    export_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            colmap_bin,
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
        return False

    cameras_txt = export_dir / "cameras.txt"
    images_txt = export_dir / "images.txt"
    if not cameras_txt.exists() or not images_txt.exists():
        return False

    cameras = {}
    with cameras_txt.open() as handle:
        for line in handle:
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            camera_id = int(parts[0])
            model_name = parts[1]
            width = int(parts[2])
            height = int(parts[3])
            params = [float(value) for value in parts[4:]]
            cameras[camera_id] = {
                "model_name": model_name,
                "width": width,
                "height": height,
                "params": params,
            }

    extrinsics = []
    intrinsics = []
    with images_txt.open() as handle:
        for line in handle:
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 10:
                continue
            if "." in parts[0]:
                continue
            image_id = int(parts[0])
            qw, qx, qy, qz = map(float, parts[1:5])
            tx, ty, tz = map(float, parts[5:8])
            camera_id = int(parts[8])
            name = Path(" ".join(parts[9:])).stem
            c2w = colmap_pose_to_c2w(qw, qx, qy, qz, tx, ty, tz)
            cam = cameras.get(camera_id)
            intr = camera_intrinsics_from_colmap(
                cam["model_name"],
                cam["width"],
                cam["height"],
                cam["params"],
            ) if cam else [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ]
            extrinsics.append({"camera_id": name or image_id, "matrix": c2w})
            intrinsics.append({"camera_id": name or image_id, "matrix": intr})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "num_cameras": len(extrinsics),
        "extrinsics": extrinsics,
        "intrinsics": intrinsics,
    }, indent=2), encoding="utf-8")

    shutil.rmtree(export_dir, ignore_errors=True)
    return True


def session_input_sources(session: Session) -> dict:
    assets = session.assets.order_by(Asset.id.asc()).all()
    videos = []
    images = []
    for asset in assets:
        entry = {
            "asset_id": asset.id,
            "filename": asset.original_filename,
            "storage_path": asset.storage_path,
            "absolute_path": get_absolute_path(asset.storage_path),
        }
        if asset.type == "video":
            videos.append(entry)
        elif asset.type == "image":
            images.append(entry)
    prepared_dir = get_absolute_path(f"derived/reconstruction_sets/session_{session.id:04d}/images")
    return {
        "videos": videos,
        "images": images,
        "prepared_dir": prepared_dir if prepared_dir.exists() else None,
    }


def symlink_file(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    dest.symlink_to(source)
