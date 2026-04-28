#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh
import xatlas
from PIL import Image


@dataclass
class Camera:
    camera_id: int
    model: str
    width: int
    height: int
    params: list[float]

    @property
    def fx(self) -> float:
        return self.params[0]

    @property
    def fy(self) -> float:
        return self.params[0]

    @property
    def cx(self) -> float:
        return self.params[1]

    @property
    def cy(self) -> float:
        return self.params[2]

    @property
    def k1(self) -> float:
        return self.params[3] if len(self.params) > 3 else 0.0


@dataclass
class ImagePose:
    image_id: int
    camera_id: int
    name: str
    qw: float
    qx: float
    qy: float
    qz: float
    tx: float
    ty: float
    tz: float

    @property
    def qvec(self) -> np.ndarray:
        return np.array([self.qw, self.qx, self.qy, self.qz], dtype=np.float64)

    @property
    def tvec(self) -> np.ndarray:
        return np.array([self.tx, self.ty, self.tz], dtype=np.float64)


def qvec_to_rotmat(qvec: np.ndarray) -> np.ndarray:
    w, x, y, z = qvec
    return np.array(
        [
            [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y],
            [2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x],
            [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y],
        ],
        dtype=np.float64,
    )


def parse_cameras(path: Path) -> dict[int, Camera]:
    cameras: dict[int, Camera] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        camera_id = int(parts[0])
        model = parts[1]
        width = int(parts[2])
        height = int(parts[3])
        params = [float(v) for v in parts[4:]]
        cameras[camera_id] = Camera(camera_id, model, width, height, params)
    return cameras


def parse_images(path: Path) -> list[ImagePose]:
    lines = path.read_text().splitlines()
    poses: list[ImagePose] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        poses.append(
            ImagePose(
                image_id=int(parts[0]),
                qw=float(parts[1]),
                qx=float(parts[2]),
                qy=float(parts[3]),
                qz=float(parts[4]),
                tx=float(parts[5]),
                ty=float(parts[6]),
                tz=float(parts[7]),
                camera_id=int(parts[8]),
                name=parts[9],
            )
        )
        # Skip points2D line.
        if i < len(lines):
            i += 1
    return poses


def project_points(points: np.ndarray, camera: Camera, pose: ImagePose) -> tuple[np.ndarray, np.ndarray]:
    rmat = qvec_to_rotmat(pose.qvec)
    pc = (rmat @ points.T).T + pose.tvec
    z = pc[:, 2].copy()
    valid = z > 1e-6
    uv = np.full((points.shape[0], 2), np.nan, dtype=np.float64)
    if not np.any(valid):
        return uv, valid

    xy = pc[valid, :2] / z[valid, None]
    if camera.model in {"SIMPLE_RADIAL", "RADIAL"}:
        r2 = np.sum(xy * xy, axis=1)
        radial = 1.0 + camera.k1 * r2
        xy = xy * radial[:, None]
    uv_valid = np.empty_like(xy)
    uv_valid[:, 0] = camera.fx * xy[:, 0] + camera.cx
    uv_valid[:, 1] = camera.fy * xy[:, 1] + camera.cy
    uv[valid] = uv_valid
    return uv, valid


def compute_vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    normals = np.zeros_like(vertices, dtype=np.float64)
    tri = vertices[faces]
    face_normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    for corner in range(3):
        np.add.at(normals, faces[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1e-12
    normals[valid] /= lengths[valid, None]
    normals[~valid] = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    return normals.astype(np.float32)


def bilinear_sample(image: np.ndarray, uv: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    x = np.clip(uv[:, 0], 0.0, w - 1.001)
    y = np.clip(uv[:, 1], 0.0, h - 1.001)
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = np.clip(x0 + 1, 0, w - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)
    dx = (x - x0)[:, None]
    dy = (y - y0)[:, None]

    c00 = image[y0, x0].astype(np.float32)
    c10 = image[y0, x1].astype(np.float32)
    c01 = image[y1, x0].astype(np.float32)
    c11 = image[y1, x1].astype(np.float32)
    c0 = c00 * (1.0 - dx) + c10 * dx
    c1 = c01 * (1.0 - dx) + c11 * dx
    return c0 * (1.0 - dy) + c1 * dy


def triangle_area_2d(pts: np.ndarray) -> float:
    return abs(
        0.5
        * (
            pts[0, 0] * (pts[1, 1] - pts[2, 1])
            + pts[1, 0] * (pts[2, 1] - pts[0, 1])
            + pts[2, 0] * (pts[0, 1] - pts[1, 1])
        )
    )


def barycentric_coords(p: np.ndarray, tri: np.ndarray) -> np.ndarray:
    a = tri[0]
    b = tri[1]
    c = tri[2]
    v0 = b - a
    v1 = c - a
    v2 = p - a
    d00 = float(np.dot(v0, v0))
    d01 = float(np.dot(v0, v1))
    d11 = float(np.dot(v1, v1))
    d20 = np.einsum("ij,j->i", v2, v0)
    d21 = np.einsum("ij,j->i", v2, v1)
    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-12:
        return np.full((p.shape[0], 3), np.nan, dtype=np.float64)
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    u = 1.0 - v - w
    return np.stack([u, v, w], axis=1)


def choose_best_camera(
    tri_world: np.ndarray,
    normal: np.ndarray,
    cameras: dict[int, Camera],
    poses: list[ImagePose],
) -> tuple[ImagePose | None, np.ndarray | None]:
    centroid = tri_world.mean(axis=0)
    best_score = -math.inf
    best_pose: ImagePose | None = None
    best_uv: np.ndarray | None = None
    for pose in poses:
        camera = cameras.get(pose.camera_id)
        if camera is None:
            continue
        uv, valid = project_points(tri_world, camera, pose)
        if not np.all(valid):
            continue
        if np.any(uv[:, 0] < 2) or np.any(uv[:, 0] > camera.width - 3):
            continue
        if np.any(uv[:, 1] < 2) or np.any(uv[:, 1] > camera.height - 3):
            continue

        rmat = qvec_to_rotmat(pose.qvec)
        camera_center = -(rmat.T @ pose.tvec)
        view_dir = camera_center - centroid
        view_len = np.linalg.norm(view_dir)
        if view_len < 1e-6:
            continue
        view_dir = view_dir / view_len
        facing = abs(float(np.dot(normal, view_dir)))
        if facing < 0.05:
            continue

        area = triangle_area_2d(uv)
        if area < 8.0:
            continue
        margin = min(
            uv[:, 0].min(),
            uv[:, 1].min(),
            camera.width - uv[:, 0].max(),
            camera.height - uv[:, 1].max(),
        )
        score = area * (0.5 + facing) * (1.0 + min(margin, 80.0) / 160.0)
        if score > best_score:
            best_score = score
            best_pose = pose
            best_uv = uv
    return best_pose, best_uv


def rasterize_face(
    texture: np.ndarray,
    coverage: np.ndarray,
    tri_uv_px: np.ndarray,
    tri_src_uv: np.ndarray,
    image: np.ndarray,
) -> int:
    xmin = max(int(np.floor(tri_uv_px[:, 0].min())), 0)
    xmax = min(int(np.ceil(tri_uv_px[:, 0].max())), texture.shape[1] - 1)
    ymin = max(int(np.floor(tri_uv_px[:, 1].min())), 0)
    ymax = min(int(np.ceil(tri_uv_px[:, 1].max())), texture.shape[0] - 1)
    if xmax < xmin or ymax < ymin:
        return 0

    xs = np.arange(xmin, xmax + 1, dtype=np.float64) + 0.5
    ys = np.arange(ymin, ymax + 1, dtype=np.float64) + 0.5
    grid_x, grid_y = np.meshgrid(xs, ys)
    points = np.stack([grid_x.ravel(), grid_y.ravel()], axis=1)
    bary = barycentric_coords(points, tri_uv_px)
    inside = np.all(bary >= -1e-4, axis=1)
    if not np.any(inside):
        return 0

    bary = bary[inside]
    points = points[inside]
    src_uv = bary @ tri_src_uv
    colors = bilinear_sample(image, src_uv)

    xi = np.clip(np.floor(points[:, 0]).astype(np.int32), 0, texture.shape[1] - 1)
    yi = np.clip(np.floor(points[:, 1]).astype(np.int32), 0, texture.shape[0] - 1)
    texture[yi, xi] += colors
    coverage[yi, xi] += 1.0
    return int(inside.sum())


def write_obj(
    obj_path: Path,
    mtl_name: str,
    texture_name: str,
    vertices: np.ndarray,
    normals: np.ndarray,
    faces_v: np.ndarray,
    uvs: np.ndarray,
    faces_vt: np.ndarray,
) -> None:
    mtl_path = obj_path.with_suffix(".mtl")
    with mtl_path.open("w", encoding="utf-8") as mtl:
        mtl.write("newmtl material0\n")
        mtl.write("Ka 1.000000 1.000000 1.000000\n")
        mtl.write("Kd 1.000000 1.000000 1.000000\n")
        mtl.write("Ks 0.000000 0.000000 0.000000\n")
        mtl.write("d 1.0\n")
        mtl.write("illum 2\n")
        mtl.write(f"map_Kd {texture_name}\n")

    with obj_path.open("w", encoding="utf-8") as obj:
        obj.write(f"mtllib {mtl_name}\n")
        for v in vertices:
            obj.write(f"v {v[0]:.8f} {v[1]:.8f} {v[2]:.8f}\n")
        for vt in uvs:
            obj.write(f"vt {vt[0]:.8f} {1.0 - vt[1]:.8f}\n")
        for n in normals:
            obj.write(f"vn {n[0]:.8f} {n[1]:.8f} {n[2]:.8f}\n")
        obj.write("usemtl material0\n")
        for face_idx, face in enumerate(faces_v):
            vt_face = faces_vt[face_idx]
            obj.write(
                "f "
                + " ".join(
                    f"{int(face[i]) + 1}/{int(vt_face[i]) + 1}/{int(face[i]) + 1}" for i in range(3)
                )
                + "\n"
            )


def fill_uncovered(texture: np.ndarray, coverage: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    covered = coverage > 0
    out = texture.copy()
    if np.any(covered):
        out[covered] = out[covered] / coverage[covered, None]
    out[~covered] = fallback[~covered]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Bake a textured mesh from COLMAP cameras and prepared images.")
    parser.add_argument("--mesh", required=True, help="Input mesh path")
    parser.add_argument("--cameras", required=True, help="COLMAP cameras.txt path")
    parser.add_argument("--images", required=True, help="COLMAP images.txt path")
    parser.add_argument("--images-dir", required=True, help="Prepared images directory")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--texture-size", type=int, default=2048, help="Square texture size")
    parser.add_argument("--texture-name", default="texture.png", help="Texture image filename")
    parser.add_argument("--mesh-name", default="textured.obj", help="Output OBJ filename")
    parser.add_argument("--max-images", type=int, default=0, help="Optional cap on source images considered")
    parser.add_argument("--progress-every", type=int, default=1000, help="Emit progress every N faces")
    args = parser.parse_args()

    mesh_path = Path(args.mesh).resolve()
    cameras_path = Path(args.cameras).resolve()
    images_path = Path(args.images).resolve()
    images_dir = Path(args.images_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    mesh = trimesh.load_mesh(mesh_path, process=False)
    if not isinstance(mesh, trimesh.Trimesh):
        raise SystemExit(f"expected a triangle mesh at {mesh_path}")

    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.uint32)
    normals = compute_vertex_normals(vertices, faces)
    if vertices.size == 0 or faces.size == 0:
        raise SystemExit(f"mesh is empty: {mesh_path}")

    vmapping, atlas_indices, atlas_uvs = xatlas.parametrize(vertices, faces, normals)
    atlas_indices = np.asarray(atlas_indices, dtype=np.uint32)
    atlas_uvs = np.asarray(atlas_uvs, dtype=np.float32)
    atlas_vertices = vertices[np.asarray(vmapping, dtype=np.int64)]
    atlas_normals = normals[np.asarray(vmapping, dtype=np.int64)]

    cameras = parse_cameras(cameras_path)
    poses = parse_images(images_path)
    if args.max_images > 0:
        poses = poses[: args.max_images]

    texture_size = int(args.texture_size)
    texture_accum = np.zeros((texture_size, texture_size, 3), dtype=np.float32)
    coverage = np.zeros((texture_size, texture_size), dtype=np.float32)
    fallback = np.zeros((texture_size, texture_size, 3), dtype=np.float32)

    cache: dict[str, np.ndarray] = {}
    textured_faces = 0
    textured_pixels = 0

    tri_world_cache = atlas_vertices[atlas_indices]
    tri_normals = np.cross(
        tri_world_cache[:, 1] - tri_world_cache[:, 0],
        tri_world_cache[:, 2] - tri_world_cache[:, 0],
    )
    tri_norm_lengths = np.linalg.norm(tri_normals, axis=1)
    valid_normals = tri_norm_lengths > 1e-8
    tri_normals[valid_normals] = tri_normals[valid_normals] / tri_norm_lengths[valid_normals, None]
    tri_uv_px = atlas_uvs[atlas_indices] * float(texture_size - 1)

    if hasattr(mesh.visual, "vertex_colors") and len(mesh.visual.vertex_colors) == len(vertices):
        base_colors = np.asarray(mesh.visual.vertex_colors[:, :3], dtype=np.float32)
        face_colors = base_colors[np.asarray(vmapping, dtype=np.int64)][atlas_indices].mean(axis=1)
    else:
        face_colors = np.full((atlas_indices.shape[0], 3), 160.0, dtype=np.float32)

    for face_idx in range(atlas_indices.shape[0]):
        if args.progress_every > 0 and face_idx and face_idx % args.progress_every == 0:
            pct = int(round(face_idx * 100.0 / atlas_indices.shape[0]))
            print(
                f"[texture] faces {face_idx}/{atlas_indices.shape[0]} ({pct}%) textured={textured_faces}",
                file=sys.stderr,
                flush=True,
            )
        uv_px = tri_uv_px[face_idx]
        tri_world = tri_world_cache[face_idx]
        normal = tri_normals[face_idx]
        pose, src_uv = choose_best_camera(tri_world, normal, cameras, poses)

        xmin = max(int(np.floor(uv_px[:, 0].min())), 0)
        xmax = min(int(np.ceil(uv_px[:, 0].max())), texture_size - 1)
        ymin = max(int(np.floor(uv_px[:, 1].min())), 0)
        ymax = min(int(np.ceil(uv_px[:, 1].max())), texture_size - 1)
        if xmax < xmin or ymax < ymin:
            continue
        fallback[ymin : ymax + 1, xmin : xmax + 1] = face_colors[face_idx]

        if pose is None or src_uv is None:
            continue

        image_path = images_dir / pose.name
        if not image_path.is_file():
            continue
        if pose.name not in cache:
            cache[pose.name] = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.uint8)
        textured_pixels += rasterize_face(texture_accum, coverage, uv_px, src_uv, cache[pose.name])
        textured_faces += 1

    texture = fill_uncovered(texture_accum, coverage, fallback).clip(0, 255).astype(np.uint8)
    texture_path = output_dir / args.texture_name
    Image.fromarray(texture, mode="RGB").save(texture_path)

    mesh_path_out = output_dir / args.mesh_name
    write_obj(
        mesh_path_out,
        mtl_name=mesh_path_out.with_suffix(".mtl").name,
        texture_name=texture_path.name,
        vertices=atlas_vertices,
        normals=atlas_normals,
        faces_v=atlas_indices,
        uvs=atlas_uvs,
        faces_vt=atlas_indices,
    )

    print(f"mesh={mesh_path_out}")
    print(f"texture={texture_path}")
    print(f"textured_faces={textured_faces}")
    print(f"textured_pixels={textured_pixels}")
    print(f"total_faces={atlas_indices.shape[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
