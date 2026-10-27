"""
HTML email template builder.
Palette  — navy header, white body, slate-gray text, steel-blue accents.
No images, no external fonts; renders cleanly in Gmail / Outlook.
"""
from datetime import datetime


# ── Palette ──────────────────────────────────────────────────────────────────
_NAVY       = "#1B2A4A"   # header background
_STEEL      = "#2C5282"   # project section border / sub-header
_BODY_BG    = "#F0F2F5"   # page background
_CARD_BG    = "#FFFFFF"   # card / table background
_STAT_BG    = "#EBF0F9"   # stat-box background
_BORDER     = "#CBD5E0"   # table / divider lines
_TEXT_MAIN  = "#1A202C"   # primary text
_TEXT_MUTED = "#718096"   # secondary / label text
_GREEN      = "#276749"   # positive amount
_STRIPE     = "#F7FAFC"   # alternate table row


def _fmt_inr(value) -> str:
    """Format a numeric value as ₹ with commas."""
    if value is None:
        return "—"
    try:
        v = float(value)
        return f"₹{v:,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _stat_box(label: str, value: str) -> str:
    return f"""
      <td style="width:25%;padding:0 6px;">
        <div style="background:{_STAT_BG};border-radius:6px;padding:14px 16px;text-align:center;">
          <div style="font-size:22px;font-weight:700;color:{_NAVY};letter-spacing:-0.5px;">{value}</div>
          <div style="font-size:11px;color:{_TEXT_MUTED};margin-top:4px;text-transform:uppercase;letter-spacing:.6px;">{label}</div>
        </div>
      </td>"""


def stat_row(stats: list[tuple[str, str]]) -> str:
    """stats = [(label, value), ...]  — up to 4 boxes per row."""
    cells = "".join(_stat_box(l, v) for l, v in stats)
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;">
      <tr>{cells}</tr>
    </table>"""


def section_header(title: str) -> str:
    return f"""
    <h3 style="margin:28px 0 10px;font-size:13px;font-weight:700;color:{_STEEL};
               text-transform:uppercase;letter-spacing:.8px;border-bottom:2px solid {_STEEL};
               padding-bottom:6px;">{title}</h3>"""


def project_block_open(project_code: str, project_name: str, client_name: str = "") -> str:
    subtitle = f" &nbsp;·&nbsp; {client_name}" if client_name else ""
    return f"""
    <div style="border-left:4px solid {_STEEL};padding-left:14px;margin:22px 0 10px;">
      <span style="font-size:13px;font-weight:700;color:{_NAVY};">{project_code}</span>
      <span style="font-size:13px;color:{_TEXT_MAIN};"> — {project_name}</span>
      <span style="font-size:11px;color:{_TEXT_MUTED};">{subtitle}</span>
    </div>"""


def project_block_close() -> str:
    return ""  # no HTML needed; just a logical separator


def table(headers: list[str], rows: list[list], amount_cols: set[int] | None = None) -> str:
    """Render a clean data table.

    amount_cols: column indices whose values should be right-aligned and formatted as INR.
    """
    if amount_cols is None:
        amount_cols = set()

    th_cells = "".join(
        f'<th style="text-align:{"right" if i in amount_cols else "left"};'
        f'padding:8px 12px;font-size:11px;font-weight:700;color:{_TEXT_MUTED};'
        f'text-transform:uppercase;letter-spacing:.5px;border-bottom:2px solid {_BORDER};">{h}</th>'
        for i, h in enumerate(headers)
    )
    thead = f"<thead><tr>{th_cells}</tr></thead>"

    tbody_rows = []
    for idx, row in enumerate(rows):
        bg = _STRIPE if idx % 2 else _CARD_BG
        td_cells = "".join(
            f'<td style="text-align:{"right" if i in amount_cols else "left"};'
            f'padding:8px 12px;font-size:12px;color:{_TEXT_MAIN};'
            f'border-bottom:1px solid {_BORDER};">'
            f'{_fmt_inr(v) if i in amount_cols else (v or "—")}</td>'
            for i, v in enumerate(row)
        )
        tbody_rows.append(f'<tr style="background:{bg};">{td_cells}</tr>')

    tbody = f"<tbody>{''.join(tbody_rows) or _empty_row(len(headers))}</tbody>"

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;border:1px solid {_BORDER};border-radius:6px;
                  overflow:hidden;margin-bottom:20px;font-size:12px;">
      {thead}{tbody}
    </table>"""


def _empty_row(col_count: int) -> str:
    return (
        f'<tr><td colspan="{col_count}" style="padding:14px 12px;text-align:center;'
        f'color:{_TEXT_MUTED};font-style:italic;">No records this period</td></tr>'
    )


def no_data_note(msg: str = "No activity recorded this period.") -> str:
    return (
        f'<p style="color:{_TEXT_MUTED};font-style:italic;font-size:12px;'
        f'margin:6px 0 20px;">{msg}</p>'
    )


# ── Full email wrapper ────────────────────────────────────────────────────────

def build_email(
    module_name: str,
    period_label: str,
    generated_at: datetime,
    body_html: str,
) -> str:
    gen = generated_at.strftime("%d %b %Y, %I:%M %p IST")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ERP Monthly Report — {module_name}</title>
</head>
<body style="margin:0;padding:0;background:{_BODY_BG};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">

  <!-- Outer wrapper -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:32px 16px;">

        <!-- Card -->
        <table role="presentation" width="700" cellpadding="0" cellspacing="0"
               style="max-width:700px;width:100%;background:{_CARD_BG};
                      border-radius:10px;overflow:hidden;
                      box-shadow:0 2px 8px rgba(0,0,0,.10);">

          <!-- ── Header ── -->
          <tr>
            <td style="background:{_NAVY};padding:28px 32px;">
              <div style="font-size:11px;color:rgba(255,255,255,.55);
                          text-transform:uppercase;letter-spacing:1.2px;">
                ERP Monthly Report
              </div>
              <div style="font-size:24px;font-weight:700;color:#FFFFFF;margin-top:4px;">
                {module_name}
              </div>
              <div style="font-size:13px;color:rgba(255,255,255,.7);margin-top:6px;">
                Period: <strong style="color:#FFFFFF;">{period_label}</strong>
              </div>
            </td>
          </tr>

          <!-- ── Body ── -->
          <tr>
            <td style="padding:28px 32px;">
              {body_html}
            </td>
          </tr>

          <!-- ── Footer ── -->
          <tr>
            <td style="background:{_STRIPE};border-top:1px solid {_BORDER};
                        padding:16px 32px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="font-size:11px;color:{_TEXT_MUTED};">
                    Generated: {gen}
                  </td>
                  <td align="right" style="font-size:11px;color:{_TEXT_MUTED};">
                    ERP System &nbsp;·&nbsp; dishaanhitechit@gmail.com
                  </td>
                </tr>
              </table>
            </td>
          </tr>

        </table><!-- /Card -->

      </td>
    </tr>
  </table><!-- /Outer -->

</body>
</html>"""
