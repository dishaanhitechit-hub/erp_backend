#!/usr/bin/env python3
"""
Sent once on server startup/reboot
"""
import smtplib
import socket
import subprocess
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────
# Migrated into the backend repo (ops/alerts/). SMTP login comes from
# /srv/prax-config/alerts.env; recipients from the shared file edited in the
# Ops Console (/srv/prax-config/alert_recipients.json). The lists below are
# only the fallback, used if that file is missing or unreadable.
import os as _os, sys as _sys
_sys.path.insert(0, _os.environ.get("PRAX_BACKEND_DIR", "/srv/backend"))
from prax_ops import recipients as _recipients
from prax_ops.alert_settings import smtp_settings as _smtp_settings
_SMTP          = _smtp_settings()
SMTP_HOST      = _SMTP["host"]
SMTP_PORT      = _SMTP["port"]
FROM_EMAIL     = _SMTP["user"] or "dishaanhitechit.server@gmail.com"
APP_PASSWORD   = _SMTP["password"]

def to(category, fallback):
    """Recipients for one alert type (Ops Console → Alert recipients)."""
    return _recipients.get(category, fallback=fallback)

ALL_EMAILS   = [
    "dishaanhitechit@gmail.com",
    "rohan.soumyajit@gmail.com",
    "adas34965@gmail.com"
]
ALL_EMAILS   = to("server_startup", ALL_EMAILS)

def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5, shell=True)
        return r.stdout.strip()
    except:
        return "N/A"

hostname = socket.gethostname()
now      = datetime.now().strftime("%d %b %Y %H:%M:%S")
uptime   = run("uptime -p")
ip       = run("hostname -I | awk '{print $1}'")

html = f"""
<!DOCTYPE html><html><body style="background:#0d1117;font-family:'Segoe UI',Arial,sans-serif;padding:20px">
<div style="max-width:600px;margin:0 auto">
  <div style="background:#0d2d00;border:1px solid #3FB950;border-radius:12px;padding:24px;text-align:center;margin-bottom:16px">
    <div style="font-size:32px">🟢</div>
    <div style="font-size:22px;font-weight:800;color:#3FB950;margin:8px 0">SERVER ONLINE</div>
    <div style="font-size:13px;color:#8b949e">PRAX ERP Server has started successfully</div>
  </div>
  <div style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px">
    <table style="width:100%;font-size:13px;border-collapse:collapse">
      <tr><td style="padding:8px;color:#8b949e;border-bottom:1px solid #21262d">Hostname</td><td style="padding:8px;color:#c9d1d9;font-family:monospace;border-bottom:1px solid #21262d">{hostname}</td></tr>
      <tr><td style="padding:8px;color:#8b949e;border-bottom:1px solid #21262d">IP Address</td><td style="padding:8px;color:#388BFD;font-family:monospace;border-bottom:1px solid #21262d">{ip}</td></tr>
      <tr><td style="padding:8px;color:#8b949e;border-bottom:1px solid #21262d">Boot Time</td><td style="padding:8px;color:#c9d1d9;font-family:monospace;border-bottom:1px solid #21262d">{now} IST</td></tr>
      <tr><td style="padding:8px;color:#8b949e">Uptime</td><td style="padding:8px;color:#c9d1d9;font-family:monospace">{uptime}</td></tr>
    </table>
  </div>
  <div style="text-align:center;padding:16px;font-size:11px;color:#484f58">
    PRAX ERP Alert System · Dishaan Hi-tech (India) Pvt. Ltd.
  </div>
</div>
</body></html>
"""

try:
    msg = MIMEMultipart("alternative")
    msg["From"]    = FROM_EMAIL
    msg["To"]      = ", ".join(ALL_EMAILS)
    msg["Subject"] = f"🟢 PRAX ERP Server Online — {now} IST"
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(FROM_EMAIL, APP_PASSWORD)
        server.sendmail(FROM_EMAIL, ALL_EMAILS, msg.as_string())
    print("Startup notification sent")
except Exception as e:
    print(f"Failed: {e}")
