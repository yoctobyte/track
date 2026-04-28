#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pymeshlab as ml


def main() -> int:
    parser = argparse.ArgumentParser(description="Texture a mesh from registered rasters using PyMeshLab.")
    parser.add_argument("--mesh", required=True, help="Input mesh path")
    parser.add_argument("--bundle", required=True, help="Bundler .out camera file")
    parser.add_argument("--list", required=True, help="Bundler list.txt with image paths")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--texture-size", type=int, default=4096, help="Square texture atlas size")
    parser.add_argument("--texture-name", default="texture.png", help="Texture atlas filename")
    parser.add_argument("--mesh-name", default="textured.obj", help="Output mesh filename")
    parser.add_argument("--save-project", action="store_true", help="Save a MeshLab .mlp project for debugging")
    args = parser.parse_args()

    mesh_path = Path(args.mesh).resolve()
    bundle_path = Path(args.bundle).resolve()
    list_path = Path(args.list).resolve()
    output_dir = Path(args.output_dir).resolve()
    texture_name = Path(args.texture_name).name
    mesh_name = Path(args.mesh_name).name

    if not mesh_path.is_file():
        raise SystemExit(f"mesh not found: {mesh_path}")
    if not bundle_path.is_file():
        raise SystemExit(f"bundle file not found: {bundle_path}")
    if not list_path.is_file():
        raise SystemExit(f"bundler list not found: {list_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    ms = ml.MeshSet()
    ms.load_project([str(bundle_path), str(list_path)])
    ms.load_new_mesh(str(mesh_path))

    if args.save_project:
        ms.save_project(str(output_dir / "texturing_setup.mlp"))

    ms.compute_texcoord_parametrization_and_texture_from_registered_rasters(
        texturesize=args.texture_size,
        texturename=texture_name,
        colorcorrection=True,
        colorcorrectionfiltersize=1,
        usedistanceweight=True,
        useimgborderweight=True,
        usealphaweight=False,
        cleanisolatedtriangles=True,
        stretchingallowed=False,
        texturegutter=4,
    )
    ms.save_current_mesh(str(output_dir / mesh_name), save_textures=True, texture_quality=95)

    output_mesh = output_dir / mesh_name
    output_texture = output_dir / texture_name
    print(f"mesh={output_mesh}")
    print(f"texture={output_texture}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
