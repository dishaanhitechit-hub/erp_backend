"""
grn_pdf_rl_service.py
=====================
Pixel-perfect GRN (Goods Receipt Note) PDF using ReportLab direct PDF generation.
No intermediate DOCX / LibreOffice / COM required — works on all platforms.

Template reference: GRN.docx
Specs extracted from document.xml (sectPr, tblGrid, anchor positions).

Page geometry (from sectPr in GRN.docx):
  Paper  : A4  595.5 × 842 pt  (11910 × 16840 twips)
  Margins: top=49  bottom=14  left=35.45  right=21.4  header_dist=36  (pt)
  Border : single black line on all 4 sides, offset from page, space=25

6-column table widths (from tblGrid, twips → pt, factor 0.05):
  [33.75, 49.65, 205.5, 49.65, 56.70, 127.55]
  Cols   : SL No | Item Code | Item Name | Unit | Qty | Store Location

Colors (from shd fill values in GRN.docx):
  D9D9D9 — table header row (gray)
  B6DDE8 — last/total row (light blue, accent5 tint 66%)

Header layout (derived from anchor positions in document.xml):
  Left   : Company logo/banner (109 pt wide, 45 pt tall)
  Center : "(India) Private Limited"  +  "GOODS RECEIPT NOTE [GRN]"
  Right  : QR code + "www.dishaanhitech.com"

Footer microprint (every page):
  "Generated: {datetime}  |  Fingerprint: {sha256[:16]}  |
   {company_name}  |  www.dishaanhitech.com"
  Font: 4pt Helvetica, centered
"""

import io
import os
import hashlib
import textwrap
from datetime import datetime

# ── ReportLab core ────────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    PageTemplate,
    Frame,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    KeepTogether,
    Image as RLImage,
)

# ── QR / image ────────────────────────────────────────────────────────────────
import qrcode
from qrcode.image.pil import PilImage as _QRPil
from PIL import Image as _PILImg, ImageDraw as _PILDraw

# ── Token signing ──────────────────────────────────────────────────────────────
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

# ── Flask / app ───────────────────────────────────────────────────────────────
from flask import current_app, make_response, send_from_directory

from app.extensions import db
from app.models.grnMaster import GrnMaster
from app.models.companies import Company
from app.models.approval_path import ApprovalHistory
from app.models.user import User
from app.response import res


# ══════════════════════════════════════════════════════════════════════════════
# PAGE GEOMETRY  (all values in points, 1 pt = 1/72 inch)
# Conversion from twips: 1 twip = 1/1440 inch = 72/1440 pt = 0.05 pt
# ══════════════════════════════════════════════════════════════════════════════

_T = 0.05                  # twips → points factor

PG_W  = 595.5              # A4 width  (11910 twips)
PG_H  = 842.0              # A4 height (16840 twips)
MG_L  = 709  * _T          # 35.45 pt  left   margin
MG_R  = 428  * _T          # 21.40 pt  right  margin
MG_B  = 280  * _T          # 14.00 pt  bottom margin
MG_HD = 720  * _T          # 36.00 pt  header distance from page top

# Top margin is set larger than the docx value (49 pt) to accommodate
# the drawn header (logo + titles + separator) which occupies ~140 pt.
MG_T  = 145.0              # pt — body text starts here from page top

CONTENT_W = PG_W - MG_L - MG_R    # 538.65 pt  usable line width


# ══════════════════════════════════════════════════════════════════════════════
# 6-COLUMN WIDTHS  (from tblGrid in GRN.docx)
# tblW = 10456 twips total
# ══════════════════════════════════════════════════════════════════════════════

_COL_TW = [675, 993, 4110, 993, 1134, 2551]
COL_W   = [c * _T for c in _COL_TW]
# = [33.75, 49.65, 205.5, 49.65, 56.70, 127.55]
TABLE_W = sum(COL_W)                # 522.80 pt

# Row heights (twips → pt)
RH_HDR  = 340 * _T                  # 17.00 pt  header row minimum
RH_DATA = 16.0                      # default data-row min height


# ══════════════════════════════════════════════════════════════════════════════
# COLORS  (hex values from shd fill in GRN.docx)
# ══════════════════════════════════════════════════════════════════════════════

C_GRAY_HD  = HexColor("#D9D9D9")    # table header row (light gray)
C_BLUE_TOT = HexColor("#B6DDE8")    # last/total row (light blue)
C_BLACK    = colors.black
C_WHITE    = colors.white


# ══════════════════════════════════════════════════════════════════════════════
# FONTS  (built-in PDF fonts — no install needed)
# ══════════════════════════════════════════════════════════════════════════════

F   = "Helvetica"
FB  = "Helvetica-Bold"
FI  = "Helvetica-Oblique"
FBI = "Helvetica-BoldOblique"


# ══════════════════════════════════════════════════════════════════════════════
# PARAGRAPH STYLES
# ══════════════════════════════════════════════════════════════════════════════

def _ps(name, size=8, bold=False, italic=False, align=TA_LEFT,
        color=None, leading=None, sp_before=0, sp_after=0,
        left_indent=0, first_indent=0):
    fn = FBI if bold and italic else FB if bold else FI if italic else F
    return ParagraphStyle(
        name,
        fontName=fn,
        fontSize=size,
        leading=leading if leading is not None else round(size * 1.25, 2),
        alignment=align,
        textColor=color or C_BLACK,
        spaceBefore=sp_before,
        spaceAfter=sp_after,
        leftIndent=left_indent,
        firstLineIndent=first_indent,
    )


ST_BODY    = _ps("grn_body")
ST_BODY_C  = _ps("grn_body_c",  align=TA_CENTER)
ST_BODY_R  = _ps("grn_body_r",  align=TA_RIGHT)
ST_BOLD    = _ps("grn_bold",    bold=True)
ST_BOLD_C  = _ps("grn_bold_c",  bold=True, align=TA_CENTER)
ST_LBL     = _ps("grn_lbl",     size=8,  bold=True,   leading=11)
ST_VAL     = _ps("grn_val",     size=8,  bold=False,  leading=11)
ST_LBL_C   = _ps("grn_lbl_c",  size=8,  bold=True,   align=TA_CENTER, leading=11)
ST_APPR    = _ps("grn_appr",    size=8,  leading=11, sp_before=1, sp_after=1)


# ══════════════════════════════════════════════════════════════════════════════
# TOKEN / STORAGE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

PDF_TOKEN_SALT  = "grn-pdf-v1"
PDF_EXPIRY_DAYS = 2

LOGO_PATH = os.getenv(
    "COMPANY_LOGO_PATH",
    os.path.join(os.getcwd(), "asset", "order", "1000018063.jpeg"),
)


def _storage_root():
    return current_app.config.get(
        "PDF_STORAGE_PATH",
        os.path.join(os.getcwd(), "storage", "pdf"),
    )


def _save_pdf(pdf_bytes, grn_no):
    import time
    root   = _storage_root()
    folder = os.path.join(root, "grn_pdf", grn_no)
    os.makedirs(folder, exist_ok=True)
    fname  = f"grn_{int(time.time())}.pdf"
    with open(os.path.join(folder, fname), "wb") as fh:
        fh.write(pdf_bytes)
    base = current_app.config.get("PDF_BASE_URL", "/resource/order/pdf-file")
    return f"{base}/grn_pdf/{grn_no}/{fname}"


def serve_grn_pdf_file(relative_path):
    root     = _storage_root()
    full_dir = os.path.join(root, os.path.dirname(relative_path))
    resp = send_from_directory(
        full_dir, os.path.basename(relative_path), mimetype="application/pdf"
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"]        = "no-cache"
    resp.headers["Expires"]       = "0"
    return resp


def _serializer():
    secret = current_app.config.get("JWT_SECRET_KEY", "erp-secret")
    return URLSafeTimedSerializer(secret)


def _fingerprint(grn):
    raw = f"{grn.grn_no}|{grn.id}|{str(grn.grn_date or '')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()


# ══════════════════════════════════════════════════════════════════════════════
# QR CODE WITH L-BRACKET CORNER MARKS
# ══════════════════════════════════════════════════════════════════════════════

def _qr_with_brackets(url):
    qr = qrcode.QRCode(
        box_size=10, border=4,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(image_factory=_QRPil,
                  fill_color="black", back_color="white").save(buf, "PNG")
    buf.seek(0)

    img  = _PILImg.open(buf).convert("RGB")
    draw = _PILDraw.Draw(img)
    iw, ih = img.size
    t = max(5, iw // 45)
    L = iw // 5
    for x0, y0, x1, y1 in [
        (0,    0,    L,    t), (0,    0,    t,    L),
        (iw-L, 0,    iw,   t), (iw-t, 0,    iw,   L),
        (0,    ih-t, L,    ih), (0,    ih-L, t,    ih),
        (iw-L, ih-t, iw,   ih), (iw-t, ih-L, iw,   ih),
    ]:
        draw.rectangle([x0, y0, x1 - 1, y1 - 1], fill="black")

    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE CANVAS DRAWING  (header + border + footer — repeated on EVERY page)
# ══════════════════════════════════════════════════════════════════════════════

def _draw_page(canvas, doc):
    s = doc._pdf_state
    canvas.saveState()
    _draw_border(canvas)
    _draw_header(canvas, s)
    _draw_footer(canvas, s)
    canvas.restoreState()


def _draw_border(c):
    """Draw single black page border matching GRN.docx pgBorders (space=25 twips from page edge)."""
    pad = 25 * _T                  # 1.25 pt inset from page edge
    c.setStrokeColor(C_BLACK)
    c.setLineWidth(0.5)            # sz=4 in docx → 0.5 pt
    c.rect(pad, pad, PG_W - 2 * pad, PG_H - 2 * pad, stroke=1, fill=0)


def _draw_header(c, s):
    """
    Draw the letterhead header on every page.

    Positions derived from anchor offsets in GRN.docx document.xml:

    Logo   : posH from page = 450272 EMU → 35.45 pt (= MG_L)
              posV from para = 5080 EMU  → ~0.4 pt (≈ page top + MG_HD)
              size: 1392072 × 572713 EMU → 109.6 × 45.1 pt

    QR     : posH from margin = 5419725 EMU → MG_L + 426.7 pt = 462.2 pt
              posV from margin = 289560 EMU → MG_HD + 22.8 pt = 58.8 pt from top
              size: 859155 × 859155 EMU → 67.6 × 67.6 pt

    Website: textbox top-right, right-aligned, sz=20 (10pt), Bahnschrift Light
              drawn near logo level, right-justified in QR column area

    Titles : "(India) Private Limited" — sz=28 (14pt), Title style
             "GOODS RECEIPT NOTE"      — sz=32 (16pt), bold, centered
             "[GRN]"                   — sz=32 (16pt), bold, centered
    """
    # ── geometry ───────────────────────────────────────────────────────────────
    x0    = MG_L                           # 35.45 pt  left content edge
    x_end = PG_W - MG_R                    # 574.1  pt  right content edge
    y_body = PG_H - MG_T                   # canvas y of body top (= 697 pt)

    # Logo dimensions (from EMU sizes)
    logo_h = 45.1                          # pt
    logo_w = 109.6                         # pt
    # Logo top edge: page top canvas − (header_dist + ~0.4) ≈ PG_H − MG_HD
    logo_top_canvas = PG_H - MG_HD        # 806 pt in canvas coords
    logo_bot_canvas = logo_top_canvas - logo_h   # 760.9 pt

    # QR dimensions and position (from EMU offsets converted to pt)
    qr_size = 67.6                         # pt (859155 EMU)
    qr_x    = MG_L + 426.7                 # 462.2 pt from left page edge
    # posV from margin = 58.8 pt from top of page content area
    qr_top_canvas  = PG_H - MG_HD - 22.8  # canvas y of QR top edge (783.2)
    qr_bot_canvas  = qr_top_canvas - qr_size   # 715.6 pt

    # ── LEFT: Logo ─────────────────────────────────────────────────────────────
    if os.path.exists(s["logo_path"]):
        try:
            c.drawImage(
                ImageReader(s["logo_path"]),
                x0, logo_bot_canvas,
                width=logo_w, height=logo_h,
                preserveAspectRatio=True, anchor="nw",
                mask="auto",
            )
        except Exception:
            pass

    # ── RIGHT: QR code ─────────────────────────────────────────────────────────
    qr_bytes = s.get("qr_bytes")
    if qr_bytes:
        try:
            c.drawImage(
                ImageReader(io.BytesIO(qr_bytes)),
                qr_x, qr_bot_canvas,
                width=qr_size, height=qr_size,
                preserveAspectRatio=True, anchor="nw",
                mask="auto",
            )
        except Exception:
            pass

    # ── RIGHT: "www.dishaanhitech.com" (website textbox, top-right) ────────────
    # posH from column: 4837411 EMU → 380.8 pt from column start = MG_L + 380.8
    # right-aligned within 143.75 pt wide textbox, sz=20 (10pt)
    c.setFont(F, 8)
    c.setFillColor(C_BLACK)
    c.drawRightString(x_end - 2, logo_top_canvas - 12, "www.dishaanhitech.com")

    # ── CENTER: "(India) Private Limited" (Title style, sz=28 → 14pt) ──────────
    # In docx: paragraph 3 (after logo para + QR para), Title style, ind left=0
    # Vertically positioned just below the logo
    cx = (x0 + x_end) / 2             # center x of content area
    c.setFont(F, 10)
    c.drawCentredString(cx, logo_bot_canvas - 12, "(India) Private Limited")

    # ── CENTER: "GOODS RECEIPT NOTE" (Aptos, sz=32 → 16pt, bold) ───────────────
    # In docx: indent left=1843 twips (92.15 pt), centered → effective cx ≈ 354 pt
    # We use content center for simplicity (small visual difference)
    c.setFont(FB, 14)
    c.drawCentredString(cx, logo_bot_canvas - 28, "GOODS RECEIPT NOTE")

    # ── CENTER: "[GRN]" (same style as above) ──────────────────────────────────
    c.setFont(FB, 14)
    c.drawCentredString(cx, logo_bot_canvas - 44, "[GRN]")

    # ── Separator line (marks bottom of header / top of body) ──────────────────
    c.setStrokeColor(C_BLACK)
    c.setLineWidth(0.5)
    c.line(x0, y_body, x_end, y_body)


def _draw_footer(c, s):
    """Microprint footer on every page — 4pt Helvetica, centered."""
    cx = (MG_L + PG_W - MG_R) / 2
    y  = MG_B - 8

    text = (
        f"Generated: {s['generated_at']}   │   "
        f"Fingerprint: {s['fp']}   │   "
        f"Dishaan Hi-Tech (India) Pvt. Ltd.   │   "
        f"www.dishaanhitech.com"
    )
    c.setFont(F, 4)
    c.setFillColor(C_BLACK)
    c.drawCentredString(cx, y, text)


# ══════════════════════════════════════════════════════════════════════════════
# INFO TABLE  (label–value pairs in 2-column layout)
# Mirrors the tab-aligned fields in GRN.docx (lines 7–14 of body).
# ══════════════════════════════════════════════════════════════════════════════

def _build_info_table(grn, company):
    """
    Return a borderless 2-column table replicating the info field layout.

    Left column  : Site Code, Project Name, Customer Name, Party Name,
                   Party Bill No, Party Bill Date, Delivery Vehicle,
                   Delivery Concern
    Right column : GRN No, GRN Date, Unloading Date, PO No,
                   Challan No, Challan Date, Shipping Address

    Each cell is an inner 2-column label/value table (bold label + plain value).
    """
    project  = grn.project
    vendor   = grn.vendor
    order    = grn.order

    def _fmt_date(d):
        if d is None:
            return ""
        if hasattr(d, "strftime"):
            return d.strftime("%d-%b-%Y")
        return str(d)

    def _fmt_dt(dt):
        if dt is None:
            return ""
        if hasattr(dt, "strftime"):
            return dt.strftime("%d-%b-%Y")
        return str(dt)

    # Left-side field definitions: (label, value)
    left_fields = [
        ("Site Code",        grn.project_code or ""),
        ("Project Name",     (project.project_name if project else "") or ""),
        ("Customer Name",    (project.client_name  if project else "") or ""),
        ("Party Name",       (vendor.ledger_name   if vendor  else "") or ""),
        ("Party Bill No",    grn.party_bill_no  or ""),
        ("Party Bill Date",  _fmt_date(grn.party_bill_date)),
        ("Delivery Vehicle", grn.deliver_vehicle_no or ""),
        ("Delivery Concern", grn.delivered_concern  or ""),
    ]

    # Right-side field definitions: (label, value)
    right_fields = [
        ("GRN No",           grn.grn_no   or ""),
        ("GRN Date",         _fmt_date(grn.grn_date)),
        ("Unloading Date",   _fmt_dt(grn.unloading_datetime)),
        ("PO No",            (order.order_no if order else "") or ""),
        ("Challan No",       grn.challan_no or ""),
        ("Challan Date",     ""),           # no challan_date field in model
        ("Shipping Address", grn.shipping_address or ""),
        ("",                 ""),           # padding to match left column count
    ]

    # Build each info row as: [left_label, left_val, right_label, right_val]
    # Column widths: left_lbl=88, left_val=180, right_lbl=88, right_val=182
    # Total = 538 pt ≈ CONTENT_W
    LBL_W  = 90.0
    VAL_L  = 178.0
    VAL_R  = 175.0
    GAP    = CONTENT_W - LBL_W - VAL_L - LBL_W - VAL_R   # ~3.65 pt spacing

    col_widths = [LBL_W, VAL_L, LBL_W, VAL_R]

    rows = []
    for (l_lbl, l_val), (r_lbl, r_val) in zip(left_fields, right_fields):
        def _cell(label, value):
            if not label:
                return Paragraph("", ST_BODY)
            txt = f"<b>{label}</b> : {value}"
            return Paragraph(txt, ST_BODY)

        rows.append([
            _cell(l_lbl, l_val),
            "",
            _cell(r_lbl, r_val),
            "",
        ])

    # Use a single-col approach: each row is [left_para, right_para]
    # Rebuild with 2 columns instead of 4 to simplify
    rows2 = []
    for (l_lbl, l_val), (r_lbl, r_val) in zip(left_fields, right_fields):
        def _para(label, value):
            if not label:
                return Paragraph("", ST_BODY)
            return Paragraph(f"<b>{label}</b> : {value}", ST_BODY)

        rows2.append([_para(l_lbl, l_val), _para(r_lbl, r_val)])

    half = CONTENT_W / 2
    tbl = Table(rows2, colWidths=[half, half])
    tbl.setStyle(TableStyle([
        ("FONTNAME",       (0, 0), (-1, -1), F),
        ("FONTSIZE",       (0, 0), (-1, -1), 8),
        ("LEADING",        (0, 0), (-1, -1), 11),
        ("TOPPADDING",     (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 1),
        ("LEFTPADDING",    (0, 0), (-1, -1), 2),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 2),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW",      (0, -1), (-1, -1), 0.25, C_BLACK),
    ]))
    return tbl


# ══════════════════════════════════════════════════════════════════════════════
# ITEMS TABLE  (header row + dynamic data rows + blue total row)
# ══════════════════════════════════════════════════════════════════════════════

def _build_items_table(items):
    """
    Return a 6-column Table:
      Row 0      : column header row (D9D9D9, repeats on page break)
      Rows 1..N  : item data rows (dynamic)
      Row N+1    : empty/total row (B6DDE8 light blue, matching docx last row)

    Columns: SL No | Item Code | Item Name | Unit | Qty | Store Location
    """
    # ── Row 0: column header ───────────────────────────────────────────────────
    HDR_LABELS = ["SL No", "Item Code", "Item Name", "Unit", "Qty", "Store Location"]
    rows = [[Paragraph(lbl, ST_BOLD_C) for lbl in HDR_LABELS]]

    # ── Data rows ─────────────────────────────────────────────────────────────
    n_items = max(len(items), 1)    # at least 1 row so table renders

    for ri in range(n_items):
        if ri < len(items):
            it = items[ri]
            rows.append([
                Paragraph(str(it.get("sl", "")),        ST_BODY_C),
                Paragraph(it.get("item_code", "") or "", ST_BODY_C),
                Paragraph(it.get("item_name", "") or "", ST_BODY),
                Paragraph(it.get("unit", "")      or "", ST_BODY_C),
                Paragraph(f"{it.get('qty', 0):.2f}",    ST_BODY_C),
                Paragraph(it.get("store_location", "") or "", ST_BODY),
            ])
        else:
            rows.append([""] * 6)

    # ── Blue last row (matching B6DDE8 row in docx — acts as a visual footer) ──
    rows.append([""] * 6)

    n_data  = n_items
    r_blue  = 1 + n_data     # index of the blue row

    # ── TableStyle ─────────────────────────────────────────────────────────────
    style = TableStyle([
        # Global defaults
        ("FONTNAME",       (0, 0), (-1, -1), F),
        ("FONTSIZE",       (0, 0), (-1, -1), 8),
        ("LEADING",        (0, 0), (-1, -1), 10),
        ("TOPPADDING",     (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 2),
        ("LEFTPADDING",    (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 3),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",           (0, 0), (-1, -1), 0.5, C_BLACK),

        # Header row
        ("BACKGROUND",     (0, 0), (-1, 0),  C_GRAY_HD),
        ("FONTNAME",       (0, 0), (-1, 0),  FB),
        ("ALIGN",          (0, 0), (-1, 0),  "CENTER"),
        ("MINROWHEIGHT",   (0, 0), (0, 0),   RH_HDR),

        # Data row alignment
        ("ALIGN",          (0, 1), (0, r_blue - 1), "CENTER"),   # SL No
        ("ALIGN",          (1, 1), (1, r_blue - 1), "CENTER"),   # Item Code
        ("ALIGN",          (3, 1), (3, r_blue - 1), "CENTER"),   # Unit
        ("ALIGN",          (4, 1), (4, r_blue - 1), "CENTER"),   # Qty

        # Blue last row
        ("BACKGROUND",     (0, r_blue), (-1, r_blue), C_BLUE_TOT),
        ("MINROWHEIGHT",   (0, r_blue), (-1, r_blue), RH_HDR),
    ])

    tbl = Table(rows, colWidths=COL_W, repeatRows=1)
    tbl.setStyle(style)
    return tbl


# ══════════════════════════════════════════════════════════════════════════════
# APPROVAL / SIGNATURE SECTION  (Physically Received / Verified / Doc Verified)
# ══════════════════════════════════════════════════════════════════════════════

def _build_approval_section(received_by, verified_by, doc_verified_by):
    """
    Return a list of Paragraph flowables for the approval lines below the table.

    Mirrors the GRN.docx lines:
      Physically Received By  : [name] [datetime]
      Physically Verified By  : [name] [datetime]
      Document Verified By    : [name] [datetime]

    Each argument is a dict with keys 'name' and 'at', or None.
    """
    def _line(label, person):
        name = person["name"] if person else ""
        at   = person["at"]   if person else ""
        txt  = f"<b>{label}</b> : {name}"
        if at:
            txt += f"  [{at}]"
        return Paragraph(txt, ST_APPR)

    return [
        _line("Physically Received By ", received_by),
        _line("Physically Verified By ", verified_by),
        _line("Document Verified By   ", doc_verified_by),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_pdf(grn, company, items, received_by, verified_by, doc_verified_by,
               qr_bytes, fp, generated_at):
    """
    Build and return the complete GRN PDF as bytes using ReportLab Platypus.

    Structure:
      - BaseDocTemplate with one PageTemplate
      - PageTemplate.onPage = _draw_page (page border + header + footer)
      - Frame = body content area (between header and bottom margin)
      - Story:
          1. Info table   (label-value fields)
          2. Spacer
          3. Items table  (header row repeats on page break)
          4. Spacer
          5. Approval lines (Received / Verified / Document Verified)
    """
    buf = io.BytesIO()

    doc = BaseDocTemplate(
        buf,
        pagesize=(PG_W, PG_H),
        leftMargin=MG_L,
        rightMargin=MG_R,
        topMargin=MG_T,
        bottomMargin=MG_B,
        title=f"GRN — {grn.grn_no or ''}",
        author="Dishaan Hi-Tech (India) Pvt. Ltd.",
    )

    frame = Frame(
        MG_L,
        MG_B,
        CONTENT_W,
        PG_H - MG_T - MG_B,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )

    pt = PageTemplate(id="grn_main", frames=[frame], onPage=_draw_page)
    doc.addPageTemplates([pt])

    doc._pdf_state = {
        "company":      company,
        "qr_bytes":     qr_bytes,
        "fp":           fp,
        "generated_at": generated_at,
        "logo_path":    LOGO_PATH,
    }

    story = []

    # 1. Info table
    info_tbl = _build_info_table(grn, company)
    story.append(KeepTogether(info_tbl))

    story.append(Spacer(1, 4))

    # 2. Items table (items header repeats on page break)
    items_tbl = _build_items_table(items)
    story.append(items_tbl)

    story.append(Spacer(1, 6))

    # 3. Approval lines
    for para in _build_approval_section(received_by, verified_by, doc_verified_by):
        story.append(para)

    doc.build(story)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def generate_grn_pdf(grn_id, base_url, force=False):
    """
    Generate (or serve cached) GRN PDF.

    ?force=1  →  delete existing cached PDF and regenerate fresh.
    """
    try:
        grn = GrnMaster.query.get(grn_id)
        if not grn:
            return res("GRN not found", [], 404)

        # ── Force: remove old cached file and clear DB fields ─────────────────
        if force:
            if getattr(grn, "pdf_url", None):
                try:
                    base_prefix = current_app.config.get(
                        "PDF_BASE_URL", "/resource/order/pdf-file"
                    )
                    relative = grn.pdf_url.replace(base_prefix + "/", "", 1)
                    old_path = os.path.join(_storage_root(), relative)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except Exception:
                    pass
            grn.pdf_url = grn.pdf_token = grn.pdf_generated_at = None

        # ── Return cached PDF if still valid and file exists on disk ──────────
        if (
            not force
            and getattr(grn, "pdf_url",          None)
            and getattr(grn, "pdf_generated_at", None)
        ):
            age = (datetime.utcnow() - grn.pdf_generated_at).days
            if age < PDF_EXPIRY_DAYS:
                base_prefix = current_app.config.get(
                    "PDF_BASE_URL", "/resource/order/pdf-file"
                )
                relative  = grn.pdf_url.replace(base_prefix + "/", "", 1)
                full_path = os.path.join(_storage_root(), relative)
                if os.path.exists(full_path):
                    return serve_grn_pdf_file(relative)
                grn.pdf_url = grn.pdf_token = grn.pdf_generated_at = None

        # ── Gather data ────────────────────────────────────────────────────────
        company = Company.query.first()
        fp      = _fingerprint(grn)
        token   = _serializer().dumps(
            {"gid": grn.id, "gno": grn.grn_no, "fp": fp},
            salt=PDF_TOKEN_SALT,
        )
        verify_url   = f"{base_url.rstrip('/')}/resource/grn/verify/{token}"
        qr_bytes     = _qr_with_brackets(verify_url)
        generated_at = datetime.utcnow().strftime("%d-%b-%Y %H:%M UTC")

        # Items list
        items = []
        for i, gi in enumerate(grn.items, 1):
            item_name = ""
            item_code = gi.item_code or ""
            if gi.item:
                item_name = getattr(gi.item, "item_name", "") or ""
            items.append({
                "sl":             i,
                "item_code":      item_code,
                "item_name":      item_name,
                "unit":           gi.unit or "",
                "qty":            float(gi.current_received_qty or 0),
                "store_location": gi.store_location or "",
            })

        # Approval history: SUBMIT → Received, APPROVE → Verified, FINAL_APPROVE → Doc Verified
        history = (
            db.session.query(ApprovalHistory, User.username)
            .outerjoin(User, User.id == ApprovalHistory.action_by)
            .filter(
                ApprovalHistory.module_code == "goods_received_note",
                ApprovalHistory.record_id   == grn.id,
            )
            .order_by(ApprovalHistory.id.asc())
            .all()
        )

        received_by    = None
        verified_by    = None
        doc_verified_by = None

        for h, username in history:
            name = username or "—"
            at   = (h.created_at.strftime("%d-%b-%Y; %H:%M")
                    if h.created_at else "")
            record = {"name": name, "at": at}
            if   h.action == "SUBMIT":         received_by     = record
            elif h.action == "APPROVE":        verified_by     = record
            elif h.action == "FINAL_APPROVE":  doc_verified_by = record

        # Fallback: use model fields if approval history missing
        if received_by is None and grn.submitter:
            name = (getattr(grn.submitter, "username", None)
                    or getattr(grn.submitter, "name",     None) or "—")
            at   = (grn.submitted_at.strftime("%d-%b-%Y; %H:%M")
                    if grn.submitted_at else "")
            received_by = {"name": name, "at": at}

        if verified_by is None and grn.physically_verified_by:
            verified_by = {"name": grn.physically_verified_by, "at": ""}

        # ── Generate PDF ───────────────────────────────────────────────────────
        pdf_bytes = _build_pdf(
            grn, company, items,
            received_by, verified_by, doc_verified_by,
            qr_bytes, fp, generated_at,
        )

        # ── Persist metadata ───────────────────────────────────────────────────
        pdf_url = _save_pdf(pdf_bytes, grn.grn_no)
        grn.pdf_url          = pdf_url
        grn.pdf_token        = token
        grn.pdf_generated_at = datetime.utcnow()
        db.session.commit()

        response = make_response(pdf_bytes)
        response.headers["Content-Type"]        = "application/pdf"
        response.headers["Content-Disposition"] = (
            f'inline; filename="{grn.grn_no}.pdf"'
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"]        = "no-cache"
        response.headers["Expires"]       = "0"
        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════════════════
# QR VERIFICATION  (public endpoint, scanned by recipient)
# ══════════════════════════════════════════════════════════════════════════════

def verify_grn_pdf(token):
    try:
        data = _serializer().loads(token, salt=PDF_TOKEN_SALT,
                                   max_age=PDF_EXPIRY_DAYS * 86400)
        grn = GrnMaster.query.get(data["gid"])
        if not grn or grn.pdf_token != token:
            return _vpage("invalid")
        if data.get("fp") != _fingerprint(grn):
            return _vpage("tampered", grn)
        base_prefix = current_app.config.get("PDF_BASE_URL", "/resource/order/pdf-file")
        relative    = grn.pdf_url.replace(base_prefix + "/", "", 1)
        return serve_grn_pdf_file(relative)
    except SignatureExpired as e:
        try:
            payload = e.payload
            if payload:
                grn = GrnMaster.query.get(payload.get("gid"))
                if grn and grn.pdf_token == token:
                    grn.pdf_url = grn.pdf_token = grn.pdf_generated_at = None
                    db.session.commit()
        except Exception:
            pass
        return _vpage("expired")
    except BadSignature:
        return _vpage("invalid")
    except Exception as e:
        return _vpage("error", msg=str(e))


def _vpage(status, grn=None, msg=""):
    cfg = {
        "valid":    ("#2e7d32", "✓ DOCUMENT VERIFIED",
                     (f"GRN <b>{grn.grn_no}</b> is authentic.")
                     if grn else "Verified."),
        "tampered": ("#b71c1c", "⚠ TAMPERED DOCUMENT",
                     "Data does not match the original.<br/>"
                     "<b>Do not accept this document.</b>"),
        "expired":  ("#e65100", "⏱ QR CODE EXPIRED",
                     "This QR is valid for 2 days only.<br/>"
                     "Request a regenerated document."),
        "invalid":  ("#37474f", "✗ INVALID QR",
                     "This QR code is not recognised."),
        "error":    ("#37474f", "Error", msg),
    }
    color, title, body = cfg.get(status, cfg["invalid"])
    code = 200 if status == "valid" else 410 if status == "expired" else 400
    return make_response(
        f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>GRN Verification</title>
<style>
  body{{font-family:Arial,sans-serif;display:flex;justify-content:center;
       align-items:center;min-height:100vh;margin:0;background:#f5f5f5}}
  .card{{background:#fff;border-radius:12px;padding:40px;max-width:480px;
         text-align:center;box-shadow:0 4px 20px rgba(0,0,0,.12)}}
  .icon{{font-size:52px;color:{color}}}
  .title{{font-size:20px;font-weight:bold;color:{color};margin:12px 0}}
  .body{{font-size:14px;color:#555;line-height:1.7}}
</style></head><body>
<div class="card">
  <div class="icon">{title[0]}</div>
  <div class="title">{title}</div>
  <div class="body">{body}</div>
</div></body></html>""",
        code,
    )
