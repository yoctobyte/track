#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
MAP3D_DIR = ROOT_DIR / "map3d"
if str(MAP3D_DIR) not in sys.path:
    sys.path.insert(0, str(MAP3D_DIR))

from app import create_app  # noqa: E402
from app.video_pipeline import build_session_reconstruction_set  # noqa: E402
from job_tools import filter_jobs, iter_session_jobs  # noqa: E402


def make_progress_reporter(job_label: str):
    last_text = ""

    def report(*, stage: str, current=0, total=0, message="", done=False):
        nonlocal last_text
        prefix = f"[prepare {job_label}] "
        text = prefix + (message or stage)
        if total and current:
            text += f" [{current}/{total}]"
        padded = text
        if len(last_text) > len(text):
            padded += " " * (len(last_text) - len(text))
        print("\r" + padded, end="\n" if done else "", file=sys.stderr, flush=True)
        last_text = text if not done else ""

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a map3d session for reconstruction.")
    parser.add_argument("--session", type=int, help="Session id to prepare")
    parser.add_argument("--name", default="", help="Output reconstruction-set name")
    parser.add_argument("--force", action="store_true", help="Replace existing prepared set and extracted frames")
    parser.add_argument("--candidate-fps", type=float, default=None, help="Candidate extraction fps override")
    parser.add_argument("--target-fps", type=float, default=None, help="Target kept fps override")
    parser.add_argument("--building", default="", help="Filter by building name fragment")
    parser.add_argument("--location", default="", help="Filter by location name fragment")
    parser.add_argument("--tag", default="", help="Filter by tag fragment")
    parser.add_argument("--list", action="store_true", help="List matching jobs instead of preparing them")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    app = create_app()
    with app.app_context():
        jobs = filter_jobs(
            iter_session_jobs(Path(app.config["DATA_DIR"])),
            building_filter=args.building,
            location_filter=args.location,
            tag_filter=args.tag,
            need="any" if args.force else "prepare",
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
                state = "ready" if job.prepared else "new"
                print(
                    f"{job.session_id:04d} {state:<5} {job.source_type:<14} "
                    f"{job.building_name or '-'} :: {', '.join(job.location_names) or '-'}"
                )
            return 0
        if not jobs:
            print("No matching jobs to prepare.")
            return 0
        results = []
        for job in jobs:
            set_name = args.name if len(jobs) == 1 and args.name else None
            reporter = make_progress_reporter(f"{job.session_id:04d}")
            result = build_session_reconstruction_set(
                job.session_id,
                set_name=set_name,
                force=args.force,
                candidate_fps=args.candidate_fps,
                target_fps=args.target_fps,
                progress=reporter,
            )
            results.append({
                "session_id": job.session_id,
                "images_dir": str(result["images_dir"]),
                "set_dir": str(result["set_dir"]),
                "selection": result["selection"],
            })
        print(json.dumps(results[0] if len(results) == 1 else results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
