#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
MAP3D_DIR = ROOT_DIR / "map3d"
if str(MAP3D_DIR) not in sys.path:
    sys.path.insert(0, str(MAP3D_DIR))

from app import create_app, db  # noqa: E402
from app.model_tools import (  # noqa: E402
    MODEL_BACKENDS,
    export_colmap_camera_prior,
    model_reconstruction_root,
    model_workspace_dir,
    session_input_sources,
    symlink_file,
)
from app.storage import get_absolute_path  # noqa: E402
from app.models import Session  # noqa: E402
from job_tools import filter_jobs, iter_session_jobs, _session_location_names  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare experimental model-based map3d reconstructions.")
    parser.add_argument("--session", type=int, help="Session id to package")
    parser.add_argument("--building", default="", help="Filter by building name fragment")
    parser.add_argument("--location", default="", help="Filter by location name fragment")
    parser.add_argument("--tag", default="", help="Filter by tag fragment")
    parser.add_argument("--list", action="store_true", help="List matching jobs instead of preparing them")
    parser.add_argument("--backend", choices=MODEL_BACKENDS, default="hyworld", help="Experimental model backend")
    parser.add_argument("--input-mode", choices=["auto", "video", "frames", "images"], default="auto", help="Preferred input source")
    parser.add_argument("--execute", action="store_true", help="Run the generated backend command after preparing the workspace")
    parser.add_argument("--force", action="store_true", help="Replace any existing model workspace")
    parser.add_argument("--target-size", type=int, default=952, help="Backend target longest-edge resolution")
    parser.add_argument("--fps", type=int, default=1, help="Video fps for HY-World video extraction")
    parser.add_argument("--video-strategy", choices=["new", "old"], default="new", help="HY-World video extraction strategy")
    parser.add_argument("--video-max-frames", type=int, default=32, help="HY-World maximum extracted frames from video")
    parser.add_argument("--use-fsdp", action="store_true", help="Generate multi-GPU HY-World command")
    parser.add_argument("--enable-bf16", action="store_true", help="Enable bf16 in generated HY-World command")
    parser.add_argument("--small-vram", action="store_true", help="Use safer HY-World defaults for low-VRAM GPUs")
    parser.add_argument("--save-rendered", action="store_true", help="Ask HY-World to render an interpolated fly-through")
    parser.add_argument("--disable-heads", default="", help="Space/comma separated HY-World heads to disable")
    return parser.parse_args()


def slug_bool(value: bool) -> str:
    return "true" if value else "false"


def choose_input(session: Session, input_mode: str):
    sources = session_input_sources(session)
    videos = sources["videos"]
    prepared_dir = sources["prepared_dir"]
    images = sources["images"]

    if input_mode == "video":
        if not videos:
            raise ValueError("requested video input, but session has no video asset")
        return {"kind": "video", "path": videos[0]["absolute_path"], "source": videos[0]}
    if input_mode == "frames":
        if not prepared_dir:
            raise ValueError("requested prepared frames, but session has no prepared reconstruction set")
        return {"kind": "frames", "path": prepared_dir}
    if input_mode == "images":
        if not images:
            raise ValueError("requested raw images, but session has no image assets")
        return {"kind": "images", "items": images}

    if videos:
        return {"kind": "video", "path": videos[0]["absolute_path"], "source": videos[0]}
    if prepared_dir:
        return {"kind": "frames", "path": prepared_dir}
    if images:
        return {"kind": "images", "items": images}
    raise ValueError("session has no usable video or image input")


def write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def create_hyworld_run_script(workspace_dir: Path, manifest: dict, args: argparse.Namespace) -> str:
    output_root = workspace_dir / "outputs"
    result_dir = output_root / "result"
    input_path = manifest["input"]["prepared_path"]
    prior_cam_path = workspace_dir / "priors" / "colmap_camera_params.json"
    configured_repo = os.environ.get("HYWORLD_REPO", "")
    configured_python = os.environ.get("HYWORLD_PYTHON", "")
    disabled = [token for token in args.disable_heads.replace(",", " ").split() if token]
    disable_heads = " ".join(disabled)
    runtime = hyworld_runtime_settings(args)
    target_size = runtime["target_size"]
    video_max_frames = runtime["video_max_frames"]
    enable_bf16 = runtime["enable_bf16"]

    run_module = "python3 -m hyworld2.worldrecon.pipeline"
    if args.use_fsdp:
        run_module = 'torchrun --nproc_per_node "${HYWORLD_NPROC_PER_NODE:-2}" -m hyworld2.worldrecon.pipeline'

    extra_flags = []
    if enable_bf16:
        extra_flags.append("--enable_bf16")
    if args.use_fsdp:
        extra_flags.append("--use_fsdp")
    if args.save_rendered:
        extra_flags.append("--save_rendered")
    if disabled:
        extra_flags.append(f"--disable_heads {disable_heads}")
    extra_flags.append("--save_colmap")
    extra_flags.append("--no_interactive")
    extra_flags.append("--fsdp_cpu_offload")

    if manifest["input"]["kind"] == "video":
        extra_flags.append(f"--fps {args.fps}")
        extra_flags.append(f"--video_strategy {args.video_strategy}")
        extra_flags.append(f"--video_max_frames {video_max_frames}")

    extra_text = " \\\n  ".join(extra_flags)
    maybe_prior = ""
    use_prior = prior_cam_path.exists() and manifest["input"]["kind"] != "video"
    if use_prior:
        maybe_prior = f"""if [[ \"${{HYWORLD_USE_CAMERA_PRIOR:-1}}\" != \"0\" ]]; then
  CMD+=(--prior_cam_path "{prior_cam_path}")
fi
"""

    return f"""#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="{workspace_dir}"
OUTPUT_ROOT="{output_root}"
RESULT_DIR="{result_dir}"
INPUT_PATH="{input_path}"
CONFIGURED_HYWORLD_REPO="{configured_repo}"
CONFIGURED_HYWORLD_PYTHON="{configured_python}"

mkdir -p "$OUTPUT_ROOT" "$RESULT_DIR" "$WORKSPACE_DIR/logs"

if [[ -n "${{HYWORLD_REPO:-}}" ]]; then
  export PYTHONPATH="${{HYWORLD_REPO}}:${{PYTHONPATH:-}}"
elif [[ -n "$CONFIGURED_HYWORLD_REPO" ]]; then
  export PYTHONPATH="$CONFIGURED_HYWORLD_REPO:${{PYTHONPATH:-}}"
fi

PYTHON_BIN="${{HYWORLD_PYTHON:-${{CONFIGURED_HYWORLD_PYTHON:-python3}}}}"
RUN_CMD=(bash -lc)
export PYTORCH_CUDA_ALLOC_CONF="${{PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}}"
CMD=($PYTHON_BIN -m hyworld2.worldrecon.pipeline
  --input_path "$INPUT_PATH"
  --output_path "$OUTPUT_ROOT"
  --strict_output_path "$RESULT_DIR"
  --target_size "{target_size}"
  {extra_text}
)
{maybe_prior}printf 'Running HY-World in %s\\n' "$WORKSPACE_DIR"
printf 'Input: %s\\n' "$INPUT_PATH"
printf 'Output: %s\\n' "$RESULT_DIR"
printf 'Runtime budget: target_size=%s, video_max_frames=%s, bf16=%s, input_kind=%s\\n' "{target_size}" "{video_max_frames if manifest['input']['kind'] == 'video' else 'n/a'}" "{str(enable_bf16).lower()}" "{manifest['input']['kind']}"
printf 'FlashAttention disabled: %s\\n' "${{HYWORLD_DISABLE_FLASH_ATTN:-0}}"
"${{CMD[@]}}" "$@"
"""


def hyworld_runtime_settings(args: argparse.Namespace) -> dict:
    target_size = args.target_size
    video_max_frames = args.video_max_frames
    enable_bf16 = args.enable_bf16
    if args.small_vram:
        target_size = min(target_size, 512)
        video_max_frames = min(video_max_frames, 8)
        enable_bf16 = True
    return {
        "target_size": target_size,
        "video_max_frames": video_max_frames,
        "enable_bf16": enable_bf16,
        "small_vram": args.small_vram,
    }


def create_lyra_run_script(workspace_dir: Path, manifest: dict) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="{workspace_dir}"
cat <<'EOF'
Lyra packaging has been prepared for this session, but automatic execution is not wired in TRACK yet.

Prepared inputs:
  {manifest["input"]["prepared_path"]}

Suggested next step:
  1. Point a Lyra checkout or environment at this workspace.
  2. Run the appropriate Lyra inference command against the prepared input.
  3. Save outputs under:
     {workspace_dir}/outputs/result
EOF
exit 2
"""


def prepare_workspace(session: Session, args: argparse.Namespace, app, *, execute: bool = False) -> dict:
    data_dir = Path(app.config["DATA_DIR"])
    workspace_dir = model_workspace_dir(data_dir, session.id, args.backend)
    if workspace_dir.exists():
        if not args.force:
            return {
                "session_id": session.id,
                "backend": args.backend,
                "workspace": str(workspace_dir),
                "status": "exists",
            }
        shutil.rmtree(workspace_dir, ignore_errors=True)

    input_spec = choose_input(session, args.input_mode)
    (workspace_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (workspace_dir / "outputs" / "result").mkdir(parents=True, exist_ok=True)
    (workspace_dir / "logs").mkdir(parents=True, exist_ok=True)
    (workspace_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (workspace_dir / "priors").mkdir(parents=True, exist_ok=True)
    (workspace_dir / "references").mkdir(parents=True, exist_ok=True)

    prepared_input_path: Path
    if input_spec["kind"] == "video":
        src = Path(input_spec["path"])
        dest = workspace_dir / "inputs" / "video" / src.name
        symlink_file(src, dest)
        prepared_input_path = dest
    elif input_spec["kind"] == "frames":
        src_dir = Path(input_spec["path"])
        dest_dir = workspace_dir / "inputs" / "images"
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted(src_dir.iterdir()):
            if src.is_file() or src.is_symlink():
                symlink_file(src.resolve(), dest_dir / src.name)
        prepared_input_path = dest_dir
    else:
        dest_dir = workspace_dir / "inputs" / "images"
        dest_dir.mkdir(parents=True, exist_ok=True)
        for item in input_spec["items"]:
            symlink_file(Path(item["absolute_path"]), dest_dir / Path(item["filename"]).name)
        prepared_input_path = dest_dir

    selection_path = get_absolute_path(f"derived/reconstruction_sets/session_{session.id:04d}/selection.json")
    if selection_path.exists():
        symlink_file(selection_path, workspace_dir / "references" / "selection.json")

    sparse_model_dir = get_absolute_path(f"derived/reconstructions/session_{session.id:04d}/sparse/0")
    prior_camera_path = workspace_dir / "priors" / "colmap_camera_params.json"
    local_cuda_bin = ROOT_DIR / "tmp-colmap-build" / "pkgroot" / "opt" / "colmap-cuda" / "bin" / "colmap"
    colmap_bin = os.environ.get("COLMAP_BIN", str(local_cuda_bin if local_cuda_bin.exists() else "colmap"))
    has_prior = export_colmap_camera_prior(sparse_model_dir, prior_camera_path, colmap_bin=colmap_bin) if sparse_model_dir.exists() else False

    manifest = {
        "backend": args.backend,
        "session_id": session.id,
        "session_label": session.label,
        "building_name": session.building.name if session.building else "",
        "source_type": session.source_type,
        "locations": _session_location_names(session),
        "input": {
            "requested_mode": args.input_mode,
            "kind": input_spec["kind"],
            "prepared_path": str(prepared_input_path),
        },
        "priors": {
            "colmap_camera_path": str(prior_camera_path) if has_prior else "",
            "usable_for_input": bool(has_prior and input_spec["kind"] != "video"),
        },
        "workspace_dir": str(workspace_dir),
        "status": "prepared",
    }
    if args.backend == "hyworld":
        runtime = hyworld_runtime_settings(args)
        manifest["hyworld"] = {
            "small_vram": runtime["small_vram"],
            "target_size": runtime["target_size"],
            "video_max_frames": runtime["video_max_frames"],
            "enable_bf16": runtime["enable_bf16"],
        }
    if input_spec.get("source"):
        manifest["input"]["source_asset_id"] = input_spec["source"]["asset_id"]
        manifest["input"]["source_storage_path"] = input_spec["source"]["storage_path"]

    job_path = workspace_dir / "job.json"
    job_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_status(workspace_dir / "status.json", {
        "status": "prepared",
        "backend": args.backend,
        "session_id": session.id,
    })

    if args.backend == "hyworld":
        script_text = create_hyworld_run_script(workspace_dir, manifest, args)
    else:
        script_text = create_lyra_run_script(workspace_dir, manifest)
    run_script = workspace_dir / "scripts" / "run-backend.sh"
    run_script.write_text(script_text, encoding="utf-8")
    run_script.chmod(0o755)

    readme = workspace_dir / "README.md"
    readme.write_text(
        "\n".join([
            f"# Experimental Model Reconstruction: {args.backend}",
            "",
            f"Session: {session.id:04d}",
            f"Building: {session.building.name if session.building else 'Unknown'}",
            f"Input kind: {input_spec['kind']}",
            "",
            "Outputs land under `outputs/result/`.",
            "Run the generated backend script when compute is available:",
            f"",
            f"```bash",
            f"{run_script}",
            f"```",
            "",
            "This workspace is an experimental representation layer. Original media remains the source of truth.",
        ]),
        encoding="utf-8",
    )

    if execute:
        write_status(workspace_dir / "status.json", {
            "status": "running",
            "backend": args.backend,
            "session_id": session.id,
        })
        log_path = workspace_dir / "logs" / "run.log"
        with log_path.open("ab") as log_handle:
            result = subprocess.run([str(run_script)], cwd=workspace_dir, stdout=log_handle, stderr=subprocess.STDOUT, check=False)
        write_status(workspace_dir / "status.json", {
            "status": "completed" if result.returncode == 0 else "failed",
            "backend": args.backend,
            "session_id": session.id,
            "exit_code": result.returncode,
        })

    return {
        "session_id": session.id,
        "backend": args.backend,
        "workspace": str(workspace_dir),
        "input_kind": input_spec["kind"],
        "prepared_input": str(prepared_input_path),
        "has_camera_prior": has_prior,
        "uses_camera_prior": bool(has_prior and input_spec["kind"] != "video"),
        "run_script": str(run_script),
        "status": "prepared",
    }


def main() -> int:
    args = parse_args()
    app = create_app()
    with app.app_context():
        jobs = filter_jobs(
            iter_session_jobs(Path(app.config["DATA_DIR"])),
            building_filter=args.building,
            location_filter=args.location,
            tag_filter=args.tag,
            need="any",
        )
        if args.session is not None:
            jobs = [job for job in jobs if job.session_id == args.session] or [
                job for job in iter_session_jobs(Path(app.config["DATA_DIR"])) if job.session_id == args.session
            ]
        if args.list:
            if not jobs:
                print("No matching jobs.")
                return 0
            for job in jobs:
                print(
                    f"{job.session_id:04d} {job.source_type:<14} {job.building_name or '-'} :: "
                    f"{', '.join(job.location_names) or '-'}"
                )
            return 0
        if not jobs:
            print("No matching jobs.")
            return 0
        results = []
        for job in jobs:
            session = db.session.get(Session, job.session_id)
            results.append(prepare_workspace(session, args, app, execute=args.execute))
        print(json.dumps(results[0] if len(results) == 1 else results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
