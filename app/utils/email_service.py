import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import current_app


def _get_recipients(raw: str) -> list[str]:
    return [r.strip() for r in raw.split(",") if r.strip()]


def send_monthly_report(subject: str, html_body: str, recipients_raw: str) -> None:
    """Send an HTML email via Gmail SMTP using an App Password."""
    recipients = _get_recipients(recipients_raw)
    if not recipients:
        current_app.logger.warning("send_monthly_report: no recipients for '%s', skipping", subject)
        return

    sender       = current_app.config["MAIL_SENDER"]
    app_password = current_app.config["MAIL_APP_PASSWORD"]

    if not app_password:
        current_app.logger.error("MAIL_APP_PASSWORD not set — cannot send monthly report")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)

    msg.attach(MIMEText(html_body, "html"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(sender, app_password)
        server.sendmail(sender, recipients, msg.as_string())

    current_app.logger.info("Monthly report '%s' sent to %s", subject, recipients)
