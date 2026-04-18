import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from PIL import Image

from . import db
from .metadata import generate_preview
from .models import Asset, Frame, Observation, Session, utcnow
from .storage import get_absolute_path, store_extracted_frame, store_preview


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run_json_command(command: list[str]) -> dict:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "external command failed")
    return json.loads(result.stdout or "{}")


def _ffmpeg_thread_count() -> int:
    raw = os.environ.get("MAP3D_FFMPEG_THREADS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    cpu_total = os.cpu_count() or 2
    return max(1, cpu_total - 1)


def probe_video_metadata(video_path: Path) -> dict:
    if not ffmpeg_available():
        return {}

    data = _run_json_command([
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ])

    streams = data.get("streams") or []
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    duration = _safe_float((data.get("format") or {}).get("duration")) or _safe_float(video_stream.get("duration"))
    fps = _parse_fraction(video_stream.get("avg_frame_rate")) or _parse_fraction(video_stream.get("r_frame_rate"))
    return {
        "duration_seconds": duration,
        "fps": fps,
        "width": _safe_int(video_stream.get("width")),
        "height": _safe_int(video_stream.get("height")),
        "codec_name": video_stream.get("codec_name") or "",
        "bit_rate": _safe_int((data.get("format") or {}).get("bit_rate")),
        "rotation": _extract_rotation(video_stream),
        "format_name": (data.get("format") or {}).get("format_name") or "",
    }


def build_video_poster(video_path: Path, duration_seconds: float | None = None) -> bytes | None:
    if not ffmpeg_available():
        return None
    seek_seconds = 1.0
    if duration_seconds and duration_seconds > 4:
        seek_seconds = min(2.0, duration_seconds * 0.15)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{seek_seconds:.3f}",
        "-i",
        str(video_path),
        "-threads",
        str(_ffmpeg_thread_count()),
        "-frames:v",
        "1",
        "-vf",
        "scale='min(1280,iw)':-2",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        return None
    return result.stdout


def choose_auto_candidate_fps(duration_seconds: float | None, source_fps: float | None) -> float:
    if not duration_seconds or duration_seconds <= 0:
        target = 12.0
    elif duration_seconds <= 90:
        target = 16.0
    elif duration_seconds <= 240:
        target = 14.0
    elif duration_seconds <= 600:
        target = 12.0
    elif duration_seconds <= 1200:
        target = 10.0
    else:
        target = 8.0
    if source_fps:
        target = min(target, max(1.0, source_fps))
    return max(2.0, min(20.0, target))


def choose_auto_target_fps(duration_seconds: float | None) -> float:
    if not duration_seconds or duration_seconds <= 0:
        return 4.0
    if duration_seconds <= 90:
        return 5.0
    if duration_seconds <= 240:
        return 4.5
    if duration_seconds <= 600:
        return 4.0
    if duration_seconds <= 1200:
        return 3.5
    return 3.0


@dataclass
class CandidateFrame:
    path: Path
    seconds: float
    width: int
    height: int
    sharpness: float
    brightness: float
    fingerprint: list[int]
    source_pkt_size: int | None = None
    source_pkt_pos: int | None = None
    source_key_frame: bool = False
    source_pict_type: str = ""


@dataclass
class SourceFrameMetric:
    seconds: float
    pkt_pos: int | None
    pkt_size: int | None
    key_frame: bool
    pict_type: str


def extract_candidate_frames(
    video_path: Path,
    candidates_dir: Path,
    candidate_fps: float,
    max_width: int = 1920,
) -> list[Path]:
    candidates_dir.mkdir(parents=True, exist_ok=True)
    pattern = candidates_dir / "candidate_%06d.jpg"
    vf = f"fps={candidate_fps:.3f},scale='min({max_width},iw)':-2"
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-threads",
            str(_ffmpeg_thread_count()),
            "-vf",
            vf,
            "-q:v",
            "2",
            str(pattern),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg extraction failed")
    return sorted(candidates_dir.glob("candidate_*.jpg"))


def probe_source_frame_metrics(video_path: Path) -> list[SourceFrameMetric]:
    if not ffmpeg_available():
        return []
    data = _run_json_command([
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_frames",
        "-show_entries",
        "frame=best_effort_timestamp_time,pkt_pos,pkt_size,key_frame,pict_type",
        "-of",
        "json",
        str(video_path),
    ])
    metrics: list[SourceFrameMetric] = []
    for frame in data.get("frames") or []:
        seconds = _safe_float(frame.get("best_effort_timestamp_time"))
        if seconds is None:
            continue
        metrics.append(SourceFrameMetric(
            seconds=seconds,
            pkt_pos=_safe_int(frame.get("pkt_pos")),
            pkt_size=_safe_int(frame.get("pkt_size")),
            key_frame=bool(_safe_int(frame.get("key_frame"))),
            pict_type=str(frame.get("pict_type") or ""),
        ))
    return metrics


def attach_source_frame_metrics(candidates: list[CandidateFrame], source_metrics: list[SourceFrameMetric]) -> list[CandidateFrame]:
    if not candidates or not source_metrics:
        return candidates
    metric_index = 0
    metric_count = len(source_metrics)
    for candidate in candidates:
        while metric_index + 1 < metric_count:
            current = source_metrics[metric_index]
            nxt = source_metrics[metric_index + 1]
            if abs(nxt.seconds - candidate.seconds) <= abs(current.seconds - candidate.seconds):
                metric_index += 1
            else:
                break
        metric = source_metrics[metric_index]
        candidate.source_pkt_size = metric.pkt_size
        candidate.source_pkt_pos = metric.pkt_pos
        candidate.source_key_frame = metric.key_frame
        candidate.source_pict_type = metric.pict_type
    return candidates


def analyze_candidate_frames(candidate_paths: list[Path], candidate_fps: float, progress=None) -> list[CandidateFrame]:
    analyzed: list[CandidateFrame] = []
    total = len(candidate_paths)
    for index, path in enumerate(candidate_paths, start=1):
        with Image.open(path) as img:
            width, height = img.width, img.height
            thumb = img.convert("L")
            thumb.thumbnail((160, 160), Image.LANCZOS)
            pixels = list(thumb.getdata())
            w, h = thumb.size
        brightness = sum(pixels) / max(1, len(pixels))
        sharpness = _gradient_energy(pixels, w, h)
        fingerprint = _fingerprint_pixels(pixels, w, h)
        analyzed.append(CandidateFrame(
            path=path,
            seconds=(index - 1) / candidate_fps if candidate_fps > 0 else float(index - 1),
            width=width,
            height=height,
            sharpness=sharpness,
            brightness=brightness,
            fingerprint=fingerprint,
        ))
        if progress:
            progress(
                stage="analyze",
                current=index,
                total=total,
                message=f"analyzing {index}/{total} candidates",
            )
    return analyzed


def select_candidate_frames(
    candidates: list[CandidateFrame],
    target_fps: float,
    min_fps: float = 1.0,
    max_fps: float = 8.0,
) -> list[tuple[CandidateFrame, float]]:
    if not candidates:
        return []

    target_fps = max(min_fps, min(max_fps, target_fps))
    target_spacing = 1.0 / max(target_fps, 0.001)
    max_spacing = 1.0 / max(min_fps, 0.001)
    sharpness_scores = [candidate.sharpness for candidate in candidates if candidate.sharpness > 0]
    sharpness_floor = (median(sharpness_scores) * 0.55) if sharpness_scores else 0.0
    pkt_sizes = [candidate.source_pkt_size for candidate in candidates if (candidate.source_pkt_size or 0) > 0]
    pkt_size_floor = (median(pkt_sizes) * 0.55) if pkt_sizes else 0.0
    pkt_size_prefer = median(pkt_sizes) if pkt_sizes else 1.0

    selected: list[tuple[CandidateFrame, float]] = []
    last_kept: CandidateFrame | None = None
    last_kept_seconds = -1e9
    window: list[CandidateFrame] = []
    window_start = candidates[0].seconds

    def flush_window(force=False):
        nonlocal window, window_start, last_kept, last_kept_seconds
        if not window:
            return

        viable: list[tuple[CandidateFrame, float]] = []
        for candidate in window:
            duplicate_score = 999.0 if last_kept is None else _fingerprint_distance(candidate.fingerprint, last_kept.fingerprint)
            pkt_size = candidate.source_pkt_size or 0
            delta = candidate.seconds - last_kept_seconds
            if candidate.sharpness < sharpness_floor and pkt_size < pkt_size_floor and delta < max_spacing:
                continue
            if last_kept is not None and duplicate_score < 4.0 and delta < max_spacing:
                continue
            viable.append((candidate, duplicate_score))

        if not viable:
            if force:
                candidate = max(
                    window,
                    key=lambda item: (
                        item.sharpness,
                        item.source_pkt_size or 0,
                        item.seconds,
                    ),
                )
                duplicate_score = 999.0 if last_kept is None else _fingerprint_distance(candidate.fingerprint, last_kept.fingerprint)
                viable = [(candidate, duplicate_score)]
            else:
                window = []
                return

        def score(item: tuple[CandidateFrame, float]) -> tuple[float, float, float]:
            candidate, duplicate_score = item
            pkt_score = (candidate.source_pkt_size or 0) / max(pkt_size_prefer, 1.0)
            return (
                candidate.sharpness,
                pkt_score,
                duplicate_score,
            )

        best, duplicate_score = max(viable, key=score)
        if last_kept is None or best.seconds - last_kept_seconds >= target_spacing * 0.5:
            selected.append((best, duplicate_score))
            last_kept = best
            last_kept_seconds = best.seconds
        window = []

    for candidate in candidates:
        if candidate.seconds - window_start >= target_spacing:
            flush_window(force=True)
            window_start = candidate.seconds
        window.append(candidate)

    flush_window(force=True)

    if not selected:
        best = max(candidates, key=lambda item: item.sharpness)
        selected.append((best, 999.0))
    return selected


def clear_prepared_video_derivatives(video_asset: Asset) -> None:
    session_id = video_asset.session_id
    source_asset_id = video_asset.id
    derived_assets = []
    for asset in Asset.query.filter_by(session_id=session_id, type="image").all():
        metadata = parse_asset_metadata(asset)
        if metadata.get("source_video_asset_id") == source_asset_id:
            derived_assets.append(asset)

    for asset in derived_assets:
        for frame in asset.frames.all():
            if frame.preview_path:
                preview_path = get_absolute_path(frame.preview_path)
                if preview_path.exists():
                    preview_path.unlink()
            Observation.query.filter_by(frame_id=frame.id).delete()
            db.session.delete(frame)
        asset_path = get_absolute_path(asset.storage_path)
        if asset_path.exists():
            asset_path.unlink()
        metadata = parse_asset_metadata(asset)
        asset_preview = metadata.get("preview_path")
        if asset_preview:
            asset_preview_path = get_absolute_path(asset_preview)
            if asset_preview_path.exists():
                asset_preview_path.unlink()
        db.session.delete(asset)

    extracted_dir = get_absolute_path(
        f"extracted_frames/session_{video_asset.session_id:04d}/video_asset_{video_asset.id:04d}"
    )
    if extracted_dir.exists():
        shutil.rmtree(extracted_dir, ignore_errors=True)
    db.session.flush()


def prepare_video_asset(
    video_asset: Asset,
    *,
    force: bool = False,
    candidate_fps: float | None = None,
    target_fps: float | None = None,
    progress=None,
) -> dict:
    if video_asset.type != "video":
        raise ValueError("prepare_video_asset expects a video asset")

    video_metadata = parse_asset_metadata(video_asset)
    video_info = video_metadata.get("video") or probe_video_metadata(get_absolute_path(video_asset.storage_path))
    duration_seconds = _safe_float(video_info.get("duration_seconds"))
    source_fps = _safe_float(video_info.get("fps"))

    if not force:
        existing_count = 0
        for asset in Asset.query.filter_by(session_id=video_asset.session_id, type="image").all():
            metadata = parse_asset_metadata(asset)
            if metadata.get("source_video_asset_id") == video_asset.id:
                existing_count += 1
        prepared = video_metadata.get("prepared") or {}
        if existing_count and prepared.get("kept_count") == existing_count:
            if progress:
                progress(
                    stage="skip",
                    current=existing_count,
                    total=existing_count,
                    message=f"already prepared: {existing_count} kept frames",
                    done=True,
                )
            return {
                "kept_count": existing_count,
                "candidate_fps": prepared.get("candidate_fps"),
                "target_fps": prepared.get("target_fps"),
                "skipped": True,
            }

    clear_prepared_video_derivatives(video_asset)

    candidate_fps = candidate_fps or choose_auto_candidate_fps(duration_seconds, source_fps)
    target_fps = target_fps or choose_auto_target_fps(duration_seconds)
    if progress:
        progress(
            stage="extract",
            current=0,
            total=0,
            message=(
                f"extracting candidates @ {candidate_fps:.1f} fps "
                f"(target {target_fps:.1f} fps, ffmpeg threads {_ffmpeg_thread_count()})"
            ),
        )

    video_path = get_absolute_path(video_asset.storage_path)
    extracted_root = get_absolute_path(
        f"extracted_frames/session_{video_asset.session_id:04d}/video_asset_{video_asset.id:04d}"
    )
    candidates_dir = extracted_root / "candidates"
    if extracted_root.exists():
        shutil.rmtree(extracted_root, ignore_errors=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)

    candidate_paths = extract_candidate_frames(video_path, candidates_dir, candidate_fps)
    if progress:
        progress(
            stage="extract",
            current=len(candidate_paths),
            total=len(candidate_paths),
            message=f"extracted {len(candidate_paths)} candidates",
        )
    analyzed = analyze_candidate_frames(candidate_paths, candidate_fps, progress=progress)
    if progress:
        progress(
            stage="metrics",
            current=0,
            total=0,
            message="reading source frame metrics",
        )
    source_metrics = probe_source_frame_metrics(video_path)
    analyzed = attach_source_frame_metrics(analyzed, source_metrics)
    selected = select_candidate_frames(analyzed, target_fps=target_fps)
    if progress:
        progress(
            stage="select",
            current=len(selected),
            total=len(candidate_paths),
            message=f"selected {len(selected)} / {len(candidate_paths)} frames",
        )

    default_location_id = _safe_int(video_metadata.get("default_location_id")) or None
    created_assets = []

    for keep_index, (candidate, duplicate_score) in enumerate(selected, start=1):
        output_name = (
            f"video_{video_asset.id:04d}_t{int(round(candidate.seconds * 1000)):09d}ms_"
            f"keep{keep_index:04d}.jpg"
        )
        image_data = candidate.path.read_bytes()
        storage_info = store_extracted_frame(
            image_data,
            session_id=video_asset.session_id,
            source_asset_id=video_asset.id,
            filename=output_name,
        )
        preview_data = generate_preview(image_data)
        extracted_asset = Asset(
            session_id=video_asset.session_id,
            type="image",
            original_filename=output_name,
            storage_path=storage_info["storage_path"],
            hash_sha256=storage_info["hash_sha256"],
            file_size=storage_info["file_size"],
            mime_type=storage_info["mime_type"],
            import_source="extracted_from_video",
            metadata_json=json.dumps({
                "source_video_asset_id": video_asset.id,
                "source_video_filename": video_asset.original_filename,
                "video_seconds": round(candidate.seconds, 3),
                "candidate_fps": candidate_fps,
                "target_fps": target_fps,
                "source_pkt_size": candidate.source_pkt_size,
                "source_pkt_pos": candidate.source_pkt_pos,
                "source_key_frame": candidate.source_key_frame,
                "source_pict_type": candidate.source_pict_type,
            }),
        )
        db.session.add(extracted_asset)
        db.session.flush()
        frame = Frame(
            asset_id=extracted_asset.id,
            frame_index=keep_index,
            timestamp_original=None,
            timestamp_imported=utcnow(),
            width=candidate.width,
            height=candidate.height,
            blur_score=round(candidate.sharpness, 3),
            duplicate_score=round(float(duplicate_score), 3),
            metadata_json=json.dumps({
                "source_video_asset_id": video_asset.id,
                "source_video_filename": video_asset.original_filename,
                "video_seconds": round(candidate.seconds, 3),
                "source_pkt_size": candidate.source_pkt_size,
                "source_pkt_pos": candidate.source_pkt_pos,
                "source_key_frame": candidate.source_key_frame,
                "source_pict_type": candidate.source_pict_type,
                "source_candidate_path": str(candidate.path.relative_to(get_absolute_path(""))),
            }),
            sensor_json="{}",
            processing_status="done",
        )
        db.session.add(frame)
        db.session.flush()
        if preview_data:
            frame.preview_path = store_preview(preview_data, frame.id)
        if default_location_id:
            db.session.add(Observation(
                frame_id=frame.id,
                assigned_location_id=default_location_id,
                assignment_method="manual",
            ))
        created_assets.append(extracted_asset)
        if progress:
            progress(
                stage="store",
                current=keep_index,
                total=len(selected),
                message=f"storing kept frames {keep_index}/{len(selected)}",
            )

    video_metadata["video"] = video_info
    video_metadata["prepared"] = {
        "prepared_at": utcnow().isoformat(),
        "candidate_fps": candidate_fps,
        "target_fps": target_fps,
        "candidate_count": len(candidate_paths),
        "kept_count": len(created_assets),
    }
    video_asset.metadata_json = json.dumps(video_metadata)
    db.session.commit()
    if progress:
        progress(
            stage="done",
            current=len(created_assets),
            total=len(candidate_paths),
            message=(
                f"done: kept {len(created_assets)} / {len(candidate_paths)} "
                f"(candidate {candidate_fps:.1f} fps, target {target_fps:.1f} fps)"
            ),
            done=True,
        )

    return {
        "kept_count": len(created_assets),
        "candidate_count": len(candidate_paths),
        "candidate_fps": candidate_fps,
        "target_fps": target_fps,
        "skipped": False,
    }


def build_session_reconstruction_set(
    session_id: int,
    *,
    set_name: str | None = None,
    force: bool = False,
    candidate_fps: float | None = None,
    target_fps: float | None = None,
    progress=None,
) -> dict:
    session = db.session.get(Session, session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")

    set_name = set_name or f"session_{session_id:04d}"
    data_dir = get_absolute_path("")
    set_dir = data_dir / "derived" / "reconstruction_sets" / set_name
    images_dir = set_dir / "images"
    if set_dir.exists():
        if not force:
            selection_path = set_dir / "selection.json"
            selection = {}
            if selection_path.exists():
                try:
                    selection = json.loads(selection_path.read_text(encoding="utf-8"))
                except Exception:
                    selection = {}
            return {
                "set_dir": set_dir,
                "images_dir": images_dir,
                "selection": selection or {
                    "name": set_name,
                    "session_id": session.id,
                    "building_id": session.building_id,
                    "building_name": session.building.name if session.building else "",
                    "source_type": session.source_type,
                    "count": len(list(images_dir.iterdir())) if images_dir.exists() else 0,
                    "first_session": session.id,
                    "last_session": session.id,
                    "first_time": session.start_time.isoformat() if session.start_time else "",
                    "last_time": session.end_time.isoformat() if session.end_time else "",
                    "video_prepare": [],
                },
            }
        shutil.rmtree(set_dir, ignore_errors=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    video_assets = Asset.query.filter_by(session_id=session_id, type="video").order_by(Asset.id.asc()).all()
    video_prepare = []
    for asset in video_assets:
        if progress:
            progress(
                stage="video",
                current=asset.id,
                total=len(video_assets),
                message=f"preparing video asset {asset.original_filename}",
            )
        video_prepare.append(prepare_video_asset(
            asset,
            force=force,
            candidate_fps=candidate_fps,
            target_fps=target_fps,
            progress=progress,
        ))

    image_assets = Asset.query.filter_by(session_id=session_id, type="image").order_by(Asset.id.asc()).all()
    manifest_lines = [
        "target_name\tasset_id\tasset_type\timport_source\tstorage_path\tvideo_seconds\n"
    ]
    image_count = 0
    for index, asset in enumerate(image_assets, start=1):
        ext = Path(asset.original_filename).suffix.lower() or ".jpg"
        target_name = f"frame_{index:06d}{ext}"
        target_path = images_dir / target_name
        source_path = get_absolute_path(asset.storage_path)
        if target_path.exists() or target_path.is_symlink():
            target_path.unlink()
        target_path.symlink_to(source_path)
        metadata = parse_asset_metadata(asset)
        manifest_lines.append(
            f"{target_name}\t{asset.id}\t{asset.type}\t{asset.import_source}\t{asset.storage_path}\t{metadata.get('video_seconds', '')}\n"
        )
        image_count += 1

    selection = {
        "name": set_name,
        "session_id": session.id,
        "building_id": session.building_id,
        "building_name": session.building.name if session.building else "",
        "source_type": session.source_type,
        "count": image_count,
        "first_session": session.id,
        "last_session": session.id,
        "first_time": session.start_time.isoformat() if session.start_time else "",
        "last_time": session.end_time.isoformat() if session.end_time else "",
        "video_prepare": video_prepare,
    }
    (set_dir / "manifest.tsv").write_text("".join(manifest_lines), encoding="utf-8")
    (set_dir / "selection.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
    if progress:
        progress(
            stage="manifest",
            current=image_count,
            total=image_count,
            message=f"reconstruction set ready: {image_count} images",
            done=True,
        )
    return {
        "set_dir": set_dir,
        "images_dir": images_dir,
        "selection": selection,
    }


def parse_asset_metadata(asset: Asset) -> dict:
    try:
        return json.loads(asset.metadata_json or "{}")
    except json.JSONDecodeError:
        return {}


def _gradient_energy(pixels: list[int], width: int, height: int) -> float:
    if width <= 1 or height <= 1:
        return 0.0
    total = 0
    samples = 0
    for y in range(height - 1):
        row = y * width
        next_row = (y + 1) * width
        for x in range(width - 1):
            idx = row + x
            total += abs(pixels[idx] - pixels[idx + 1])
            total += abs(pixels[idx] - pixels[next_row + x])
            samples += 2
    return total / max(1, samples)


def _fingerprint_pixels(pixels: list[int], width: int, height: int) -> list[int]:
    if width == 0 or height == 0:
        return []
    sample_w = 24
    sample_h = 14
    result: list[int] = []
    for sy in range(sample_h):
        y = min(height - 1, round((sy + 0.5) * height / sample_h))
        for sx in range(sample_w):
            x = min(width - 1, round((sx + 0.5) * width / sample_w))
            result.append(pixels[y * width + x])
    return result


def _fingerprint_distance(left: list[int], right: list[int]) -> float:
    if not left or not right or len(left) != len(right):
        return 999.0
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


def _parse_fraction(value) -> float | None:
    if not value:
        return None
    text = str(value)
    if "/" in text:
        num, den = text.split("/", 1)
        den_value = _safe_float(den)
        if den_value:
            return _safe_float(num) / den_value
        return None
    return _safe_float(text)


def _extract_rotation(video_stream: dict) -> int:
    tags = video_stream.get("tags") or {}
    rotation = tags.get("rotate")
    side_data = video_stream.get("side_data_list") or []
    for item in side_data:
        if item.get("rotation") is not None:
            rotation = item.get("rotation")
            break
    return _safe_int(rotation) or 0


def _safe_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None
