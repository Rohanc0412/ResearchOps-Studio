from __future__ import annotations

import smtplib
from email.message import EmailMessage

from researchops_core.auth.config import get_auth_config


def send_password_reset_otp(*, to_email: str, otp: str) -> None:
    cfg = get_auth_config()
    smtp_host = (cfg.smtp_host or "").strip()
    smtp_from_email = (cfg.smtp_from_email or "").strip()
    smtp_user = (cfg.smtp_user or "").strip()
    smtp_password = cfg.smtp_password or ""

    if not smtp_host or not smtp_from_email:
        raise RuntimeError("SMTP not configured")
    if smtp_user and not smtp_password:
        raise RuntimeError("SMTP password missing")
    if smtp_password and not smtp_user:
        raise RuntimeError("SMTP user missing")

    subject = "Your ResearchStudio password reset code"
    body = (
        "Your password reset code is:\n\n"
        f"{otp}\n\n"
        "This code expires soon. If you did not request a reset, you can ignore this email."
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{cfg.smtp_from_name} <{smtp_from_email}>"
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP(smtp_host, cfg.smtp_port) as server:
        if cfg.smtp_starttls:
            server.starttls()
        if smtp_user:
            server.login(smtp_user, smtp_password)
        server.send_message(msg)
