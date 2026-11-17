#!/usr/bin/env python3
"""
Called by GitHub Actions deploy.yml when flask db upgrade fails.
Sends immediate alert to all emails with error details.
Usage: python3 /opt/alerts/migration_alert.py "error message here"
"""
import smtplib, sys, socket
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import subprocess

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

ALL_EMAILS     = ["dishaanhitechit@gmail.com", "rohan.soumyajit@gmail.com", "adas34965@gmail.com"]
ALL_EMAILS     = to("server_migration", ALL_EMAILS)

def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=True)
        return r.stdout.strip()
    except: return ""

error_msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Unknown error"
now       = datetime.now().strftime("%d %b %Y %H:%M:%S")
hostname  = socket.gethostname()

# Which app failed: each deploy.yml does "cd /srv/<app>" before calling this
# script, so use the current folder (or PRAX_APP_DIR). Falls back to the ERP.
from prax_ops.alert_settings import alembic_version as _alembic_version
_cwd = _os.getcwd()
APP_DIR   = _os.environ.get("PRAX_APP_DIR") or (_cwd if _os.path.isdir(_os.path.join(_cwd, "migrations")) else "/srv/backend")
APP_NAME  = _os.path.basename(APP_DIR.rstrip("/")) or "backend"
SERVICE   = f"{APP_NAME}.service"
APP_LABEL = "PRAX ERP" if APP_NAME == "backend" else APP_NAME

# Get last 20 lines of the app's journal for context
journal_logs = run(f"journalctl -u {SERVICE} -n 20 --no-pager --output=short-iso 2>/dev/null")

# Get alembic version info (as the app's own database user, no sudo)
db_version = _alembic_version(APP_DIR)
migration_files = run(f"ls {APP_DIR}/migrations/versions/ 2>/dev/null")

def log_rows(logs):
    rows = ""
    for line in (logs or "No logs").splitlines()[:20]:
        if line.strip():
            color = "#991B1B" if any(w in line.lower() for w in ["error","fail","exception","traceback","critical"]) else "#44403C"
            rows += f'<tr><td style="padding:3px 10px;font-size:11px;color:{color};font-family:monospace;border-bottom:1px solid #FEF3C7;word-break:break-all;line-height:1.5">{line[:120]}</td></tr>'
    return rows

html = f"""<!DOCTYPE html><html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"></head>
<body style="margin:0;padding:0;background:#F5EFE6;font-family:Arial,Helvetica,sans-serif">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background:#F5EFE6;padding:16px 8px">
<tr><td align="center">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width:560px">

  <!-- HEADER -->
  <tr><td style="background:#7C3E1B;padding:16px 20px;border-radius:12px 12px 0 0;text-align:center">
    <div style="font-size:10px;color:#FCD9B2;letter-spacing:2px;text-transform:uppercase;margin-bottom:3px">Dishaan Hi-tech (India) Pvt. Ltd.</div>
    <div style="font-size:18px;font-weight:800;color:#FFFFFF">PRAX ERP Alert System</div>
    <div style="font-size:10px;color:#FCD9B2;margin-top:2px">{hostname} &nbsp;·&nbsp; 132.154.156.82</div>
  </td></tr>

  <!-- STATUS -->
  <tr><td style="background:#FFF1F2;border-left:3px solid #FECACA;border-right:3px solid #FECACA;padding:20px;text-align:center">
    <div style="font-size:40px;line-height:1;margin-bottom:8px">🔴</div>
    <div style="font-size:20px;font-weight:800;color:#7F1D1D;margin-bottom:6px">Database Migration Failed — {APP_LABEL}</div>
    <div style="font-size:11px;color:#78716C">{now} IST</div>
  </td></tr>

  <!-- ERROR DETAILS -->
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">⚡ Error Details</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #FECACA;background:#FFF8F8">
      <tr>
        <td style="padding:10px 12px;font-size:13px;color:#78716C;border-bottom:1px solid #FEE2E2;width:35%">App</td>
        <td style="padding:10px 12px;font-size:13px;color:#44403C;font-weight:700;border-bottom:1px solid #FEE2E2;font-family:monospace">{APP_NAME} ({APP_DIR})</td>
      </tr>
      <tr>
        <td style="padding:10px 12px;font-size:13px;color:#78716C;border-bottom:1px solid #FEE2E2">Command</td>
        <td style="padding:10px 12px;font-size:13px;color:#991B1B;font-weight:700;border-bottom:1px solid #FEE2E2;font-family:monospace">flask db upgrade</td>
      </tr>
      <tr>
        <td style="padding:10px 12px;font-size:13px;color:#78716C;border-bottom:1px solid #FEE2E2">Error</td>
        <td style="padding:10px 12px;font-size:12px;color:#991B1B;border-bottom:1px solid #FEE2E2;font-family:monospace;word-break:break-all">{error_msg[:500]}</td>
      </tr>
      <tr>
        <td style="padding:10px 12px;font-size:13px;color:#78716C;border-bottom:1px solid #FEE2E2">DB Version</td>
        <td style="padding:10px 12px;font-size:13px;color:#1D4ED8;font-family:monospace;border-bottom:1px solid #FEE2E2">{db_version or "Unknown"}</td>
      </tr>
      <tr>
        <td style="padding:10px 12px;font-size:13px;color:#78716C;border-bottom:1px solid #FEE2E2">Time</td>
        <td style="padding:10px 12px;font-size:13px;color:#44403C;border-bottom:1px solid #FEE2E2">{now} IST</td>
      </tr>
      <tr>
        <td style="padding:10px 12px;font-size:13px;color:#78716C">Migration Files</td>
        <td style="padding:10px 12px;font-size:12px;color:#44403C;font-family:monospace;word-break:break-all">{migration_files or "None found"}</td>
      </tr>
    </table>
  </td></tr>

  <!-- WHAT TO DO -->
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0;border-top:8px solid #F5EFE6">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">🔧 Immediate Actions</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #E8D5C0;background:#FFF8F2">
      <tr><td style="padding:8px 12px;font-size:12px;color:#44403C;border-bottom:1px solid #F5F5F4">1. SSH into server: <span style="font-family:monospace;color:#1D4ED8">ssh dishaan-hitech-it@132.154.156.82</span></td></tr>
      <tr><td style="padding:8px 12px;font-size:12px;color:#44403C;border-bottom:1px solid #F5F5F4">2. Check migration files: <span style="font-family:monospace;color:#1D4ED8">ls {APP_DIR}/migrations/versions/</span></td></tr>
      <tr><td style="padding:8px 12px;font-size:12px;color:#44403C;border-bottom:1px solid #F5F5F4">3. Check DB version: <span style="font-family:monospace;color:#1D4ED8">cd {APP_DIR} &amp;&amp; venv/bin/flask db current</span></td></tr>
      <tr><td style="padding:8px 12px;font-size:12px;color:#44403C;border-bottom:1px solid #F5F5F4">4. Check app logs: <span style="font-family:monospace;color:#1D4ED8">sudo journalctl -u {SERVICE} -n 50</span></td></tr>
      <tr><td style="padding:8px 12px;font-size:12px;color:#44403C">5. Fix sync if needed: <span style="font-family:monospace;color:#1D4ED8">flask db stamp head</span></td></tr>
    </table>
  </td></tr>

  <!-- LOG SNAPSHOT -->
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0;border-top:8px solid #F5EFE6">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">📜 {APP_NAME} Log Snapshot</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #FDE68A;background:#FFFDF5">
      <tbody>{log_rows(journal_logs)}</tbody>
    </table>
  </td></tr>

  <!-- FOOTER -->
  <tr><td style="background:#7C3E1B;padding:14px 20px;border-radius:0 0 12px 12px;text-align:center;border-top:8px solid #F5EFE6">
    <div style="font-size:10px;color:#FCD9B2;line-height:2">
      PRAX ERP Automated Alert System &nbsp;·&nbsp; Dishaan Hi-tech (India) Pvt. Ltd.<br>
      <a href="http://132.154.156.82/server-monitor/" style="color:#FDE68A;text-decoration:none">Server Monitor</a>
      &nbsp;|&nbsp;
      <a href="http://132.154.156.82/server-logs/" style="color:#FDE68A;text-decoration:none">Log Viewer</a>
    </div>
  </td></tr>

</table></td></tr></table>
</body></html>"""

try:
    msg = MIMEMultipart("alternative")
    msg["From"]             = f"PRAX ERP Alerts <{FROM_EMAIL}>"
    msg["To"]               = ", ".join(ALL_EMAILS)
    msg["Subject"]          = f"🔴 {APP_LABEL} — DB Migration FAILED | {now}"
    msg["Importance"]       = "high"
    msg["X-Priority"]       = "1"
    msg["X-MSMail-Priority"]= "High"
    msg["Priority"]         = "urgent"
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(FROM_EMAIL, APP_PASSWORD)
        s.sendmail(FROM_EMAIL, ALL_EMAILS, msg.as_string())
    print("✅ Migration failure alert sent")
except Exception as e:
    print(f"❌ Failed to send alert: {e}")
