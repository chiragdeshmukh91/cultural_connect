"""Outbound email. Uses SMTP when configured; otherwise the message is written to the server log
(clearly marked) so local development still works. The API never reveals which path was taken to
anonymous callers, and never claims an email was delivered."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from . import config

log = logging.getLogger("culture_connect.mail")


def enabled() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_FROM)


def send(to: str, subject: str, body: str) -> bool:
    if not enabled():
        print(f"\n[mail:not-configured] To: {to}\nSubject: {subject}\n{body}\n", flush=True)
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            if config.SMTP_TLS:
                s.starttls()
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("Email to %s failed: %s", to.split("@")[-1], type(exc).__name__)
        return False
