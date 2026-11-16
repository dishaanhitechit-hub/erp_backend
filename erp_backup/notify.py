"""E-mail alerts. Sender = MAIL_SENDER / MAIL_APP_PASSWORD (from env).
Recipients = the shared recipients file (prax_ops.recipients, edited in the
Ops Console), falling back to BACKUP_ALERT_EMAILS when it is not set up."""

from prax_ops import mailer, recipients

from .util import log


def send(settings, subject, text, html=None, category="backup_failure", urgent=False):
    to = recipients.get(category, fallback=settings.alert_emails)
    if not to:
        log.warning("no recipients for %s — not sending: %s", category, subject)
        return False
    if not settings.mail_sender or not settings.mail_password:
        log.warning("MAIL_SENDER / MAIL_APP_PASSWORD not set — not sending: %s", subject)
        return False
    try:
        mailer.send(settings.mail_sender, settings.mail_password, to, subject, html or f"<pre>{text}</pre>",
                    text, host=settings.smtp_host, port=settings.smtp_port, urgent=urgent)
    except Exception as e:  # never let a mail problem break a backup
        log.error("alert e-mail failed: %s", e)
        return False
    log.info("e-mail sent to %s: %s", ", ".join(to), subject)
    return True
