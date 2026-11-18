"""Select real, available YouTube streams; prefer H.264 and MP4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .settings import ALLOWED_HEIGHTS


@dataclass(frozen=True)
class VideoSelection:
    format_selector: str
    height: int | None
    fps: int | None
    codec: str
    estimated_bytes: int | None

    @property
    def compatible(self) -> bool:
        return self.codec.startswith("avc1") or self.codec.startswith("h264")


def video_formats(info: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in info.get("formats", []) if
            f.get("format_id") and not f.get("has_drm") and
            f.get("vcodec", "none") not in (None, "none") and
            isinstance(f.get("height"), (int, float)) and f["height"] > 0]


def available_heights(info: dict[str, Any]) -> list[int]:
    heights = {int(f["height"]) for f in video_formats(info)}
    return sorted(heights.intersection(ALLOWED_HEIGHTS))


def select_video(info: dict[str, Any], height: int | None = None, fps: int = 60) -> VideoSelection:
    formats = video_formats(info)
    if not formats:
        raise ValueError("No downloadable video streams found")
    target = max(int(f["height"]) for f in formats) if height is None else height
    eligible = [f for f in formats if int(f["height"]) <= target]
    if not eligible:
        eligible = formats  # A lower-than-source preference must not fail outright.
    chosen_height = max(int(f["height"]) for f in eligible)
    # If no requested-or-lower resolution exists, select the smallest larger stream.
    if height is not None and all(int(f["height"]) > target for f in formats):
        chosen_height = min(int(f["height"]) for f in formats)
    candidates = [f for f in formats if int(f["height"]) == chosen_height]
    fps_candidates = [f for f in candidates if not f.get("fps") or float(f["fps"]) <= fps + .1]
    if fps_candidates:
        candidates = fps_candidates
    known_fps = [float(f.get("fps") or 0) for f in candidates]
    best_fps = max(known_fps, default=0)
    if best_fps:
        candidates = [f for f in candidates if float(f.get("fps") or 0) == best_fps]
    def score(f: dict[str, Any]) -> tuple[int, int, float, float]:
        codec = str(f.get("vcodec") or "")
        return (
            int(codec.startswith(("avc1", "h264"))),
            int(f.get("ext") == "mp4"),
            min(float(f.get("fps") or 0), fps),
            float(f.get("tbr") or 0),
        )
    best = max(candidates, key=score)
    codec = str(best.get("vcodec") or "unknown")
    fmtid = str(best["format_id"])
    if best.get("acodec") not in (None, "none"):
        selector = fmtid  # Already contains audio.
    else:
        selector = f"{fmtid}+bestaudio[ext=m4a]/{fmtid}+bestaudio/{fmtid}"
    estimate = best.get("filesize") or best.get("filesize_approx")
    if estimate:
        estimate = int(estimate * 1.2)  # Include estimated audio overhead.
    return VideoSelection(selector, int(best["height"]), int(best.get("fps") or 0) or None, codec, estimate)
