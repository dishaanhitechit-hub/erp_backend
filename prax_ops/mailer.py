"""Send one HTML email (with a plain-text copy) over SMTP."""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid


def send(sender, password, to, subject, html_body, text_body="", host="smtp.gmail.com",
         port=465, sender_name="PRAX ERP Alerts", urgent=False, timeout=30):
    """Raises smtplib.SMTPException / OSError on failure."""
    to = [t for t in to if t]
    if not to:
        raise ValueError("no recipients")
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((sender_name, sender))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    if urgent:
        msg["Importance"] = "high"
        msg["X-Priority"] = "1"
    msg.attach(MIMEText(text_body or subject, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    ctx = ssl.create_default_context()
    if int(port) == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=timeout) as s:
            s.login(sender, password)
            s.sendmail(sender, to, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as s:
            s.starttls(context=ctx)
            s.login(sender, password)
            s.sendmail(sender, to, msg.as_string())
