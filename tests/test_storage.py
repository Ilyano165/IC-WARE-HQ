"""Speicher: Schlüsselschema, kein Pfad-Ausbruch, atomares Schreiben, S3-Pfad gegen moto."""
from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from ichq.storage import object_key
from ichq.storage.base import StorageError
from ichq.storage.local import LocalStorage
from ichq.storage.s3 import S3Storage


def test_schluesselschema() -> None:
    t, f = uuid.uuid4(), uuid.uuid4()
    assert object_key(t, f, 3) == f"t/{t}/f/{f}/v/3"
    with pytest.raises(TypeError):
        object_key("t", f)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        object_key(t, f, 0)


def test_lokal_lesen_schreiben_loeschen(tmp_path: Path) -> None:
    st = LocalStorage(tmp_path)
    key = object_key(uuid.uuid4(), uuid.uuid4())
    obj = st.put(key, b"inhalt")
    assert obj.size == 6 and len(obj.sha256) == 64 and st.exists(key) and st.get(key) == b"inhalt"
    assert stat.S_IMODE(os.stat(tmp_path / key).st_mode) == 0o600
    assert not [p for p in tmp_path.rglob("*.tmp")]
    st.delete(key)
    assert not st.exists(key)
    with pytest.raises(StorageError):
        st.get(key)
    st.check()


@pytest.mark.parametrize("key", ["../etc/passwd", "/etc/passwd", "t/../../x", "beliebig.txt",
                                 f"t/{uuid.uuid4()}/f/{uuid.uuid4()}/v/1/../../..", "", "_health/../x"])
def test_ungueltige_schluessel(tmp_path: Path, key: str) -> None:
    st = LocalStorage(tmp_path)
    with pytest.raises(StorageError):
        st.put(key, b"x")
    with pytest.raises(StorageError):
        st.get(key)


def test_mandanten_liegen_getrennt(tmp_path: Path) -> None:
    st = LocalStorage(tmp_path)
    a, b, f = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    st.put(object_key(a, f), b"A")
    assert not st.exists(object_key(b, f))


@mock_aws
def test_s3_gegen_moto() -> None:
    boto3.client("s3", region_name="eu-central-1").create_bucket(
        Bucket="ichq-test", CreateBucketConfiguration={"LocationConstraint": "eu-central-1"})
    st = S3Storage("ichq-test", None, "eu-central-1", "x", "y")
    key = object_key(uuid.uuid4(), uuid.uuid4())
    obj = st.put(key, b"daten", "text/plain")
    assert st.exists(key) and st.get(key) == b"daten" and obj.size == 5
    url = st.presigned_get(key, 60)
    assert "X-Amz-Expires=60" in url and "X-Amz-Signature" in url
    with pytest.raises(ValueError):
        st.presigned_get(key, 3600)
    st.delete(key)
    assert not st.exists(key)
    with pytest.raises(StorageError):
        st.put("../flucht", b"x")
    st.check()
