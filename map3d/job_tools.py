import json
import re
from dataclasses import dataclass
from pathlib import Path

from app import db
from app.models import Asset, Frame, Location, Observation, Session
from app.video_pipeline import parse_asset_metadata


def slugify(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


@dataclass
class SessionJob:
    session_id: int
    label: str
    building_name: str
    building_slug: str
    source_type: str
    capture_mode: str
    image_count: int
    video_count: int
    location_names: list[str]
    location_slugs: list[str]
    processable: bool
    prepared: bool
    reconstructed: bool
    set_name: str
    set_names: list[str]
    tags: list[str]


def _selection_map(data_dir: Path) -> dict[int, list[str]]:
    selection_root = data_dir / "derived" / "reconstruction_sets"
    selections: dict[int, list[str]] = {}
    if not selection_root.exists():
        return selections
    for path in selection_root.iterdir():
        if not path.is_dir():
            continue
        selection_path = path / "selection.json"
        if not selection_path.exists():
            continue
        try:
            data = json.loads(selection_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        session_id = data.get("session_id")
        if session_id is None:
            continue
        selections.setdefault(int(session_id), []).append(path.name)
    return selections


def _reconstructed_names(data_dir: Path) -> set[str]:
    recon_root = data_dir / "derived" / "reconstructions"
    names: set[str] = set()
    if not recon_root.exists():
        return names
    for path in recon_root.iterdir():
        sparse = path / "sparse"
        if not path.is_dir() or not sparse.exists():
            continue
        if any((child / "points3D.bin").exists() for child in sparse.iterdir() if child.is_dir()):
            names.add(path.name)
    return names


def _session_location_names(session: Session) -> list[str]:
    names: set[str] = set()
    rows = (
        db.session.query(Location.name)
        .join(Observation, Observation.assigned_location_id == Location.id)
        .join(Frame, Frame.id == Observation.frame_id)
        .join(Asset, Asset.id == Frame.asset_id)
        .filter(Asset.session_id == session.id)
        .distinct()
        .all()
    )
    for (name,) in rows:
        if name:
            names.add(name)
    for asset in session.assets.all():
        if asset.type != "video":
            continue
        metadata = parse_asset_metadata(asset)
        location_id = metadata.get("default_location_id")
        if not location_id:
            continue
        location = db.session.get(Location, int(location_id))
        if location and location.name:
            names.add(location.name)
    return sorted(names)


def _job_tags(session: Session, building_slug: str, location_slugs: list[str], video_count: int) -> list[str]:
    tags = [
        f"session:{session.id:04d}",
        f"building:{building_slug}" if building_slug else "building:unknown",
        f"type:{slugify(session.source_type or 'unknown')}",
    ]
    if session.capture_mode:
        tags.append(f"mode:{slugify(session.capture_mode)}")
        tags.append(slugify(session.capture_mode))
    if video_count:
        tags.append("video")
        tags.append("type:video")
    for location_slug in location_slugs:
        tags.append(f"location:{location_slug}")
    return sorted(dict.fromkeys(tag for tag in tags if tag))


def iter_session_jobs(data_dir: Path) -> list[SessionJob]:
    selections = _selection_map(data_dir)
    reconstructed_names = _reconstructed_names(data_dir)
    jobs: list[SessionJob] = []
    for session in Session.query.order_by(Session.id.asc()).all():
        assets = session.assets.all()
        image_count = sum(1 for asset in assets if asset.type == "image")
        video_count = sum(1 for asset in assets if asset.type == "video")
        location_names = _session_location_names(session)
        location_slugs = [slugify(name) for name in location_names if slugify(name)]
        building_name = session.building.name if session.building else ""
        building_slug = slugify(building_name)
        default_set_name = f"session_{session.id:04d}"
        set_names = selections.get(session.id, [])
        prepared = default_set_name in set_names or bool(set_names)
        primary_set_name = default_set_name if default_set_name in set_names else (set_names[0] if set_names else default_set_name)
        reconstructed = primary_set_name in reconstructed_names
        processable = bool(video_count or image_count >= 2 or session.capture_mode == "burst")
        jobs.append(SessionJob(
            session_id=session.id,
            label=session.label or default_set_name,
            building_name=building_name,
            building_slug=building_slug,
            source_type=session.source_type or "",
            capture_mode=session.capture_mode or "",
            image_count=image_count,
            video_count=video_count,
            location_names=location_names,
            location_slugs=location_slugs,
            processable=processable,
            prepared=prepared,
            reconstructed=reconstructed,
            set_name=primary_set_name,
            set_names=set_names,
            tags=_job_tags(session, building_slug, location_slugs, video_count),
        ))
    return jobs


def filter_jobs(
    jobs: list[SessionJob],
    *,
    building_filter: str = "",
    location_filter: str = "",
    tag_filter: str = "",
    need: str = "any",
) -> list[SessionJob]:
    building_filter = slugify(building_filter)
    location_filter = slugify(location_filter)
    tag_filter = slugify(tag_filter.replace(":", "-"))

    filtered: list[SessionJob] = []
    for job in jobs:
        if not job.processable:
            continue
        if building_filter and building_filter not in job.building_slug:
            continue
        if location_filter:
            if not any(location_filter in slug for slug in job.location_slugs):
                continue
        if tag_filter:
            comparable_tags = [slugify(tag.replace(":", "-")) for tag in job.tags]
            if not any(tag_filter in tag for tag in comparable_tags):
                continue
        if need == "prepare" and job.prepared:
            continue
        if need == "reconstruct" and job.reconstructed:
            continue
        filtered.append(job)
    return filtered
