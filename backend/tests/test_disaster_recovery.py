import io
import json
import os
import tarfile
from uuid import uuid4
import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def backup_key(monkeypatch):
    from lubriflow.config import settings
    key = Fernet.generate_key()
    monkeypatch.setattr(settings(), "backup_encryption_key", key.decode())
    import base64
    return base64.urlsafe_b64decode(key)


def test_streaming_encryption_rejects_tamper_wrong_key_and_truncation(tmp_path, backup_key):
    from lubriflow.disaster_recovery import seal, unseal
    source, encrypted, restored = [tmp_path / name for name in ("source", "encrypted", "restored")]
    data = os.urandom(2 * 1024 * 1024 + 19)
    source.write_bytes(data)
    seal(source, encrypted, backup_key)
    unseal(encrypted, restored, backup_key)
    assert restored.read_bytes() == data
    for content, key in [(encrypted.read_bytes(), os.urandom(32)),
                         (encrypted.read_bytes()[:-5], backup_key),
                         (encrypted.read_bytes()[:100] + b"changed" + encrypted.read_bytes()[107:], backup_key)]:
        restored.unlink(missing_ok=True)
        altered = tmp_path / "altered"
        altered.write_bytes(content)
        with pytest.raises(ValueError):
            unseal(altered, restored, key)
        assert not restored.exists()


def test_authenticated_archive_rejects_path_traversal(tmp_path, backup_key):
    from lubriflow.disaster_recovery import seal, verify_bundle
    archive = tmp_path / "malicious.tar"
    with tarfile.open(archive, "w") as tar:
        for name, content in [("manifest.json", json.dumps(dict(version=1, files=[])).encode()),
                              ("../escape", b"bad")]:
            item = tarfile.TarInfo(name)
            item.size = len(content)
            tar.addfile(item, io.BytesIO(content))
    bundle = tmp_path / "bundle"
    seal(archive, bundle, backup_key)
    with pytest.raises(ValueError, match="Unsafe"):
        verify_bundle(bundle)
    assert not (tmp_path / "escape").exists()


@pytest.mark.skipif("lubriflow_test" not in os.getenv("DATABASE_URL", ""), reason="Dedicated test DB required")
def test_full_database_restore_drill(tmp_path, backup_key):
    import psycopg
    from psycopg import sql
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from lubriflow.config import settings
    from lubriflow.disaster_recovery import export_bundle, verify_bundle, restore_bundle
    source = settings().database_url
    target_name = "lubriflow_restore_test_" + uuid4().hex[:12]
    target = make_url(source).set(database=target_name).render_as_string(hide_password=False)
    parsed = make_url(source).set(database="postgres")
    maintenance = {**parsed.query, **parsed.translate_connect_args(username="user", database="dbname")}
    bundle, documents = tmp_path / "full.lfdr", tmp_path / "documents"
    with psycopg.connect(**maintenance, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_name)))
        try:
            manifest = export_bundle(bundle)
            assert verify_bundle(bundle) == manifest
            restore_bundle(bundle, target, documents)
            source_engine, target_engine = create_engine(source), create_engine(target)
            try:
                with source_engine.connect() as old, target_engine.connect() as new:
                    for table in ["users", "business_orders", "business_invoices", "audit_events", "checkpoints"]:
                        query = text("SELECT count(*) FROM " + table)
                        assert old.scalar(query) == new.scalar(query)
                    assert new.scalar(text("SELECT count(*) FROM login_sessions")) == 0
                    assert new.scalar(text("SELECT count(*) FROM tenants WHERE settings->>'mode'='automatic'")) == 0
                    for payload in new.scalars(text("SELECT payload FROM business_attachments")):
                        import hashlib
                        assert hashlib.sha256((documents / payload["key"]).read_bytes()).hexdigest() == payload["sha256"]
                with pytest.raises(ValueError, match="empty"):
                    restore_bundle(bundle, target, tmp_path / "second-documents")
            finally:
                source_engine.dispose()
                target_engine.dispose()
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(target_name)))
