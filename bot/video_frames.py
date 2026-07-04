"""Pull a few sharp still frames from a short field video, so the image-only vision model can
comment on it. ffmpeg/ffprobe are already in the prod image (see bot.video_transcribe)."""
import json
import logging
import os
import subprocess
import tempfile
from io import BytesIO

from PIL import Image, ImageFilter, ImageStat

logger = logging.getLogger("bot.video_frames")


def _duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def _frame_at(path: str, t: float) -> bytes:
    """A single JPEG frame at timestamp `t` seconds (empty bytes on failure)."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", path,
         "-frames:v", "1", "-q:v", "3", "-f", "image2", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.stdout or b""


def _sharpness(jpg: bytes) -> float:
    """Cheap focus score — variance of an edge-filtered grayscale (higher = sharper).
    Lets us drop motion-blurred frames and keep the crisp ones. No numpy needed."""
    try:
        im = Image.open(BytesIO(jpg)).convert("L")
        im.thumbnail((640, 640))
        return ImageStat.Stat(im.filter(ImageFilter.FIND_EDGES)).var[0]
    except Exception:
        return 0.0


def extract_frames(video: bytes, sample: int = 6, keep: int = 3) -> list[bytes]:
    """Sample `sample` frames evenly across the clip; return the `keep` sharpest as JPEG bytes."""
    fd, path = tempfile.mkstemp(suffix=".vid")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(video)
        dur = _duration(path)
        times = [dur * (i + 0.5) / sample for i in range(sample)] if dur > 0.5 else [0.0]
        scored = []
        for t in times:
            jpg = _frame_at(path, t)
            if jpg:
                scored.append((_sharpness(jpg), jpg))
        if not scored:
            logger.warning("video_frames: no frames extracted (duration=%.1f)", dur)
            return []
        scored.sort(key=lambda s: s[0], reverse=True)
        return [jpg for _, jpg in scored[:keep]]
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
