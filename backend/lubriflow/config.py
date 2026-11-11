from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://lubriflow:change-me@localhost:5432/lubriflow"
    app_origin: str = "http://localhost:3000"
    environment: Literal["development", "production", "test"] = "development"
    document_root: str = "./var/documents"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    azure_document_endpoint: str = ""
    azure_document_key: str = ""
    mfa_encryption_key: str = ""
    require_privileged_mfa: bool = False
    backup_encryption_key: str = ""
    backup_bucket: str = ""
    backup_endpoint_url: str = ""
    messaging_live: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_session_secret: str = ""
    oidc_required_amr: list[str] = ["mfa"]
    oidc_only: bool = False
    messaging_tenant_ids: list[str] = []
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    # Per-purpose, approved Twilio Content SIDs. Values never come from voucher input.
    whatsapp_templates: dict[str, str] = {}

    @model_validator(mode="after")
    def deployment_config(self):
        if self.oidc_issuer:
            issuer = urlparse(self.oidc_issuer)
            if issuer.scheme != "https" or not issuer.hostname or issuer.query or issuer.fragment or issuer.username:
                raise ValueError("OIDC_ISSUER must be a fixed HTTPS issuer URL.")
            if not self.oidc_client_id or not self.oidc_client_secret or len(self.oidc_session_secret) < 32:
                raise ValueError("OIDC requires client credentials and a session secret of at least 32 characters.")
            if not self.oidc_required_amr:
                raise ValueError("OIDC requires explicit MFA authentication-method evidence.")
        if self.oidc_only and not self.oidc_issuer:
            raise ValueError("OIDC_ONLY requires a configured issuer.")
        if self.mfa_encryption_key:
            from cryptography.fernet import Fernet
            Fernet(self.mfa_encryption_key.encode())
        if not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use the PostgreSQL psycopg driver.")
        origin = urlparse(self.app_origin)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.netloc
            or origin.path
            or origin.query
            or origin.fragment
        ):
            raise ValueError("APP_ORIGIN must be an exact origin without a path.")
        if self.environment == "production" and origin.scheme != "https":
            raise ValueError("Production requires an HTTPS APP_ORIGIN.")
        if (self.environment == 'production' or self.require_privileged_mfa) and not self.mfa_encryption_key:
            raise ValueError('Privileged MFA enforcement requires MFA_ENCRYPTION_KEY.')
        return self


@lru_cache
def settings():
    return Settings()
