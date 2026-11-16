"""E-mail alerts. Uses the same Gmail sender + app password as the app
(MAIL_SENDER / MAIL_APP_PASSWORD), recipients from BACKUP_ALERT_EMAILS."""

import smtplib
import ssl
from email.message import EmailMessage

from .util import log


def send(settings, subject, body):
    if not settings.alert_emails:
        log.warning("no BACKUP_ALERT_EMAILS set — not sending: %s", subject)
        return False
    if not settings.mail_sender or not settings.mail_password:
        log.warning("MAIL_SENDER / MAIL_APP_PASSWORD not set — not sending: %s", subject)
        return False
    msg = EmailMessage()
    msg["Subject"] = f"[ERP Backup][{settings.env_name}] {subject}"
    msg["From"] = settings.mail_sender
    msg["To"] = ", ".join(settings.alert_emails)
    msg.set_content(body)
    ctx = ssl.create_default_context()
    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=30) as s:
                s.login(settings.mail_sender, settings.mail_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(settings.mail_sender, settings.mail_password)
                s.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        log.error("alert e-mail failed: %s", e)
        return False
    log.info("e-mail sent: %s", subject)
    return True
