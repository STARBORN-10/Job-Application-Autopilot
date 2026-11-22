"""
SMTP sending for e-mail applications.

Settings: SMTP_HOST, SMTP_PORT (465 = SSL, otherwise STARTTLS), SMTP_USER, SMTP_PASSWORD, SMTP_FROM.
For Gmail use smtp.gmail.com, port 465 and an App Password (Google Account > Security >
2-Step Verification > App passwords); the normal account password does not work.
"""
import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Optional


class EmailConfigError(Exception):
    pass


def _port() -> int:
    try:
        return int((os.getenv("SMTP_PORT") or "465").strip())
    except ValueError:
        return 465


def smtp_settings() -> dict:
    return {
        "host": (os.getenv("SMTP_HOST") or "").strip(),
        "port": _port(),
        "user": (os.getenv("SMTP_USER") or "").strip(),
        "password": os.getenv("SMTP_PASSWORD") or "",
        "sender": (os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "").strip(),
    }


def smtp_configured() -> bool:
    s = smtp_settings()
    return bool(s["host"] and s["user"] and s["password"] and s["sender"])


def build_message(sender: str, to: str, subject: str, body: str, attachment: Optional[Path]) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment is not None:
        ctype, _ = mimetypes.guess_type(attachment.name)
        maintype, subtype = (ctype or "application/pdf").split("/", 1)
        msg.add_attachment(attachment.read_bytes(), maintype=maintype, subtype=subtype, filename=attachment.name)
    return msg


def send_email(to: str, subject: str, body: str, attachment: Optional[Path] = None) -> None:
    """Send one message. Raises EmailConfigError when SMTP is not configured, smtplib errors otherwise."""
    s = smtp_settings()
    if not smtp_configured():
        raise EmailConfigError("SMTP is not configured (SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM).")
    msg = build_message(s["sender"], to, subject, body, attachment)
    context = ssl.create_default_context()
    if s["port"] == 465:
        with smtplib.SMTP_SSL(s["host"], s["port"], context=context, timeout=30) as server:
            server.login(s["user"], s["password"])
            server.send_message(msg)
    else:
        with smtplib.SMTP(s["host"], s["port"], timeout=30) as server:
            server.starttls(context=context)
            server.login(s["user"], s["password"])
            server.send_message(msg)
