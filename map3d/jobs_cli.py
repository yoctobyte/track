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
from job_tools import filter_jobs, iter_session_jobs  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List or select map3d processing jobs.")
    parser.add_argument("--building", default="", help="Filter by building name fragment")
    parser.add_argument("--location", default="", help="Filter by location name fragment")
    parser.add_argument("--tag", default="", help="Filter by tag fragment")
    parser.add_argument("--need", choices=["any", "prepare", "reconstruct"], default="any")
    parser.add_argument("--ids-only", action="store_true", help="Print matching session ids only")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a text table")
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
            need=args.need,
        )
    if args.ids_only:
        for job in jobs:
            print(f"{job.session_id:04d}")
        return 0
    if args.json:
        print(json.dumps([
            {
                "session_id": job.session_id,
                "label": job.label,
                "building": job.building_name,
                "locations": job.location_names,
                "source_type": job.source_type,
                "capture_mode": job.capture_mode,
                "images": job.image_count,
                "videos": job.video_count,
                "prepared": job.prepared,
                "reconstructed": job.reconstructed,
                "set_name": job.set_name,
                "tags": job.tags,
            }
            for job in jobs
        ], indent=2))
        return 0
    if not jobs:
        print("No matching jobs.")
        return 0
    print("session  state  source         media        building        locations             tags")
    for job in jobs:
        if job.reconstructed:
            state = "recon"
        elif job.prepared:
            state = "ready"
        else:
            state = "new"
        media = []
        if job.image_count:
            media.append(f"{job.image_count}img")
        if job.video_count:
            media.append(f"{job.video_count}vid")
        location_text = ",".join(job.location_slugs[:2]) or "-"
        tag_text = ",".join(job.tags[:4])
        print(
            f"{job.session_id:04d}   {state:<5}  {job.source_type[:12]:<12}  "
            f"{'/'.join(media):<11}  {job.building_slug[:14]:<14}  "
            f"{location_text[:20]:<20}  {tag_text}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
