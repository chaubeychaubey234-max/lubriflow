"""Full database/document recovery tooling. Run as a separate operations identity."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
from uuid import uuid4

import boto3
import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from .config import settings
from .models import now
from .storage import read_document

MAGIC = b"LUBRIFLOW-DR-1\n"
CHUNK = 1024 * 1024


def key_bytes():
    try:
        key = base64.urlsafe_b64decode(settings().backup_encryption_key)
    except (ValueError, TypeError):
        key = b""
    if len(key) != 32:
        raise ValueError("Configure BACKUP_ENCRYPTION_KEY with a separate 32-byte base64 key.")
    return key


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def seal(source, target, key):
    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC)
    with Path(source).open("rb") as src, Path(target).open("xb") as out:
        os.chmod(target, 0o600)
        out.write(MAGIC + nonce)
        while block := src.read(CHUNK):
            out.write(encryptor.update(block))
        out.write(encryptor.finalize() + encryptor.tag)
        out.flush()
        os.fsync(out.fileno())


def unseal(source, target, key):
    """Plaintext stays in a private staging directory until GCM authentication succeeds."""
    size = Path(source).stat().st_size
    if size < len(MAGIC) + 28:
        raise ValueError("Invalid recovery bundle.")
    try:
        with Path(source).open("rb") as src, Path(target).open("xb") as out:
            os.chmod(target, 0o600)
            if src.read(len(MAGIC)) != MAGIC:
                raise ValueError("Unknown recovery bundle version.")
            nonce = src.read(12)
            src.seek(-16, 2)
            tag = src.read(16)
            src.seek(len(MAGIC) + 12)
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(MAGIC)
            remaining = size - len(MAGIC) - 28
            while remaining:
                block = src.read(min(CHUNK, remaining))
                if not block:
                    raise ValueError("Truncated recovery bundle.")
                out.write(decryptor.update(block))
                remaining -= len(block)
            out.write(decryptor.finalize())
    except (InvalidTag, ValueError):
        Path(target).unlink(missing_ok=True)
        raise ValueError("Recovery bundle authentication failed; check its key and integrity.") from None


def pg_environment(url):
    parsed = make_url(url)
    args = dict(parsed.query)
    args.update({k: v for k, v in dict(host=parsed.host, port=parsed.port, user=parsed.username,
                                      password=parsed.password, dbname=parsed.database).items() if v is not None})
    # Credentials only enter the subprocess environment, never argv or logs.
    psycopg.conninfo.make_conninfo(**args)
    names = {"dbname": "PGDATABASE", "connect_timeout": "PGCONNECT_TIMEOUT",
             "application_name": "PGAPPNAME", "target_session_attrs": "PGTARGETSESSIONATTRS"}
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment.update({names.get(key, "PG" + key.upper()): str(value) for key, value in args.items()})
    return environment


def pg_tool(name, url, *args):
    executable = shutil.which(name)
    if not executable:
        raise ValueError(f"Install matching PostgreSQL client tools or add {name} to PATH.")
    result = subprocess.run([executable, *map(str, args)], env=pg_environment(url),
                            capture_output=True, timeout=3600)
    if result.returncode:
        raise RuntimeError(f"{name} failed. Check client/server versions, permissions and connectivity.")


def export_bundle(target):
    cfg, key = settings(), key_bytes()
    target = Path(target).resolve()
    if target.exists():
        raise ValueError("Backup destination already exists.")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    engine = create_engine(cfg.database_url)
    try:
        with tempfile.TemporaryDirectory(prefix="lubriflow-backup-") as temp:
            root = Path(temp)
            files = []
            with engine.connect().execution_options(isolation_level="REPEATABLE READ") as db:
                with db.begin():
                    snapshot = db.scalar(text("SELECT pg_export_snapshot()"))
                    pg_tool("pg_dump", cfg.database_url, "--format=custom", "--no-owner", "--no-privileges",
                            "--snapshot=" + snapshot, "--file=" + str(root / "database.dump"))
                    rows = db.execute(text("SELECT tenant_id, payload FROM business_attachments"))
                    copied = set()
                    for tenant, doc in rows:
                        key_name = doc["key"]
                        if key_name in copied:
                            continue
                        data = read_document(tenant, key_name)
                        if len(data) != doc["size"] or hashlib.sha256(data).hexdigest() != doc["sha256"]:
                            raise ValueError("A document failed its stored integrity check. Backup aborted.")
                        path = root / "documents" / key_name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                        files.append(dict(path="documents/" + key_name, size=len(data), sha256=doc["sha256"]))
                        copied.add(key_name)
                    files.append(dict(path="database.dump", size=(root / "database.dump").stat().st_size,
                                      sha256=file_hash(root / "database.dump")))
            manifest = dict(version=1, created_at=now().isoformat(), files=files,
                            includes=["database", "users", "automation checkpoints", "referenced documents"])
            (root / "manifest.json").write_text(json.dumps(manifest))
            with tarfile.open(root / "bundle.tar", "w") as archive:
                for name in ["manifest.json"] + [item["path"] for item in files]:
                    archive.add(root / name, arcname=name, recursive=False)
            partial = target.with_name(target.name + "." + str(uuid4()) + ".partial")
            try:
                seal(root / "bundle.tar", partial, key)
                os.link(partial, target)  # Atomic publication, refusing to overwrite another backup.
            finally:
                partial.unlink(missing_ok=True)
            return manifest
    finally:
        engine.dispose()


def unpack_verified(source, root):
    root = Path(root)
    unseal(source, root / "bundle.tar", key_bytes())
    with tarfile.open(root / "bundle.tar", "r:") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ValueError("Invalid recovery manifest.")
        for member in members:
            parts = Path(member.name).parts
            if (not member.isfile() or Path(member.name).is_absolute() or ".." in parts
                    or member.name not in {"database.dump", "manifest.json"} and
                    (len(parts) != 3 or parts[0] != "documents")):
                raise ValueError("Unsafe recovery archive member.")
        manifest_member = archive.getmember("manifest.json")
        if manifest_member.size > 20 * 1024 * 1024:
            raise ValueError("Recovery manifest is too large.")
        manifest = json.load(archive.extractfile(manifest_member))
        expected = {item["path"]: item for item in manifest["files"]}
        if (manifest["version"] != 1 or len(expected) != len(manifest["files"])
                or set(names) != set(expected) | {"manifest.json"} or "database.dump" not in expected):
            raise ValueError("Recovery manifest does not match archive.")
        for member in members:
            if member.name == "manifest.json":
                continue
            if member.size != expected[member.name]["size"]:
                raise ValueError("Recovery file size mismatch.")
            path = root / member.name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if member.name.startswith("documents/"):
                (root / "documents").chmod(0o700)
            with archive.extractfile(member) as src, path.open("xb") as dest:
                path.chmod(0o600)
                shutil.copyfileobj(src, dest, CHUNK)
            if file_hash(path) != expected[member.name]["sha256"]:
                raise ValueError("Recovery file hash mismatch.")
        return manifest


def verify_bundle(source):
    with tempfile.TemporaryDirectory(prefix="lubriflow-verify-") as temp:
        return unpack_verified(source, temp)


def restore_bundle(source, target_url, documents):
    """Only restore into an empty, offline database and a nonexistent document directory."""
    destination = Path(documents).resolve()
    if destination.exists():
        raise ValueError("Restore documents into a new directory.")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    engine = create_engine(target_url)
    try:
        with engine.connect() as db:
            count = db.scalar(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                   "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' "
                                   "AND c.relkind IN ('r','p','v','m','S','f')"))
            if count:
                raise ValueError("Recovery requires a completely empty target database.")
        with tempfile.TemporaryDirectory(prefix=".lubriflow-restore-", dir=destination.parent) as temp:
            root = Path(temp)
            manifest = unpack_verified(source, root)
            pg_tool("pg_restore", target_url, "--single-transaction", "--exit-on-error", "--no-owner",
                    "--no-privileges", "--dbname=" + make_url(target_url).database, root / "database.dump")
            with engine.begin() as db:
                db.execute(text("DELETE FROM login_sessions"))
                db.execute(text("UPDATE tenants SET settings=jsonb_set(settings, '{mode}', '\"manual\"')"))
                # A database snapshot cannot prove what was sent after backup time.
                # Hold all restored pending sends until provider logs are reconciled.
                if db.scalar(text("SELECT to_regclass('public.business_communications')")):
                    db.execute(text("""
                        UPDATE business_communications
                        SET status='Uncertain', payload=payload ||
                            '{"status":"Uncertain","error":"Disaster recovery restore: reconcile provider logs before resending."}'::jsonb
                        WHERE status IN ('Queued', 'Retry', 'Sending')
                    """))
                db.execute(text("UPDATE automation_runs SET status='Failed', result='{" +
                                '"error":"Recovery hold: operator review required"' + "}'::jsonb "
                                "WHERE status IN ('Queued','Running')"))
            (root / "documents").mkdir(exist_ok=True, mode=0o700)
            os.rename(root / "documents", destination)
            return manifest
    finally:
        engine.dispose()


def upload_bundle(path):
    cfg = settings()
    if not cfg.backup_bucket or cfg.backup_bucket == cfg.s3_bucket:
        raise ValueError("Use a separate BACKUP_BUCKET for independent recovery copies.")
    client = boto3.client("s3", endpoint_url=cfg.backup_endpoint_url or None)
    key = "lubriflow-recovery/" + Path(path).name
    client.upload_file(str(path), cfg.backup_bucket, key, ExtraArgs={"ServerSideEncryption": "AES256",
                       "Metadata": {"sha256": file_hash(path)}})
    head = client.head_object(Bucket=cfg.backup_bucket, Key=key)
    if head["ContentLength"] != Path(path).stat().st_size or head["Metadata"].get("sha256") != file_hash(path):
        raise ValueError("Remote backup verification failed.")
    remote_hash = hashlib.sha256()
    with client.get_object(Bucket=cfg.backup_bucket, Key=key)["Body"] as body:
        for chunk in body.iter_chunks(CHUNK):
            remote_hash.update(chunk)
    if remote_hash.hexdigest() != file_hash(path):
        raise ValueError("Remote backup content verification failed.")
    return key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "verify", "restore", "service"])
    parser.add_argument("path", type=Path, help="Bundle file, or output directory for service mode")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--documents", type=Path)
    parser.add_argument("--interval-hours", type=int, default=24)
    args = parser.parse_args()
    if args.action == "service":
        if args.interval_hours < 1:
            parser.error("interval must be at least one hour")
        while True:
            try:
                path = args.path / (now().strftime("%Y%m%dT%H%M%SZ") + "-" + str(uuid4()) + ".lfdr")
                export_bundle(path)
                verify_bundle(path)
                if args.upload:
                    upload_bundle(path)
                print(json.dumps(dict(event="backup_completed", at=now().isoformat(), remote=args.upload)), flush=True)
            except Exception as error:
                print(json.dumps(dict(event="backup_failed", at=now().isoformat(), error=type(error).__name__)), flush=True)
                raise SystemExit(1) from None
            time.sleep(args.interval_hours * 3600)
    elif args.action == "export":
        export_bundle(args.path)
        verify_bundle(args.path)
        if args.upload:
            upload_bundle(args.path)
        print("Encrypted full recovery bundle created and verified.")
    elif args.action == "verify":
        manifest = verify_bundle(args.path)
        print(json.dumps(dict(created_at=manifest["created_at"], files=len(manifest["files"]), verified=True)))
    else:
        target = os.getenv("DR_RESTORE_DATABASE_URL")
        if not target or not args.documents:
            parser.error("Set DR_RESTORE_DATABASE_URL and --documents for the empty offline target")
        restore_bundle(args.path, target, args.documents)
        print("Restored. Sessions revoked; automation held in manual mode. Review before starting services.")


if __name__ == "__main__":
    main()
