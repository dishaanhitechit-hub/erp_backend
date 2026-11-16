"""PRAX alert email look — the same family as the server alert emails
(brown header, coloured status banner, sections of label/value rows, log
snapshot, footer links). Table-based inline HTML so it renders in Gmail,
Outlook and phone mail apps. All values are HTML-escaped here.
"""

import html
import os
import socket
from datetime import datetime

COMPANY = "Dishaan Hi-tech (India) Pvt. Ltd."
SERVER_IP = os.getenv("PRAX_SERVER_IP", "132.154.156.82")
CONSOLE_URL = os.getenv("PRAX_CONSOLE_URL", f"http://{SERVER_IP}:6800/")

# status → (emoji, banner bg, banner border, title colour)
LEVELS = {
    "ok":       ("✅", "#F0FFF4", "#86EFAC", "#14532D"),
    "info":     ("ℹ️", "#EFF6FF", "#93C5FD", "#1E3A8A"),
    "warning":  ("⚠️", "#FFFDF0", "#FDE68A", "#78350F"),
    "critical": ("🔴", "#FFF8F8", "#FECACA", "#7F1D1D"),
    "report":   ("📅", "#FFFBEB", "#FCD34D", "#78350F"),
}
GOOD, BAD, WARN, MUTED, TEXT = "#166534", "#991B1B", "#92400E", "#78716C", "#1C1917"

_SECTION_TITLE = ("font-size:12px;font-weight:700;color:#44403C;text-transform:uppercase;"
                  "letter-spacing:.8px;margin-bottom:10px")
_BOX = "border-radius:8px;overflow:hidden;border:1px solid #E8D5C0;background:#FFF8F2"


def esc(value):
    return html.escape("" if value is None else str(value))


def header(title="PRAX ERP Alert System"):
    return f"""<tr><td style="background:#7C3E1B;padding:16px 20px;border-radius:12px 12px 0 0;text-align:center">
    <div style="font-size:10px;color:#FCD9B2;letter-spacing:2px;text-transform:uppercase;margin-bottom:3px">{esc(COMPANY)}</div>
    <div style="font-size:18px;font-weight:800;color:#FFFFFF">{esc(title)}</div>
    <div style="font-size:10px;color:#FCD9B2;margin-top:2px">{esc(socket.gethostname())} &nbsp;·&nbsp; {esc(SERVER_IP)}</div>
  </td></tr>"""


def footer():
    link = "color:#FDE68A;text-decoration:none"
    return f"""<tr><td style="background:#7C3E1B;padding:14px 20px;border-radius:0 0 12px 12px;text-align:center;border-top:8px solid #F5EFE6">
    <div style="font-size:10px;color:#FCD9B2;line-height:2">
      PRAX ERP Automated Alert System &nbsp;·&nbsp; {esc(COMPANY)}<br>
      <a href="{esc(CONSOLE_URL)}" style="{link}">Ops Console</a> &nbsp;|&nbsp;
      <a href="http://{esc(SERVER_IP)}/server-monitor/" style="{link}">Server Monitor</a> &nbsp;|&nbsp;
      <a href="http://{esc(SERVER_IP)}/server-logs/" style="{link}">Log Viewer</a>
    </div>
  </td></tr>"""


def banner(level, title, subtitle=""):
    emoji, bg, border, colour = LEVELS[level]
    return f"""<tr><td style="background:{bg};border-left:3px solid {border};border-right:3px solid {border};padding:20px;text-align:center">
    <div style="font-size:40px;line-height:1;margin-bottom:8px">{emoji}</div>
    <div style="font-size:20px;font-weight:800;color:{colour};margin-bottom:6px">{esc(title)}</div>
    <div style="font-size:11px;color:{MUTED}">{esc(subtitle)}</div>
  </td></tr>"""


def section(title, body_rows, first=False, box_style=_BOX):
    top = "" if first else "border-top:8px solid #F5EFE6;"
    return f"""<tr><td style="background:#FFFAF5;padding:16px;border-left:3px solid #E8D5C0;border-right:3px solid #E8D5C0;{top}">
    <div style="{_SECTION_TITLE}">{esc(title)}</div>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="{box_style}"><tbody>{body_rows}</tbody></table>
  </td></tr>"""


def row(label, value, colour=TEXT, mono=False):
    font = "font-family:monospace;" if mono else ""
    return f"""<tr>
      <td style="padding:10px 12px;font-size:13px;color:{MUTED};border-bottom:1px solid #F5F5F4;width:40%;vertical-align:top">{esc(label)}</td>
      <td style="padding:10px 12px;font-size:13px;color:{colour};font-weight:600;border-bottom:1px solid #F5F5F4;word-break:break-word;{font}">{esc(value)}</td>
    </tr>"""


def line(text, colour="#44403C", icon=""):
    return (f'<tr><td style="padding:9px 12px;font-size:12px;color:{colour};border-bottom:1px solid #F5F5F4;'
            f'line-height:1.6;word-break:break-word">{esc(icon + " " if icon else "")}{esc(text)}</td></tr>')


def badge(text, kind):
    colours = {"ok": ("#DCFCE7", GOOD), "bad": ("#FEE2E2", "#7F1D1D"), "warn": ("#FEF3C7", "#78350F"),
               "info": ("#E0E7FF", "#3730A3")}
    bg, fg = colours.get(kind, colours["info"])
    return (f'<span style="background:{bg};color:{fg};font-size:10px;font-weight:700;padding:2px 8px;'
            f'border-radius:20px;white-space:nowrap">{esc(text)}</span>')


def table(headers, rows_html):
    """Small multi-column table; rows_html: list of lists of already-safe cell HTML."""
    th = "".join(f'<td style="padding:8px 8px;font-size:10px;color:{MUTED};text-transform:uppercase;'
                 f'letter-spacing:.5px;border-bottom:1px solid #E8D5C0;font-weight:700">{esc(h)}</td>' for h in headers)
    body = ""
    for cells in rows_html:
        body += "<tr>" + "".join(f'<td style="padding:8px 8px;font-size:12px;color:#44403C;'
                                 f'border-bottom:1px solid #F5F5F4;vertical-align:top">{c}</td>' for c in cells) + "</tr>"
    return f"<tr>{th}</tr>{body}"


def bar(label, pct, detail):
    pct = max(0, min(100, int(round(pct or 0))))
    if pct >= 90:
        fill, colour = "#FECACA", "#7F1D1D"
    elif pct >= 80:
        fill, colour = "#FCD34D", "#78350F"
    else:
        fill, colour = "#86EFAC", "#14532D"
    return f"""<tr><td style="padding:12px 14px;border-bottom:1px solid #F5F5F4">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr><td style="font-size:12px;color:#44403C;font-weight:700;padding-bottom:4px">{esc(label)}</td>
            <td style="font-size:12px;color:{colour};font-weight:700;text-align:right;padding-bottom:4px">{pct}%</td></tr>
      </table>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#E7E5E4;border-radius:4px;height:10px">
        <tr><td width="{max(pct, 1)}%" style="background:{fill};border-radius:4px;height:10px;font-size:0">&nbsp;</td><td></td></tr>
      </table>
      <div style="font-size:11px;color:{MUTED};margin-top:4px">{esc(detail)}</div>
    </td></tr>"""


def log_block(lines):
    out = ""
    for ln in lines:
        if not str(ln).strip():
            continue
        low = str(ln).lower()
        colour = BAD if any(w in low for w in ("error", "fail", "exception", "traceback", "critical")) else "#44403C"
        out += (f'<tr><td style="padding:3px 10px;font-size:11px;color:{colour};font-family:monospace;'
                f'border-bottom:1px solid #FEF3C7;word-break:break-all;line-height:1.5">{esc(str(ln)[:300])}</td></tr>')
    return out or line("(no log lines)")


LOG_BOX = "border-radius:8px;overflow:hidden;border:1px solid #FDE68A;background:#FFFDF5"


def page(inner, title="PRAX ERP Alert System"):
    return f"""<!DOCTYPE html><html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<meta name="x-apple-disable-message-reformatting"></head>
<body style="margin:0;padding:0;background:#F5EFE6;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background:#F5EFE6;padding:16px 8px">
<tr><td align="center">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width:600px">
{header(title)}
{inner}
{footer()}
</table></td></tr></table></body></html>"""


def now_text():
    return datetime.now().strftime("%d %b %Y %H:%M:%S")
