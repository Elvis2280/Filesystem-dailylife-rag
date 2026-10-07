"""Garage-backed S3 object storage used by the document pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.response import StreamingBody

from app.core.config import settings


class ObjectStorageError(RuntimeError):
    """Raised when a Garage/S3 operation fails."""


OBJECT_STREAM_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ObjectMetadata:
    """Metadata returned by Garage for an object."""

    size: int
    etag: str | None
    last_modified: datetime | None
    content_type: str | None


def _metadata_from_response(response: dict[str, Any]) -> ObjectMetadata:
    return ObjectMetadata(
        size=int(response.get("ContentLength", 0)),
        etag=response.get("ETag"),
        last_modified=response.get("LastModified"),
        content_type=response.get("ContentType"),
    )


def _validated_key(key: str, *, allow_empty: bool = False) -> str:
    normalized = key.strip().lstrip("/")
    if not normalized:
        if allow_empty:
            return ""
        raise ValueError("Object key must not be empty")
    parts = PurePosixPath(normalized).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Unsafe object key: {key}")
    return "/".join(parts)


@lru_cache(maxsize=1)
def get_object_storage_client() -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_KEY,
        region_name=settings.OBJECT_STORAGE_REGION,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=120,
            retries={"max_attempts": 4, "mode": "standard"},
        ),
    )


def check_bucket() -> None:
    try:
        get_object_storage_client().head_bucket(Bucket=settings.OBJECT_STORAGE_BUCKET)
    except (BotoCoreError, ClientError) as exc:
        raise ObjectStorageError(
            f"Object storage bucket '{settings.OBJECT_STORAGE_BUCKET}' is unavailable"
        ) from exc


def put_file(path: Path, key: str, content_type: str) -> None:
    object_key = _validated_key(key)
    try:
        get_object_storage_client().upload_file(
            str(path),
            settings.OBJECT_STORAGE_BUCKET,
            object_key,
            ExtraArgs={"ContentType": content_type},
        )
    except (ClientError, OSError) as exc:
        raise ObjectStorageError(f"Failed to upload object '{object_key}'") from exc


def put_bytes(data: bytes, key: str, content_type: str) -> int:
    object_key = _validated_key(key)
    try:
        get_object_storage_client().put_object(
            Bucket=settings.OBJECT_STORAGE_BUCKET,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        raise ObjectStorageError(f"Failed to upload object '{object_key}'") from exc
    return len(data)


def put_text(text: str, key: str, content_type: str = "text/plain") -> int:
    return put_bytes(text.encode("utf-8"), key, f"{content_type}; charset=utf-8")


def get_bytes(key: str) -> bytes:
    object_key = _validated_key(key)
    try:
        response = get_object_storage_client().get_object(
            Bucket=settings.OBJECT_STORAGE_BUCKET,
            Key=object_key,
        )
        return response["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        raise ObjectStorageError(f"Failed to read object '{object_key}'") from exc


def head_object(key: str) -> ObjectMetadata:
    """Return Garage metadata without downloading an object body."""

    object_key = _validated_key(key)
    try:
        response = get_object_storage_client().head_object(
            Bucket=settings.OBJECT_STORAGE_BUCKET,
            Key=object_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise ObjectStorageError(f"Failed to inspect object '{object_key}'") from exc
    return _metadata_from_response(response)


def get_object_stream(
    key: str,
    byte_range: str | None = None,
) -> StreamingBody:
    """Open a Garage object body, optionally restricted to one byte range.

    The caller owns the returned ``StreamingBody`` and must close it after
    consumption. This deliberately does not read the object into memory.
    """

    object_key = _validated_key(key)
    request: dict[str, Any] = {
        "Bucket": settings.OBJECT_STORAGE_BUCKET,
        "Key": object_key,
    }
    if byte_range is not None:
        request["Range"] = byte_range

    try:
        response = get_object_storage_client().get_object(**request)
    except (BotoCoreError, ClientError) as exc:
        raise ObjectStorageError(f"Failed to stream object '{object_key}'") from exc
    return response["Body"]


def get_text(key: str) -> str:
    return get_bytes(key).decode("utf-8")


def download_file(key: str, destination: Path) -> Path:
    object_key = _validated_key(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        get_object_storage_client().download_file(
            settings.OBJECT_STORAGE_BUCKET,
            object_key,
            str(destination),
        )
    except (ClientError, OSError) as exc:
        raise ObjectStorageError(f"Failed to download object '{object_key}'") from exc
    return destination


def object_exists(key: str) -> bool:
    object_key = _validated_key(key)
    try:
        get_object_storage_client().head_object(
            Bucket=settings.OBJECT_STORAGE_BUCKET,
            Key=object_key,
        )
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return False
        raise ObjectStorageError(f"Failed to inspect object '{object_key}'") from exc


def delete_object(key: str) -> None:
    object_key = _validated_key(key)
    try:
        get_object_storage_client().delete_object(
            Bucket=settings.OBJECT_STORAGE_BUCKET,
            Key=object_key,
        )
    except ClientError as exc:
        raise ObjectStorageError(f"Failed to delete object '{object_key}'") from exc


def delete_prefix(prefix: str = "") -> int:
    object_prefix = _validated_key(prefix, allow_empty=True)
    client = get_object_storage_client()
    deleted = 0
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=settings.OBJECT_STORAGE_BUCKET,
            Prefix=object_prefix,
        ):
            objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if not objects:
                continue
            client.delete_objects(
                Bucket=settings.OBJECT_STORAGE_BUCKET,
                Delete={"Objects": objects, "Quiet": True},
            )
            deleted += len(objects)
    except ClientError as exc:
        raise ObjectStorageError(
            f"Failed to delete object prefix '{object_prefix}'"
        ) from exc
    return deleted
