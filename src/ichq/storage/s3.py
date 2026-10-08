"""S3-kompatibler Objektspeicher (MinIO lokal, Anbieter in Produktion). Bucket bleibt privat."""
from __future__ import annotations

import hashlib
import secrets
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ichq.storage.base import StorageError, StoredObject, check_key


class S3Storage:
    def __init__(self, bucket: str, endpoint_url: str | None, region: str,
                 access_key: str, secret_key: str, client: Any = None) -> None:
        self.bucket = bucket
        self.client = client or boto3.client(
            "s3", endpoint_url=endpoint_url, region_name=region,
            aws_access_key_id=access_key, aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3},
                          connect_timeout=5, read_timeout=30),
        )

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        self.client.put_object(Bucket=self.bucket, Key=check_key(key), Body=data,
                               ContentType=content_type, Metadata={"sha256": digest})
        return StoredObject(key=key, size=len(data), sha256=digest)

    def get(self, key: str) -> bytes:
        try:
            body: bytes = self.client.get_object(Bucket=self.bucket, Key=check_key(key))["Body"].read()
            return body
        except ClientError:
            raise StorageError("Objekt nicht gefunden oder nicht lesbar") from None

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=check_key(key))

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=check_key(key))
            return True
        except ClientError:
            return False

    def presigned_get(self, key: str, seconds: int = 60) -> str:
        """Kurzlebiger Download-Link. Aufrufer muss vorher die Rechte geprüft haben."""
        if not 1 <= seconds <= 300:
            raise ValueError("Gültigkeit 1–300 Sekunden")
        url: str = self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": check_key(key)}, ExpiresIn=seconds)
        return url

    def check(self) -> None:
        key = f"_health/probe-{secrets.token_hex(4)}"
        inhalt = secrets.token_bytes(16)
        self.put(key, inhalt)
        try:
            if self.get(key) != inhalt:
                raise StorageError("Prüfobjekt fehlerhaft gelesen")
        finally:
            self.delete(key)
