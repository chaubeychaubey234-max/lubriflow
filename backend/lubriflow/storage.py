from pathlib import Path
from uuid import uuid4
import boto3
from .config import settings


def put_document(tenant_id, data):
    key = tenant_id + "/" + str(uuid4())
    cfg = settings()
    if cfg.s3_bucket:
        boto3.client("s3", endpoint_url=cfg.s3_endpoint_url or None).put_object(
            Bucket=cfg.s3_bucket, Key=key, Body=data, ServerSideEncryption="AES256"
        )
    else:
        path = Path(cfg.document_root) / key
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("xb") as stream:
            stream.write(data)
        path.chmod(0o600)
    return key


def read_document(tenant_id, key):
    if not key.startswith(tenant_id + "/") or ".." in key or key.count("/") != 1:
        raise ValueError("Invalid document key.")
    cfg = settings()
    if cfg.s3_bucket:
        return (
            boto3.client("s3", endpoint_url=cfg.s3_endpoint_url or None)
            .get_object(Bucket=cfg.s3_bucket, Key=key)["Body"]
            .read()
        )
    return (Path(cfg.document_root) / key).read_bytes()


def remove_document(tenant_id, key):
    if not key.startswith(tenant_id + "/") or ".." in key or key.count("/") != 1:
        raise ValueError("Invalid document key.")
    cfg = settings()
    if cfg.s3_bucket:
        boto3.client("s3", endpoint_url=cfg.s3_endpoint_url or None).delete_object(
            Bucket=cfg.s3_bucket, Key=key
        )
    else:
        (Path(cfg.document_root) / key).unlink(missing_ok=True)
