import asyncio

import boto3
from botocore.client import Config

from bot.config import settings

_client = boto3.session.Session().client(
    "s3",
    endpoint_url=settings.s3_endpoint or None,
    aws_access_key_id=settings.s3_access_key,
    aws_secret_access_key=settings.s3_secret_key,
    region_name=settings.s3_region,
    config=Config(signature_version="s3v4"),
)


def _ensure_bucket_sync() -> None:
    existing = [b["Name"] for b in _client.list_buckets().get("Buckets", [])]
    if settings.s3_bucket not in existing:
        _client.create_bucket(Bucket=settings.s3_bucket)


def _upload_sync(key: str, data: bytes, content_type: str) -> str:
    _client.put_object(
        Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type
    )
    return f"s3://{settings.s3_bucket}/{key}"


async def ensure_bucket() -> None:
    await asyncio.to_thread(_ensure_bucket_sync)


async def upload_bytes(key: str, data: bytes, content_type: str) -> str:
    return await asyncio.to_thread(_upload_sync, key, data, content_type)


def _delete_sync(key: str) -> None:
    _client.delete_object(Bucket=settings.s3_bucket, Key=key)


async def delete_object(key: str) -> None:
    """Delete one object by key. Used by /cancel to drop a photo whose upload
    the user aborted. Best-effort — caller handles exceptions."""
    await asyncio.to_thread(_delete_sync, key)


def put_object_sync(key: str, data: bytes, content_type: str) -> str:
    """Synchronous upload (for CLI scripts). Returns the s3:// URL."""
    return _upload_sync(key, data, content_type)


def presigned_url(key: str, expires: int = 7 * 24 * 3600) -> str:
    """Time-limited GET URL for an object, served inline (so the annotation
    reference HTML opens in the browser). Object Storage is in RU and reachable
    directly from the annotator's browser, avoiding the Telegram relay."""
    return _client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.s3_bucket,
            "Key": key,
            "ResponseContentType": "text/html; charset=utf-8",
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=expires,
    )
