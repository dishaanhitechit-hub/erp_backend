#!/usr/bin/env python3
"""
PRAX ERP Server Alert System v3
- No alert# counter — shows repeat count instead
- Skips email if same errors repeated (cooldown)
- DB migration detection and report
- Daily report at 8 AM
"""

import subprocess, smtplib, json, os, time, socket
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, date

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

ADMIN_EMAIL    = "dishaanhitechit@gmail.com"
MANAGER_EMAILS = ["rohan.soumyajit@gmail.com", "adas34965@gmail.com"]
ALL_EMAILS     = [ADMIN_EMAIL] + MANAGER_EMAILS

CPU_WARN=75;  CPU_CRIT=85
RAM_WARN=80;  RAM_CRIT=90
DISK_WARN=80; DISK_CRIT=90
TEMP_WARN=65; TEMP_CRIT=75
NVME_WARN=55; NVME_CRIT=65

STATE_FILE    = "/tmp/prax_alert_state.json"
DAILY_FILE    = "/tmp/prax_daily_stats.json"
SERVICES      = ["frontend","backend","postgresql","nginx","pgadmin4","logviewer","ssh"]
REPEAT_AFTER  = 6   # re-alert after same error repeats 6 times (1 hour)
MIN_ALERT_GAP = 300 # minimum seconds between alerts (5 min buffer)

# ── HELPERS ───────────────────────────────────────────────
def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=isinstance(cmd,str))
        return r.stdout.strip()
    except: return ""

def load_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except: return {"prev_issues": {}, "repeat_counts": {}, "daily_sent": ""}

def save_state(s):
    with open(STATE_FILE,"w") as f: json.dump(s, f)

def load_daily():
    try:
        with open(DAILY_FILE) as f: return json.load(f)
    except: return {"checks":0,"alerts":0,"max_cpu":0,"max_ram":0,"max_temp":0,"issues_seen":[]}

def save_daily(d):
    with open(DAILY_FILE,"w") as f: json.dump(d, f)

# ── CHECKS ────────────────────────────────────────────────
def get_cpu():
    def read():
        with open("/proc/stat") as f: line=f.readline()
        v=list(map(int,line.split()[1:]))
        return v[3],sum(v)
    i1,t1=read(); time.sleep(1); i2,t2=read()
    return round(100*(1-(i2-i1)/(t2-t1)),1)

def get_ram():
    with open("/proc/meminfo") as f: lines=f.readlines()
    m={}
    for l in lines:
        p=l.split()
        if len(p)>=2: m[p[0].rstrip(":")]=int(p[1])
    tot=m.get("MemTotal",1); av=m.get("MemAvailable",0); used=tot-av
    return round(used/tot*100,1), round(used/1024/1024,2), round(tot/1024/1024,2)

def get_disks():
    disks=[]
    out=run("df -h --output=source,size,used,avail,pcent,target | tail -n +2")
    for l in out.splitlines():
        p=l.split()
        if len(p)<6: continue
        if not any(p[0].startswith(x) for x in ["/dev/nvme","/dev/sd"]): continue
        disks.append({"device":p[0],"size":p[1],"used":p[2],"avail":p[3],"pct":int(p[4].replace("%","")),"mount":p[5]})
    return disks

def get_temps():
    t={"cpu":None,"nvme":[]}
    try:
        out=run("sensors")
        for l in out.splitlines():
            if "Package id 0" in l and "+" in l: t["cpu"]=float(l.split("+")[1].split("°")[0])
            if "Composite" in l and "+" in l: t["nvme"].append(float(l.split("+")[1].split("°")[0]))
    except: pass
    return t

def check_services():
    return [s for s in SERVICES if run(f"systemctl is-active {s}.service")!="active"]

def check_db():
    # pg_isready needs no sudo or password. The old "sudo -u postgres psql"
    # check always failed when run as the normal user (sudo wants a password),
    # which sent a false "Database UNREACHABLE" CRITICAL.
    try:
        r=subprocess.run(["pg_isready","-h","127.0.0.1","-p","5432","-d","erp_db","-t","5"],
            capture_output=True,text=True,timeout=10)
        return r.returncode==0
    except: return False

def check_api(port):
    try:
        r=subprocess.run(["curl","-s","-o","/dev/null","-w","%{http_code}",f"http://127.0.0.1:{port}/health"],
            capture_output=True,text=True,timeout=5)
        return r.stdout.strip()=="200"
    except: return False

def get_uptime():
    with open("/proc/uptime") as f: secs=float(f.read().split()[0])
    d=int(secs//86400); h=int((secs%86400)//3600); m=int((secs%3600)//60)
    return f"{d}d {h}h {m}m"

def get_db_migrations():
    """Get recent alembic migrations from DB"""
    # As the ERP's own database user from /srv/backend/.env (the old
    # "sudo -u postgres psql" always failed without a sudo password).
    from prax_ops.alert_settings import alembic_version
    return alembic_version(_os.environ.get("PRAX_BACKEND_DIR", "/srv/backend"))

def get_recent_migration_log():
    """Get last 5 migration related lines from backend journal"""
    out=run("journalctl -u backend.service -n 200 --no-pager | grep -i 'migrat\\|alembic\\|upgrade\\|revision' | tail -5")
    return out


def get_service_logs(service_name, lines=20):
    """Get last N lines of a service log for snapshot"""
    out = run(f"journalctl -u {service_name}.service -n {lines} --no-pager --output=short-iso 2>/dev/null")
    return out or f"No logs available for {service_name}"

def get_error_snapshot(issues):
    """Get log snapshots for all failed services/components"""
    snapshots = {}
    for iss in issues:
        comp = iss.get("component","")
        if comp.startswith("Service:"):
            svc = comp.replace("Service:","")
            if svc not in snapshots:
                snapshots[svc] = get_service_logs(svc, 15)
        elif comp == "PostgreSQL":
            snapshots["postgresql"] = get_service_logs("postgresql", 10)
        elif comp in ["CPU","RAM","Temperature"]:
            snapshots["system"] = run("top -bn1 | head -15")
    return snapshots

def log_snapshot_html(snapshots):
    """Build HTML for log snapshots"""
    if not snapshots:
        return ""
    rows = ""
    for svc, logs in snapshots.items():
        log_lines = ""
        for line in logs.splitlines()[:15]:
            if line.strip():
                # Color error lines red
                color = "#991B1B" if any(w in line.lower() for w in ["error","fail","exception","traceback","critical"]) else "#44403C"
                log_lines += f'''<tr><td style="padding:3px 10px;font-size:11px;color:{color};font-family:monospace;border-bottom:1px solid #FEF3C7;word-break:break-all;line-height:1.5">{line[:120]}</td></tr>'''
        rows += f'''
        <div style="margin-bottom:12px">
          <div style="font-size:11px;font-weight:700;color:#78350F;text-transform:uppercase;letter-spacing:.5px;padding:6px 10px;background:#FEF3C7;border-radius:4px 4px 0 0">{svc} logs</div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FFFDF5;border:1px solid #FDE68A;border-top:none;border-radius:0 0 4px 4px">
            <tbody>{log_lines}</tbody>
          </table>
        </div>'''
    return f'''
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0;border-top:8px solid #F5EFE6">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">📜 Error Log Snapshot</div>
    {rows}
  </td></tr>'''

# ── EMAIL HELPERS ─────────────────────────────────────────
def send_email(to_list, subject, html_body, priority=False):
    if not to_list:
        print(f"⏭ No recipients set for: {subject}"); return False
    try:
        msg=MIMEMultipart("alternative")
        msg["From"]            = f"PRAX ERP Alerts <{FROM_EMAIL}>"
        msg["To"]              = ", ".join(to_list)
        msg["Subject"]         = subject
        msg["Importance"]      = "high"
        msg["X-Priority"]      = "1" if priority else "3"
        msg["X-MSMail-Priority"]="High" if priority else "Normal"
        msg["Priority"]        = "urgent" if priority else "normal"
        msg.attach(MIMEText(html_body,"html"))
        with smtplib.SMTP(SMTP_HOST,SMTP_PORT) as s:
            s.starttls(); s.login(FROM_EMAIL,APP_PASSWORD)
            s.sendmail(FROM_EMAIL,to_list,msg.as_string())
        print(f"✅ Sent to {to_list}")
        return True
    except Exception as e:
        print(f"❌ Email failed: {e}"); return False

def header_html(hostname):
    return f"""<tr><td style="background:#7C3E1B;padding:16px 20px;border-radius:12px 12px 0 0;text-align:center">
    <div style="font-size:10px;color:#FCD9B2;letter-spacing:2px;text-transform:uppercase;margin-bottom:3px">Dishaan Hi-tech (India) Pvt. Ltd.</div>
    <div style="font-size:18px;font-weight:800;color:#FFFFFF">PRAX ERP Alert System</div>
    <div style="font-size:10px;color:#FCD9B2;margin-top:2px">{hostname} &nbsp;·&nbsp; 132.154.156.82</div>
  </td></tr>"""

def footer_html():
    return """<tr><td style="background:#7C3E1B;padding:14px 20px;border-radius:0 0 12px 12px;text-align:center;border-top:8px solid #F5EFE6">
    <div style="font-size:10px;color:#FCD9B2;line-height:2">
      PRAX ERP Automated Alert System &nbsp;·&nbsp; Dishaan Hi-tech (India) Pvt. Ltd.<br>
      <a href="http://132.154.156.82/server-monitor/" style="color:#FDE68A;text-decoration:none">Server Monitor</a>
      &nbsp;|&nbsp;
      <a href="http://132.154.156.82/server-logs/" style="color:#FDE68A;text-decoration:none">Log Viewer</a>
    </div>
  </td></tr>"""

def wrap_email(inner, hostname):
    return f"""<!DOCTYPE html><html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<meta name="x-apple-disable-message-reformatting"></head>
<body style="margin:0;padding:0;background:#F5EFE6;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background:#F5EFE6;padding:16px 8px">
<tr><td align="center">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width:560px">
{header_html(hostname)}
{inner}
{footer_html()}
</table></td></tr></table></body></html>"""

def srow(label, val, vc="#1C1917"):
    return f"""<tr>
      <td style="padding:10px 12px;font-size:13px;color:#78716C;border-bottom:1px solid #F5F5F4;width:45%;vertical-align:top">{label}</td>
      <td style="padding:10px 12px;font-size:13px;color:{vc};font-weight:600;border-bottom:1px solid #F5F5F4;word-break:break-word">{val}</td>
    </tr>"""

def disk_row(d):
    if d['pct']>=90: pc,bc="#7F1D1D","#FECACA"
    elif d['pct']>=80: pc,bc="#78350F","#FCD34D"
    else: pc,bc="#14532D","#86EFAC"
    return f"""<tr><td style="padding:12px 14px;border-bottom:1px solid #F5F5F4">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr><td style="font-size:12px;color:#78716C;padding-bottom:4px">{d['device']}</td>
            <td style="font-size:12px;color:#44403C;font-weight:700;text-align:right;padding-bottom:4px">{d['mount']}</td></tr>
      </table>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#E7E5E4;border-radius:4px;height:10px">
        <tr><td width="{d['pct']}%" style="background:{bc};border-radius:4px;height:10px;font-size:0">&nbsp;</td><td></td></tr>
      </table>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:4px">
        <tr><td style="font-size:11px;color:#78716C">{d['used']} used / {d['size']} total ({d['avail']} free)</td>
            <td style="font-size:12px;color:{pc};font-weight:700;text-align:right">{d['pct']}%</td></tr>
      </table>
    </td></tr>"""

# ── ALERT EMAIL ───────────────────────────────────────────
def build_alert_html(issues, stats, repeat_map):
    now=datetime.now().strftime("%d %b %Y %H:%M:%S")
    hostname=socket.gethostname()
    has_crit=any(i["level"]=="CRITICAL" for i in issues)

    if not issues:
        s_emoji,s_text,s_bg,s_border,s_color="✅","All Systems Healthy","#F6FFF0","#A7F3A0","#14532D"
    elif has_crit:
        s_emoji,s_text,s_bg,s_border,s_color="🔴","Critical Alert","#FFF8F8","#FECACA","#7F1D1D"
    else:
        s_emoji,s_text,s_bg,s_border,s_color="⚠️","Warning Detected","#FFFDF0","#FDE68A","#78350F"

    issues_html=""
    if issues:
        for iss in issues:
            key=f"{iss['level']}:{iss['component']}"
            repeat=repeat_map.get(key,1)
            repeat_badge=f'<span style="background:#E0E7FF;color:#3730A3;font-size:10px;padding:1px 7px;border-radius:20px;margin-left:6px">🔁 {repeat}x</span>' if repeat>1 else ""
            if iss["level"]=="CRITICAL": b_bg,b_color,row_bg,border="#FEE2E2","#7F1D1D","#FFF8F8","#FECACA"
            else: b_bg,b_color,row_bg,border="#FEF3C7","#78350F","#FFFDF5","#FDE68A"
            issues_html+=f"""<tr><td style="padding:0;border-bottom:6px solid #F5EFE6">
              <div style="background:{row_bg};border-left:4px solid {border};padding:12px 14px">
                <div style="margin-bottom:4px">
                  <span style="background:{b_bg};color:{b_color};font-size:11px;font-weight:700;padding:2px 10px;border-radius:20px">{iss['level']}</span>
                  &nbsp;<span style="font-size:13px;font-weight:700;color:#1C1917">{iss['component']}</span>{repeat_badge}
                </div>
                <div style="font-size:12px;color:#44403C;line-height:1.6;word-break:break-word">{iss['message']}</div>
              </div></td></tr>"""
    else:
        issues_html='<tr><td style="padding:14px;text-align:center;color:#166534;font-size:13px;background:#F0FFF4">✅ No issues — all systems operating normally</td></tr>'

    ct=stats['cpu_temp']
    ct_color="#166534" if ct!="N/A" and float(str(ct))<65 else "#991B1B"
    stats_rows=(
        srow("⚡ CPU",f"{stats['cpu']}%","#1D4ED8" if stats['cpu']<75 else "#991B1B")+
        srow("🧠 RAM",f"{stats['ram_pct']}%  ({stats['ram_used']} GB / {stats['ram_total']} GB)")+
        srow("🌡 CPU Temp",f"{ct}°C",ct_color)+
        srow("⏱ Uptime",stats['uptime'])+
        srow("🗄 Database","✅ Connected" if stats['db_ok'] else "❌ UNREACHABLE","#166534" if stats['db_ok'] else "#991B1B")+
        srow("📋 Log Viewer","✅ Running" if stats['logviewer_ok'] else "❌ DOWN","#166534" if stats['logviewer_ok'] else "#92400E")+
        srow("🕐 Checked",now)
    )
    disk_rows="".join(disk_row(d) for d in stats['disks'])
    snapshots=get_error_snapshot(issues) if issues else {}
    log_snapshot=log_snapshot_html(snapshots)

    inner=f"""
  <tr><td style="background:{s_bg};border-left:3px solid {s_border};border-right:3px solid {s_border};padding:20px;text-align:center">
    <div style="font-size:40px;line-height:1;margin-bottom:8px">{s_emoji}</div>
    <div style="font-size:20px;font-weight:800;color:{s_color};margin-bottom:6px">{s_text}</div>
    <div style="font-size:11px;color:#78716C">{now} IST &nbsp;·&nbsp; Checks every 10 min</div>
  </td></tr>
  <tr><td style="background:#FFFAF5;padding:16px 16px 8px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">⚡ Issues</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #E8D5C0"><tbody>{issues_html}</tbody></table>
  </td></tr>
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0;border-top:8px solid #F5EFE6">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">📊 System Stats</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #E8D5C0;background:#FFF8F2"><tbody>{stats_rows}</tbody></table>
  </td></tr>
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0;border-top:8px solid #F5EFE6">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">💾 Disk Storage</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #E8D5C0;background:#FFF8F2"><tbody>{disk_rows}</tbody></table>
  </td></tr>
  {log_snapshot}"""

    return wrap_email(inner, hostname)

# ── MIGRATION EMAIL ───────────────────────────────────────
def build_migration_html(version, log_lines):
    now=datetime.now().strftime("%d %b %Y %H:%M:%S")
    hostname=socket.gethostname()
    log_rows=""
    for l in (log_lines or "No migration logs found").splitlines():
        if l.strip():
            log_rows+=f'<tr><td style="padding:6px 12px;font-size:12px;color:#1C1917;border-bottom:1px solid #F5F5F4;font-family:monospace;word-break:break-all">{l}</td></tr>'

    inner=f"""
  <tr><td style="background:#EFF6FF;border-left:3px solid #93C5FD;border-right:3px solid #93C5FD;padding:20px;text-align:center">
    <div style="font-size:36px;margin-bottom:8px">🗄</div>
    <div style="font-size:20px;font-weight:800;color:#1E3A8A;margin-bottom:6px">Database Migration Detected</div>
    <div style="font-size:11px;color:#78716C">{now} IST</div>
  </td></tr>
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">📋 Migration Details</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #E8D5C0;background:#FFF8F2">
      {srow("Current Version", version or "Unknown", "#1D4ED8")}
      {srow("Detected At", now)}
      {srow("Server", hostname)}
    </table>
  </td></tr>
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0;border-top:8px solid #F5EFE6">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">📜 Recent Migration Log</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #E8D5C0;background:#FFFDF5">
      <tbody>{log_rows}</tbody>
    </table>
  </td></tr>"""

    return wrap_email(inner, hostname)

# ── DAILY REPORT EMAIL ────────────────────────────────────
def build_daily_html(daily, stats):
    now=datetime.now().strftime("%d %b %Y")
    hostname=socket.gethostname()
    seen=list(set(daily.get("issues_seen",[])))
    issues_summary=""
    if seen:
        for iss in seen:
            issues_summary+=f'<tr><td style="padding:8px 12px;font-size:12px;color:#44403C;border-bottom:1px solid #F5F5F4">⚠️ {iss}</td></tr>'
    else:
        issues_summary='<tr><td style="padding:12px;text-align:center;color:#166534;font-size:13px">✅ No issues in last 24 hours</td></tr>'

    disk_rows="".join(disk_row(d) for d in stats['disks'])
    ct=stats['cpu_temp']
    ct_color="#166534" if ct!="N/A" and float(str(ct))<65 else "#991B1B"

    inner=f"""
  <tr><td style="background:#FFFBEB;border-left:3px solid #FCD34D;border-right:3px solid #FCD34D;padding:20px;text-align:center">
    <div style="font-size:36px;margin-bottom:8px">📅</div>
    <div style="font-size:20px;font-weight:800;color:#78350F;margin-bottom:6px">Daily Server Report</div>
    <div style="font-size:11px;color:#78716C">{now} &nbsp;·&nbsp; PRAX ERP Production Server</div>
  </td></tr>
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">📊 24-Hour Summary</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #E8D5C0;background:#FFF8F2">
      {srow("Total Checks Run", str(daily.get("checks",0)))}
      {srow("Alerts Sent", str(daily.get("alerts",0)), "#991B1B" if daily.get("alerts",0)>0 else "#166534")}
      {srow("Peak CPU", f"{daily.get('max_cpu',0)}%", "#991B1B" if daily.get('max_cpu',0)>=75 else "#166534")}
      {srow("Peak RAM", f"{daily.get('max_ram',0)}%", "#991B1B" if daily.get('max_ram',0)>=80 else "#166534")}
      {srow("Peak CPU Temp", f"{daily.get('max_temp',0)}°C", "#991B1B" if daily.get('max_temp',0)>=65 else "#166534")}
      {srow("Server Uptime", stats['uptime'])}
      {srow("Database", "✅ Connected" if stats['db_ok'] else "❌ UNREACHABLE", "#166534" if stats['db_ok'] else "#991B1B")}
    </table>
  </td></tr>
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0;border-top:8px solid #F5EFE6">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">⚡ Issues in Last 24h</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #E8D5C0;background:#FFF8F2">
      <tbody>{issues_summary}</tbody>
    </table>
  </td></tr>
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0;border-top:8px solid #F5EFE6">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">💾 Current Disk</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #E8D5C0;background:#FFF8F2">
      <tbody>{disk_rows}</tbody>
    </table>
  </td></tr>"""

    return wrap_email(inner, hostname)


# ── RECOVERY EMAIL ────────────────────────────────────────
def build_recovery_html(resolved_keys, stats):
    now=datetime.now().strftime("%d %b %Y %H:%M:%S")
    hostname=socket.gethostname()
    resolved_rows=""
    for k in resolved_keys:
        parts=k.split(":",1)
        comp=parts[1] if len(parts)>1 else k
        resolved_rows+=f'''<tr><td style="padding:10px 12px;font-size:13px;color:#166534;border-bottom:1px solid #F5F5F4">✅ {comp} — Recovered</td></tr>'''

    ct=stats['cpu_temp']
    ct_color="#166534" if ct!="N/A" and float(str(ct))<65 else "#991B1B"
    stats_rows=(
        srow("⚡ CPU",f"{stats['cpu']}%")+
        srow("🧠 RAM",f"{stats['ram_pct']}% ({stats['ram_used']} GB / {stats['ram_total']} GB)")+
        srow("🌡 CPU Temp",f"{ct}°C",ct_color)+
        srow("⏱ Uptime",stats['uptime'])+
        srow("🗄 Database","✅ Connected" if stats['db_ok'] else "❌ UNREACHABLE","#166534" if stats['db_ok'] else "#991B1B")
    )

    inner=f"""
  <tr><td style="background:#F0FFF4;border-left:3px solid #86EFAC;border-right:3px solid #86EFAC;padding:20px;text-align:center">
    <div style="font-size:40px;line-height:1;margin-bottom:8px">🟢</div>
    <div style="font-size:20px;font-weight:800;color:#14532D;margin-bottom:6px">All Systems Recovered</div>
    <div style="font-size:11px;color:#78716C">{now} IST — All previous issues resolved</div>
  </td></tr>
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">✅ Resolved Issues</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #E8D5C0;background:#F0FFF4">
      <tbody>{resolved_rows}</tbody>
    </table>
  </td></tr>
  <tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0;border-top:8px solid #F5EFE6">
    <div style="font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">📊 Current Stats</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-radius:8px;overflow:hidden;border:1px solid #E8D5C0;background:#FFF8F2">
      <tbody>{stats_rows}</tbody>
    </table>
  </td></tr>"""
    return wrap_email(inner, hostname)

# ── SUBJECT BUILDER ───────────────────────────────────────
def get_subject(issues, is_new):
    now=datetime.now().strftime("%d %b %H:%M")
    if not issues: return f"✅ PRAX ERP — All Systems Healthy | {now}"
    crits=[i for i in issues if i["level"]=="CRITICAL"]
    tag="🔴 CRITICAL" if crits else "⚠️ Warning"
    comps=", ".join(set(i["component"] for i in (crits or issues)))
    new_tag=" [NEW]" if is_new else " [ONGOING]"
    return f"{tag} — {comps}{new_tag} | {now}"

# ── MAIN ──────────────────────────────────────────────────
def main():
    state=load_state()
    daily=load_daily()
    now_hour=datetime.now().hour
    today=str(date.today())

    print(f"\n{'='*50}")
    print(f"PRAX Alert — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    # ── Collect metrics ──
    cpu=get_cpu(); print(f"CPU: {cpu}%")
    ram_pct,ram_used,ram_total=get_ram(); print(f"RAM: {ram_pct}%")
    disks=get_disks()
    temps=get_temps(); cpu_temp=temps["cpu"]; print(f"CPU Temp: {cpu_temp}°C")
    down=check_services(); print(f"Down: {down}")
    # Only check DB connection if postgresql service is running
    pg_running="postgresql" not in down
    if pg_running:
        db_ok=check_db(); print(f"DB: {'OK' if db_ok else 'FAILED'}")
    else:
        db_ok=False; print("DB: Skipped (postgresql service is down)")
    log_ok=check_api(6789)
    mon_ok=check_api(6790)
    uptime=get_uptime()

    # ── Update daily stats ──
    daily["checks"]=daily.get("checks",0)+1
    daily["max_cpu"]=max(daily.get("max_cpu",0), cpu)
    daily["max_ram"]=max(daily.get("max_ram",0), ram_pct)
    if cpu_temp: daily["max_temp"]=max(daily.get("max_temp",0), cpu_temp)

    # ── Build issues list ──
    issues=[]
    if cpu>=CPU_CRIT: issues.append({"level":"CRITICAL","component":"CPU","message":f"CPU critical: {cpu}% (limit {CPU_CRIT}%)"})
    elif cpu>=CPU_WARN: issues.append({"level":"WARNING","component":"CPU","message":f"CPU high: {cpu}% (limit {CPU_WARN}%)"})
    if ram_pct>=RAM_CRIT: issues.append({"level":"CRITICAL","component":"RAM","message":f"RAM critical: {ram_pct}% ({ram_used}GB/{ram_total}GB)"})
    elif ram_pct>=RAM_WARN: issues.append({"level":"WARNING","component":"RAM","message":f"RAM high: {ram_pct}% ({ram_used}GB/{ram_total}GB)"})
    for d in disks:
        if d['pct']>=DISK_CRIT: issues.append({"level":"CRITICAL","component":f"Disk {d['mount']}","message":f"Disk critical: {d['pct']}% on {d['device']}"})
        elif d['pct']>=DISK_WARN: issues.append({"level":"WARNING","component":f"Disk {d['mount']}","message":f"Disk warning: {d['pct']}% on {d['device']}"})
    if cpu_temp:
        if cpu_temp>=TEMP_CRIT: issues.append({"level":"CRITICAL","component":"Temperature","message":f"CPU temp critical: {cpu_temp}°C"})
        elif cpu_temp>=TEMP_WARN: issues.append({"level":"WARNING","component":"Temperature","message":f"CPU temp high: {cpu_temp}°C"})
    for i,nt in enumerate(temps["nvme"]):
        if nt>=NVME_CRIT: issues.append({"level":"CRITICAL","component":f"NVMe {i}","message":f"NVMe temp critical: {nt}°C"})
        elif nt>=NVME_WARN: issues.append({"level":"WARNING","component":f"NVMe {i}","message":f"NVMe temp high: {nt}°C"})
    for svc in down:
        lv="CRITICAL" if svc in ["backend","frontend","postgresql","nginx"] else "WARNING"
        issues.append({"level":lv,"component":f"Service:{svc}","message":f"'{svc}' is DOWN"})
    if pg_running and not db_ok: issues.append({"level":"CRITICAL","component":"PostgreSQL","message":"Database UNREACHABLE on localhost:5432"})
    if not log_ok: issues.append({"level":"WARNING","component":"LogViewer","message":"Log viewer API down on port 6789"})
    if not mon_ok: issues.append({"level":"WARNING","component":"MonitorAPI","message":"Monitor API down on port 6790"})

    # ── Cooldown logic — skip if same errors, resend after REPEAT_AFTER ──
    prev=state.get("prev_issues",{})
    repeat_counts=state.get("repeat_counts",{})
    current_keys=set(f"{i['level']}:{i['component']}" for i in issues)
    prev_keys=set(prev.keys())

    new_keys=current_keys - prev_keys
    resolved_keys=prev_keys - current_keys
    ongoing_keys=current_keys & prev_keys

    # Update repeat counts
    for k in list(repeat_counts.keys()):
        if k not in current_keys: del repeat_counts[k]
    for k in current_keys:
        repeat_counts[k]=repeat_counts.get(k,0)+1

    # 5-min buffer — don't send if last alert was too recent
    now_ts=time.time()
    last_alert_ts=state.get("last_alert_ts",0)
    time_since_last=now_ts-last_alert_ts

    # Decide whether to send alert
    should_send=False
    is_new=False
    is_recovery=False

    if new_keys:
        should_send=True; is_new=True
        print(f"New issues: {new_keys}")
    elif resolved_keys and not current_keys:
        # ALL issues resolved — send recovery email
        should_send=True; is_recovery=True
        print(f"All resolved: {resolved_keys}")
    elif resolved_keys:
        # Some resolved, some still ongoing
        should_send=True
        print(f"Partially resolved: {resolved_keys}")
    elif ongoing_keys:
        # Resend if any issue has hit repeat threshold
        for k in ongoing_keys:
            if repeat_counts.get(k,1) % REPEAT_AFTER == 0:
                should_send=True
                print(f"Repeat threshold hit for: {k}")
                break

    # Apply 5-min buffer (skip if too soon, unless it's a recovery or new critical)
    if should_send and not is_recovery and not is_new:
        if time_since_last < MIN_ALERT_GAP:
            print(f"Buffer active — last alert {int(time_since_last)}s ago, skipping")
            should_send=False

    # Track issues seen for daily report
    for iss in issues:
        label=f"{iss['component']}: {iss['message']}"
        seen=daily.get("issues_seen",[])
        if label not in seen: seen.append(label)
        daily["issues_seen"]=seen[-20:]  # keep last 20

    stats={
        "cpu":cpu,"ram_pct":ram_pct,"ram_used":ram_used,"ram_total":ram_total,
        "cpu_temp":cpu_temp or "N/A","uptime":uptime,
        "db_ok":db_ok,"logviewer_ok":log_ok,"disks":disks
    }

    if should_send:
        if is_recovery:
            subject=f"🟢 PRAX ERP — All Systems Recovered | {datetime.now().strftime('%d %b %H:%M')}"
            html=build_recovery_html(resolved_keys, stats)
            print(f"\nSending recovery email to all")
            send_email(to("server_recovery", ALL_EMAILS), subject, html, priority=False)
        else:
            subject=get_subject(issues, is_new)
            html=build_alert_html(issues, stats, repeat_counts)
            print(f"\nSending alert to admin")
            send_email(to("server_alert", [ADMIN_EMAIL]), subject, html, priority=bool(issues))
            crits=[i for i in issues if i["level"]=="CRITICAL"]
            if crits and is_new:
                print(f"Sending CRITICAL to managers")
                send_email(to("server_critical", MANAGER_EMAILS), subject, html, priority=True)
            if issues: daily["alerts"]=daily.get("alerts",0)+1
        state["last_alert_ts"]=now_ts
    elif not issues:
        pass  # all healthy — no email needed unless it was previously broken
    else:
        print(f"Skipping — same ongoing issues (buffer or repeat)")

    # ── Migration check ──
    current_version=get_db_migrations()
    prev_version=state.get("db_version","")
    if current_version and current_version!=prev_version and prev_version:
        print(f"Migration detected: {prev_version} → {current_version}")
        log_lines=get_recent_migration_log()
        mig_html=build_migration_html(current_version, log_lines)
        send_email(to("server_migration", ALL_EMAILS), f"🗄 PRAX ERP — DB Migration Detected | {datetime.now().strftime('%d %b %H:%M')}", mig_html)
    if current_version: state["db_version"]=current_version

    # ── Daily report at 8 AM ──
    if now_hour==8 and state.get("daily_sent","")!=today:
        print("Sending daily report")
        daily_html=build_daily_html(daily, stats)
        send_email(to("server_daily", ALL_EMAILS), f"📅 PRAX ERP Daily Report — {datetime.now().strftime('%d %b %Y')}", daily_html)
        state["daily_sent"]=today
        daily={"checks":0,"alerts":0,"max_cpu":0,"max_ram":0,"max_temp":0,"issues_seen":[]}

    # ── Update state ──
    state["prev_issues"]={f"{i['level']}:{i['component']}":i['message'] for i in issues}
    state["repeat_counts"]=repeat_counts
    save_state(state)
    save_daily(daily)
    print(f"\nDone.")

if __name__=="__main__":
    main()
