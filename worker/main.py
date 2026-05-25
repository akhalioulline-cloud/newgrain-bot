import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")


async def main() -> None:
    # Background tasks (photo download, EXIF, thumbnails, S3 upload) arrive in a later phase.
    logger.info("Worker started. No tasks wired up yet.")
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
