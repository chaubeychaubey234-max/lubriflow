"""TLS SMTP and approved WhatsApp templates; uncertain sends are never auto-retried."""
import json
import re
import smtplib
import ssl
from email.message import EmailMessage
from datetime import timedelta, datetime
import httpx
from sqlalchemy import select

from .config import settings
from .db import Session
from .models import Tenant, now
from .repository import load, save, tenant_lock
from .domain import RuleError
from .messaging import plan_messages, validate_send


class DeliveryError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def configured(message, cfg):
    if not cfg.messaging_live:
        return False
    if message["channel"] == "email":
        return bool(cfg.smtp_host and cfg.smtp_from and cfg.smtp_username and cfg.smtp_password)
    return bool(re.fullmatch(r"AC[0-9a-fA-F]{32}", cfg.twilio_account_sid)
                and cfg.twilio_auth_token and re.fullmatch(r"whatsapp:\+[1-9][0-9]{7,14}", cfg.twilio_whatsapp_from)
                and re.fullmatch(r"HX[0-9a-fA-F]{32}", cfg.whatsapp_templates.get(message["purpose"], "")))


def send(message, cfg):
    if message["channel"] == "email":
        mail = EmailMessage()
        mail["From"], mail["To"] = cfg.smtp_from, message["recipient"]
        mail["Subject"] = message["subject"]
        mail["Message-ID"] = f'<{message["id"]}.{message["tenant"]}@lubriflow.local>'
        mail.set_content(message["body"])
        # Only connection failures before SMTP DATA are safe to retry.
        try:
            smtp = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=20, context=ssl.create_default_context())
            smtp.login(cfg.smtp_username, cfg.smtp_password)
        except smtplib.SMTPAuthenticationError:
            raise DeliveryError("Failed", "SMTP authentication rejected; check server credentials.") from None
        except (OSError, smtplib.SMTPException):
            raise DeliveryError("Retry", "Could not establish an authenticated TLS SMTP connection.") from None
        try:
            smtp.send_message(mail)
        except smtplib.SMTPResponseException as exc:
            raise DeliveryError("Retry" if 400 <= exc.smtp_code < 500 else "Failed", "SMTP server rejected the message.") from None
        except smtplib.SMTPRecipientsRefused:
            raise DeliveryError("Failed", "SMTP recipient rejected.") from None
        except Exception:
            raise DeliveryError("Uncertain", "SMTP response was lost; verify provider logs before any resend.") from None
        finally:
            smtp.close()
        return str(mail["Message-ID"])
    url = f'https://api.twilio.com/2010-04-01/Accounts/{cfg.twilio_account_sid}/Messages.json'
    # Approved templates have a fixed five-variable contract documented in setup instructions.
    variables = {"1": message["company"], "2": message["source"], "3": message["due"],
                 "4": message["summary"], "5": message["replyTo"]}
    try:
        response = httpx.post(url, auth=(cfg.twilio_account_sid, cfg.twilio_auth_token),
                              data={"From": cfg.twilio_whatsapp_from, "To": "whatsapp:" + message["recipient"],
                                    "ContentSid": cfg.whatsapp_templates[message["purpose"]],
                                    "ContentVariables": json.dumps(variables)}, timeout=20)
    except httpx.ConnectError:
        raise DeliveryError("Retry", "WhatsApp connection could not be established.") from None
    except httpx.HTTPError:
        raise DeliveryError("Uncertain", "WhatsApp provider response was lost; verify provider logs.") from None
    if response.status_code == 429:
        raise DeliveryError("Retry", "WhatsApp provider rate limit; retry scheduled.")
    if 400 <= response.status_code < 500:
        raise DeliveryError("Failed", "WhatsApp provider rejected the request; check sender, template and recipient.")
    if response.status_code >= 500:
        raise DeliveryError("Uncertain", "WhatsApp provider failed after submission; verify provider logs.")
    try:
        sid = response.json()["sid"]
        if not re.fullmatch(r"SM[0-9a-fA-F]{32}", sid):
            raise ValueError()
        return sid
    except (ValueError, KeyError, TypeError):
        raise DeliveryError("Uncertain", "WhatsApp response did not contain a valid message ID.") from None


def event(message, status, detail=""):
    message["status"] = status
    message["error"] = detail
    message["events"].append(dict(at=now().isoformat(), status=status, detail=detail))


def messaging_once():
    """Claim under tenant lock, commit Sending before network I/O, then record result.

    An interrupted claim becomes Uncertain, never Queued: external sends cannot be rolled back.
    Only one outstanding attempt per tenant is allowed; no concurrent worker can claim it twice.
    """
    cfg = settings()
    with Session() as db:
        tenants = list(db.scalars(select(Tenant.id)))
    for tenant_id in tenants:
        claimed = None
        with Session.begin() as db:
            tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update(skip_locked=True))
            if tenant is None:
                continue
            s = load(db, tenant)
            before = json.dumps(s, sort_keys=True)
            plan_messages(s)
            sending = [x for x in s["communications"] if x["status"] == "Sending"]
            for message in sending:
                if datetime.fromisoformat(message["attemptedAt"]) < now() - timedelta(minutes=10):
                    event(message, "Uncertain", "Worker stopped during delivery; review provider logs before resending.")
            if not sending:
                for message in reversed(s["communications"]):
                    if message["status"] not in {"Queued", "Retry"} or message.get("nextAttemptAt", "") > now().isoformat():
                        continue
                    try:
                        validate_send(s, message)
                    except RuleError as exc:
                        event(message, "Cancelled", str(exc))
                        continue
                    if tenant_id not in cfg.messaging_tenant_ids or not configured(message, cfg):
                        message["error"] = "Awaiting live messaging configuration. No message has been sent."
                        continue
                    from .messaging import source_record
                    source = source_record(s, message["purpose"], message["source"])
                    # Keep template variables single-line and bounded. Do not silently truncate order details.
                    summary = " | ".join(message["body"].splitlines()[4:])
                    if message["channel"] == "whatsapp" and len(summary) > 900:
                        event(message, "Failed", "Document exceeds WhatsApp template size; use email for this document.")
                        continue
                    message["attempts"] += 1
                    message["attemptedAt"] = now().isoformat()
                    event(message, "Sending")
                    claimed = dict(message, tenant=tenant_id, company=" ".join(s["settings"]["company"].split()), due=source["due"],
                                   summary=summary, replyTo=" ".join(s["settings"].get("email", "").split()) or "Reply to this message")
                    break
            if json.dumps(s, sort_keys=True) != before:
                save(db, tenant, s)
        if claimed is None:
            continue
        try:
            provider_id = send(claimed, cfg)
            status, detail = "Accepted", "Provider accepted the message; delivery is not yet confirmed."
        except DeliveryError as exc:
            status, detail, provider_id = exc.status, str(exc), ""
        except Exception:
            status, detail, provider_id = "Uncertain", "Unexpected delivery failure; inspect server and provider logs.", ""
        with Session.begin() as db:
            tenant = tenant_lock(db, tenant_id)
            s = load(db, tenant)
            message = next(x for x in s["communications"] if x["id"] == claimed["id"])
            if status == "Retry" and message["attempts"] >= 5:
                status, detail = "Failed", "Retry limit reached. " + detail
            event(message, status, detail)
            if status == "Retry":
                message["nextAttemptAt"] = (now() + timedelta(minutes=min(60, 2 ** message["attempts"]))).isoformat()
            if provider_id:
                message.update(providerId=provider_id, acceptedAt=now().isoformat())
                if message["purpose"] == "po":
                    order = next(x for x in s["orders"] if x["id"] == message["source"])
                    if order["status"] == "Approved" and str(order["revision"]) == message["sourceRevision"]:
                        order["status"] = "Issued"
            save(db, tenant, s)


def poll_whatsapp():
    """Read delivery status using provider authentication; no unauthenticated webhook surface."""
    cfg = settings()
    if not cfg.messaging_live or not re.fullmatch(r"AC[0-9a-fA-F]{32}", cfg.twilio_account_sid):
        return
    with Session() as db:
        tenants = list(db.scalars(select(Tenant.id)))
    for tenant_id in tenants:
        if tenant_id not in cfg.messaging_tenant_ids:
            continue
        with Session.begin() as db:
            tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update(skip_locked=True))
            if tenant is None:
                continue
            s = load(db, tenant)
            changed = False
            for message in s["communications"]:
                if message["channel"] != "whatsapp" or message["status"] not in {"Accepted", "Sent", "Delivered"}:
                    continue
                if message.get("pollAfter", "") > now().isoformat():
                    continue
                sid = message.get("providerId", "")
                if not re.fullmatch(r"SM[0-9a-fA-F]{32}", sid):
                    continue
                try:
                    response = httpx.get(f'https://api.twilio.com/2010-04-01/Accounts/{cfg.twilio_account_sid}/Messages/{sid}.json',
                                         auth=(cfg.twilio_account_sid, cfg.twilio_auth_token), timeout=10)
                    response.raise_for_status()
                    status = {"sent": "Sent", "delivered": "Delivered", "read": "Read", "failed": "Failed", "undelivered": "Failed"}.get(response.json().get("status"))
                    if status and status != message["status"]:
                        event(message, status, "WhatsApp provider status update.")
                except (httpx.HTTPError, ValueError):
                    pass
                message["pollAfter"] = (now() + timedelta(minutes=15)).isoformat()
                changed = True
                break  # Bound provider calls to one status query per tenant and worker iteration.
            if changed:
                save(db, tenant, s)
