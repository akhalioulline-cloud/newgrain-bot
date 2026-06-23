"""Background collector for scouting-video transcription (Pilot v2).

Run from cron every few minutes. For each pending video_job: pull the video from S3,
transcribe its narration (chunked sync STT), write the text into the submission's
observation (so /plan reads it), and mark the job done. Failures retry up to 5×.

    docker compose -f docker-compose.prod.yml run --rm -T bot python -m labeling.video_collect
"""
import asyncio
import sys

from bot.db import fail_video_job, finish_video_job, get_pending_video_jobs
from bot.storage import download_bytes
from bot.video_transcribe import transcribe_video


async def run() -> int:
    jobs = await get_pending_video_jobs()
    if not jobs:
        print("video_collect: no pending jobs.", file=sys.stderr)
        return 0
    for j in jobs:
        try:
            video = await download_bytes(j["video_key"])
            text = await asyncio.to_thread(transcribe_video, video)
            await finish_video_job(j["id"], j["submission_id"], text)
            print(f"video_collect: job {j['id']} done ({len(text)} chars).", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            await fail_video_job(j["id"])
            print(f"video_collect: job {j['id']} failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
