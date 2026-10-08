"""Dateispeicher. Kennt keine Datenbank — Metadaten verwaltet das jeweilige Fachmodul."""
from __future__ import annotations

from ichq.core.config import Settings
from ichq.storage.base import Storage, StorageError, StoredObject, object_key

__all__ = ["Storage", "StorageError", "StoredObject", "build_storage", "object_key"]


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        from ichq.storage.s3 import S3Storage
        assert settings.s3_bucket and settings.s3_access_key and settings.s3_secret_key
        return S3Storage(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key=settings.s3_access_key.get_secret_value(),
            secret_key=settings.s3_secret_key.get_secret_value(),
        )
    from ichq.storage.local import LocalStorage
    assert settings.storage_path is not None
    return LocalStorage(settings.storage_path)
