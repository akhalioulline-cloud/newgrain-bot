"""Transcribe a scouting video's voice narration (the field observation /plan reads).

A narration can run minutes — past the 30 s sync-STT limit — so we split the audio into
≤25 s chunks (ffmpeg) and transcribe each via the proven sync SpeechKit path (the same one
that handles voice notes; takes bytes directly, no Object Storage). Runs in the BACKGROUND
collector (labeling/video_collect.py), so the agronomist never waits.

Verified end-to-end: ffmpeg extract + per-chunk sync STT both work on the prod image.
"""
import json
import logging
import os
import subprocess
import tempfile

from bot.transcribe import _transcribe_sync

logger = logging.getLogger("bot.video_transcribe")

CHUNK_SECONDS = 25          # under the 30 s / 1 MB sync-STT limit, with margin


def _duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def _chunk_ogg(path: str, start: float, dur: float) -> bytes:
    """One [start, start+dur] window of the video's audio → mono OGG/Opus bytes."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-ss", str(start), "-t", str(dur), "-i", path,
         "-vn", "-ac", "1", "-c:a", "libopus", "-b:a", "24k", "-f", "ogg", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.stdout or b""


def transcribe_video(video: bytes) -> str:
    """Full narration transcript for a scouting video. Empty string if no speech / failure.
    Synchronous (ffmpeg + STT calls) — call from the background collector."""
    fd, path = tempfile.mkstemp(suffix=".vid")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(video)
        dur = _duration(path)
        if dur <= 0:
            logger.warning("video has no readable duration")
            return ""
        parts, start = [], 0.0
        while start < dur:
            ogg = _chunk_ogg(path, start, CHUNK_SECONDS)
            if ogg:
                try:
                    t = _transcribe_sync(ogg, "oggopus")
                    if t:
                        parts.append(t)
                except Exception as exc:
                    logger.warning("chunk @%.0fs failed: %s", start, exc)
            start += CHUNK_SECONDS
        return " ".join(parts).strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
