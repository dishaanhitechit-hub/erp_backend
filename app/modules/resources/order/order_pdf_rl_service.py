"""
order_pdf_rl_service.py
=======================
Pixel-perfect Order PDF using ReportLab direct PDF generation.
No intermediate DOCX / LibreOffice / COM required — works on all platforms.

Template reference: app/modules/resources/order/Order.docx
Specs extracted from document.xml and header1.xml.

Page geometry (from sectPr in Order.docx):
  Paper  : US Letter  8.5" × 11"  (612 × 792 pt)
  Margins: top=92.15  bottom=35.45  left=28.35  right=37.90  header_dist=35.40  (pt)

10-column table widths (from tblGrid, twips → pt, factor 0.05):
  [28.10, 146.75, 48.60, 35.75, 45.65, 48.20, 56.75, 29.15, 49.55, 56.75]
  Cols   : SL | ItemDetails | HSN/SAC | Unit | OrderQty | UnitRate |
           BasicAmt | GST% | GSTAmt | TotalAmt

Colors (from shd fill values in Order.docx):
  D9D9D9 — all table header rows (party, items)
  BFBFBF — grand total row
  7F7F7F — sub-description / supplementary text

Header layout (derived from anchor positions in header1.xml + document.xml):
  Left   : Company logo/banner + name + address
  Center : "PURCHASES ORDER" (16pt bold) + website + GSTIN
  Right  : QR code (generated per-order) + compact address

Footer microprint (every page — required feature):
  "Generated: {datetime}  |  Fingerprint: {sha256[:16]}  |
   {company_name}  |  www.dishaanhitech.com"
  Font: 4pt Helvetica, centered, 23pt from page bottom
"""

import io
import os
import hashlib
import textwrap
from datetime import datetime

# ── ReportLab core ────────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import letter
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
    Image as RLImage,    # for embedding QR inside a table cell
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
from app.models.orderMaster import OrderMaster
from app.models.companies import Company
from app.models.approval_path import ApprovalHistory
from app.models.user import User
from app.models.category_group import CategoryMaster   # for dynamic category label
from app.response import res


# ══════════════════════════════════════════════════════════════════════════════
# PAGE GEOMETRY  (all values in points, 1 pt = 1/72 inch)
# Conversion from twips: 1 twip = 1/1440 inch = 72/1440 pt = 0.05 pt
# ══════════════════════════════════════════════════════════════════════════════

_T = 0.05                  # twips → points factor

PG_W  = 612.0              # 8.5 inch   (12240 twips)
PG_H  = 792.0              # 11  inch   (15840 twips)
MG_L  = 567  * _T          # 28.35 pt   left   margin  (from page edge)
MG_R  = 758  * _T          # 37.90 pt   right  margin
MG_T  = 1843 * _T          # 92.15 pt   top    margin  (body text starts here)
MG_B  = 709  * _T          # 35.45 pt   bottom margin
MG_HD = 708  * _T          # 35.40 pt   header distance (page top → header top)

CONTENT_W = PG_W - MG_L - MG_R    # 545.75 pt  usable line width
HDR_H     = MG_T - MG_HD           # 56.75  pt  header band height above body


# ══════════════════════════════════════════════════════════════════════════════
# 10-COLUMN WIDTHS  (from tblGrid in Order.docx)
# ══════════════════════════════════════════════════════════════════════════════

_COL_TW = [562, 2935, 972, 715, 913, 964, 1135, 583, 991, 1135]
COL_W   = [c * _T for c in _COL_TW]
# = [28.10, 146.75, 48.60, 35.75, 45.65, 48.20, 56.75, 29.15, 49.55, 56.75]
TABLE_W = sum(COL_W)                # 545.25 pt

# Merged-span aggregate widths used in specific rows
W_VENDOR  = sum(COL_W[0:2])         # 174.85 pt   party-header left  cell
W_COMP    = sum(COL_W[2:6])         # 178.20 pt   party-header center cell
W_REF     = sum(COL_W[6:10])        # 192.20 pt   party-header right  cell
W_TOT_LBL = sum(COL_W[1:6])         # 244.75 pt   TOTAL label merge (cols 1-5)
W_TAX_L   = sum(COL_W[0:5])         # 203.70 pt   tax-row label
W_TAX_M   = sum(COL_W[5:8])         # 134.15 pt   tax-row middle
W_TAX_R   = sum(COL_W[8:10])        # 106.30 pt   tax-row amount

# Row-height minimums (from trHeight in Order.docx, twips → pt)
RH_PARTY  = 283 * _T                # 14.15 pt
RH_ITEMS  = 340 * _T                # 17.00 pt
RH_TOTAL  = 283 * _T                # 14.15 pt
RH_DATA   = 18.0                    # default data-row min height


# ══════════════════════════════════════════════════════════════════════════════
# COLORS  (hex values from shd fill attributes in Order.docx)
# ══════════════════════════════════════════════════════════════════════════════

C_GRAY_HD  = HexColor("#D9D9D9")    # all table header rows (light gray)
C_GRAY_TOT = HexColor("#BFBFBF")    # grand-total row (medium gray)
C_GRAY_TXT = HexColor("#7F7F7F")    # sub-description supplementary text
C_BLACK    = colors.black
C_WHITE    = colors.white


# ══════════════════════════════════════════════════════════════════════════════
# FONTS  (built-in PDF fonts — no install needed, works on Linux + Windows)
# ══════════════════════════════════════════════════════════════════════════════

F   = "Helvetica"
FB  = "Helvetica-Bold"
FI  = "Helvetica-Oblique"
FBI = "Helvetica-BoldOblique"


# ══════════════════════════════════════════════════════════════════════════════
# PARAGRAPH STYLES
# ══════════════════════════════════════════════════════════════════════════════

def _ps(name, size=9, bold=False, italic=False, align=TA_LEFT,
        color=None, leading=None, sp_before=0, sp_after=0,
        left_indent=0, first_indent=0):
    """Factory: create a named ParagraphStyle."""
    fn = FBI if bold and italic else FB if bold else FI if italic else F
    return ParagraphStyle(
        name,
        fontName=fn,
        fontSize=size,
        leading=leading if leading is not None else round(size * 1.2, 2),
        alignment=align,
        textColor=color or C_BLACK,
        spaceBefore=sp_before,
        spaceAfter=sp_after,
        leftIndent=left_indent,
        firstLineIndent=first_indent,
    )


# Table body (9 pt)
ST_BODY    = _ps("body")
ST_BODY_C  = _ps("body_c",  align=TA_CENTER)
ST_BODY_R  = _ps("body_r",  align=TA_RIGHT)
ST_BOLD    = _ps("bold",    bold=True)
ST_BOLD_C  = _ps("bold_c",  bold=True, align=TA_CENTER)
ST_BOLD_R  = _ps("bold_r",  bold=True, align=TA_RIGHT)
# Supplementary/note text (7 pt, gray)
ST_GRAY    = _ps("gray",    size=7, color=C_GRAY_TXT, leading=8.4)

# Totals / summary (10 pt)
ST_10_R    = _ps("t10r",    size=10, align=TA_RIGHT)
ST_10_BR   = _ps("t10br",   size=10, bold=True, align=TA_RIGHT)
ST_10_BC   = _ps("t10bc",   size=10, bold=True, align=TA_CENTER)
ST_10_BL   = _ps("t10bl",   size=10, bold=True)

# Preamble (9 pt with spacing)
ST_PREAM   = _ps("pream",   leading=11, sp_before=3, sp_after=3)

# Amount in words (10 pt bold italic)
ST_WORDS   = _ps("words",   size=10, bold=True, italic=True)

# Terms & Conditions
ST_TC_HDR  = _ps("tc_hdr",  size=10, bold=True, sp_before=8, sp_after=4)
ST_TC_BODY = _ps("tc_body", size=10, sp_before=0, sp_after=2)
ST_TC_NUM  = _ps("tc_num",  size=10, sp_before=0, sp_after=2,
                 left_indent=14, first_indent=-14)

# Signature
ST_SIG_H   = _ps("sig_h",   bold=True, align=TA_CENTER, sp_before=3,  sp_after=3)
ST_SIG_B   = _ps("sig_b",   align=TA_CENTER,             sp_before=12, sp_after=12)


# ══════════════════════════════════════════════════════════════════════════════
# TOKEN / STORAGE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

PDF_TOKEN_SALT  = "order-pdf-v2"
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


def _save_pdf(pdf_bytes, order_no):
    """
    Write PDF to disk and return its URL path.

    Filename includes a Unix timestamp so each regeneration produces a
    distinct URL — this prevents browser/CDN from serving a stale cached file
    even when force=1 is used.
    Old files in the same folder are cleaned up automatically on the next force.
    """
    root   = _storage_root()
    folder = os.path.join(root, "order_pdf", order_no)
    os.makedirs(folder, exist_ok=True)

    # Unique filename: order_<epoch_seconds>.pdf  →  URL changes on every regeneration
    import time
    fname  = f"order_{int(time.time())}.pdf"
    with open(os.path.join(folder, fname), "wb") as fh:
        fh.write(pdf_bytes)
    base = current_app.config.get("PDF_BASE_URL", "/resource/order/pdf-file")
    return f"{base}/order_pdf/{order_no}/{fname}"


def serve_pdf_file(relative_path):
    root     = _storage_root()
    full_dir = os.path.join(root, os.path.dirname(relative_path))
    resp = send_from_directory(
        full_dir, os.path.basename(relative_path), mimetype="application/pdf"
    )
    # Prevent browser/proxy from caching the served file so force=1 is always fresh
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"]        = "no-cache"
    resp.headers["Expires"]       = "0"
    return resp


def _serializer():
    secret = current_app.config.get("JWT_SECRET_KEY", "erp-secret")
    return URLSafeTimedSerializer(secret)


def _fingerprint(order):
    raw = (f"{order.order_no}|"
           f"{float(order.basic_amount or 0):.2f}|"
           f"{float(order.total_amount or 0):.2f}")
    return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()


# ══════════════════════════════════════════════════════════════════════════════
# QR CODE WITH L-BRACKET CORNER MARKS
# ══════════════════════════════════════════════════════════════════════════════

def _qr_with_brackets(url):
    """Return PNG bytes of a QR code with decorative L-bracket corners."""
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
# PAGE CANVAS DRAWING  (header + microprint footer — repeated on EVERY page)
# ══════════════════════════════════════════════════════════════════════════════

def _draw_page(canvas, doc):
    """
    ReportLab PageTemplate.onPage callback.
    Draws the letterhead header and microprint footer on every page.
    State dict is attached as doc._pdf_state in generate_order_pdf().
    """
    s = doc._pdf_state
    canvas.saveState()
    _draw_header(canvas, s)
    _draw_footer(canvas, s)
    canvas.restoreState()


def _draw_header(c, s):
    """
    Draw the three-column letterhead header using direct canvas API.

    Column layout mirrors the table's merged spans:
      Left   (width W_VENDOR=174.85pt): logo banner + company name + address
      Center (width W_COMP  =178.20pt): PURCHASES ORDER title + website + GSTIN
      Right  (width W_REF   =192.20pt): QR code + compact address

    Vertical positions are derived from the anchor offsets in Order.docx:
      Logo top    : 14.4 pt from page top  → canvas y = PG_H - 14.4 = 777.6
      Title top   : 45.0 pt from page top  → canvas y = PG_H - 45.0 = 747.0
      Body starts : 92.15 pt from page top → canvas y = PG_H - MG_T  = 699.85
    """
    # ── geometry ───────────────────────────────────────────────────────────────
    x0    = MG_L                      # 28.35   left content edge
    x_end = PG_W - MG_R               # 574.10  right content edge

    # Column x starts
    x_ctr = x0 + W_VENDOR             # 203.20  center column start
    x_rgt = x_ctr + W_COMP            # 381.40  right  column start

    y_body = PG_H - MG_T              # 699.85  top of body (bottom of header)
    y_logo = PG_H - 14.4              # 777.60  logo top (from template anchor)

    # ── LEFT: Company logo + name + address ────────────────────────────────────
    logo_h = 45.0
    logo_w = 110.0
    logo_y = y_logo - logo_h           # canvas y of logo bottom edge

    if os.path.exists(s["logo_path"]):
        try:
            c.drawImage(
                ImageReader(s["logo_path"]),
                x0, logo_y,
                width=logo_w, height=logo_h,
                preserveAspectRatio=True, anchor="nw",
                mask="auto",
            )
        except Exception:
            pass

    # Company name (bold, below logo)
    company = s["company"]
    c.setFont(FB, 8)
    c.setFillColor(C_BLACK)
    name_y = logo_y - 10
    c.drawString(x0, name_y, (company.company_name or "")[:40])

    # Address lines (7 pt, compact)
    c.setFont(F, 7)
    addr_raw = company.registered_address or ""
    addr_lines = textwrap.wrap(addr_raw, width=34)[:2]
    ay = name_y - 9
    for line in addr_lines:
        c.drawString(x0, ay, line)
        ay -= 8
    c.drawString(x0, ay, f"Ph: {company.contact_number or ''}")

    # ── CENTER: PURCHASES ORDER title + website + GSTIN ────────────────────────
    # Title at 45 pt from page top (canvas 747), centered in center column
    cx = (x_ctr + x_rgt) / 2          # center x of center column = 292.3 pt

    # "PURCHASES ORDER" (16 pt bold, from template: Aptos Display Bold sz=32)
    c.setFont(FB, 16)
    c.drawCentredString(cx, PG_H - 52, s["category_name"])

    # Website (9 pt bold)
    c.setFont(FB, 9)
    c.drawCentredString(cx, PG_H - 66, "www.dishaanhitech.com")

    # GSTIN (9 pt regular)
    c.setFont(F, 9)
    c.drawCentredString(cx, PG_H - 78, f"GSTIN NO.: {company.gstn or '—'}")

    # ── RIGHT: Compact address only (QR is now inside the Reference table cell) ─
    # Show extra contact lines to fill the header space previously occupied by QR.
    c.setFont(F, 7)
    addr_r_lines = [
        addr_raw[:38],
        f"Email : {(company.email or '')[:34]}",
        f"Ph    : {company.contact_number or ''}",
        f"Web   : www.dishaanhitech.com",
    ]
    ry = y_body + 6 + len(addr_r_lines) * 8 - 8   # start near top of right column
    for line in addr_r_lines:
        c.drawString(x_rgt + 2, ry, line)
        ry -= 8

    # ── Separator line (marks bottom of header / top of body) ─────────────────
    c.setStrokeColor(C_BLACK)
    c.setLineWidth(0.5)
    c.line(x0, y_body, x_end, y_body)


def _draw_footer(c, s):
    """
    Draw the microprint footer on every page.

    Content: Generated date | Fingerprint (SHA-256 first 16 hex chars) |
             Company name | Website
    Font   : 4pt Helvetica — visually a security micro-line
    Position: centered, ~23 pt from bottom of page
    """
    x0    = MG_L
    x_end = PG_W - MG_R
    cx    = (x0 + x_end) / 2
    y     = MG_B - 12                  # 35.45 - 12 = ~23 pt from page bottom

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
# INFORMATION TABLE  (rows 0-2: parties header, parties body, preamble)
# These rows do NOT repeat on page break — kept together with KeepTogether.
# ══════════════════════════════════════════════════════════════════════════════

def _build_info_table(order, vendor, company, qr_bytes=None,
                      creator_name="", category_name=""):
    """
    Return a 10-column Table with 3 rows:
      Row 0 : party-header labels          (D9D9D9, 3 merged cells)
      Row 1 : party content data           (3 merged cells, vertical-top)
               Reference cell contains a nested 2-column mini-table:
                 left  → reference text fields
                 right → QR code image (top-right corner, no border)
      Row 2 : preamble paragraph           (full-width merge)

    Parameters
    ----------
    qr_bytes      : PNG bytes of the per-order QR code, or None to skip
    creator_name  : display name of the user who created the order
    category_name : human-readable order category (e.g. "Purchase Order")
    """
    v = vendor
    c = company

    # ── Row 0: party header labels ─────────────────────────────────────────────
    r0 = [
        Paragraph("Service From (Saler):", ST_BOLD),   # col 0  (spans 0-1)
        "",                                             # col 1  merged
        Paragraph("Service To / Buyer:",   ST_BOLD),   # col 2  (spans 2-5)
        "", "", "",                                     # cols 3-5 merged
        Paragraph("Reference:",            ST_BOLD),   # col 6  (spans 6-9)
        "", "", "",                                     # cols 7-9 merged
    ]

    # ── Row 1: party content ───────────────────────────────────────────────────
    def _lines(*pairs):
        """Build <b>label</b> value lines as a single Paragraph."""
        parts = []
        for label, val in pairs:
            if label:
                parts.append(f"<b>{label}</b> {val or '—'}")
            else:
                parts.append(str(val or ""))
        return Paragraph("<br/>".join(parts), ST_BODY)

    vendor_para = _lines(
        ("", v.ledger_name),
        ("", v.registered_address),
        ("Email:", getattr(v, "email", "")),
        ("Contact:", v.primary_contact_person),
        ("Ph:", v.primary_contact_number),
        ("PAN:", v.pan),
        ("GSTIN:", v.gstin),
        ("State:", f"{v.state_name or '—'}   Code: {v.state_code or '—'}"),
    )
    comp_para = _lines(
        ("", c.company_name),
        ("", c.registered_address),
        ("Email:", c.email),
        ("Contact:", c.contact_person),
        ("Ph:", c.contact_number),
        ("PAN:", c.pan),
        ("GSTIN:", c.gstn),
        ("State:", f"{c.state or '—'}   Code: {c.state_code or '—'}"),
    )
    # ── Reference cell: text on the left, QR on the right ───────────────────────
    # W_REF = 192.20 pt (merged span of cols 6-9).
    # We embed a borderless 2-column inner table so the QR sits at the top-right
    # and the reference text expands downward without ever overlapping.
    QR_CELL_W = 58.0                          # width reserved for QR column
    REF_TEXT_W = W_REF - QR_CELL_W - 8       # 4 pt padding each side of gap

    ref_text_para = _lines(
        ("Order No    :", order.order_no),
        ("Order Date  :", str(order.order_date or "")),
        ("Quotation No:", order.quotation_no),
        ("Quot. Date  :", str(order.quotation_date or "")),
        ("Category    :", category_name or order.category_code or "—"),
        ("Created By  :", creator_name or "—"),
        ("Project     :", order.project_code),
        ("Status      :", order.workflow_status),
    )

    # Build QR cell content — graceful fallback when bytes unavailable
    if qr_bytes:
        try:
            qr_img = RLImage(io.BytesIO(qr_bytes), width=QR_CELL_W, height=QR_CELL_W)
            qr_cell = qr_img
        except Exception:
            qr_cell = ""
    else:
        qr_cell = ""

    # Inner table: [ref_text | QR]; no borders so it blends into the outer cell
    ref_inner = Table(
        [[ref_text_para, qr_cell]],
        colWidths=[REF_TEXT_W, QR_CELL_W],
    )
    ref_inner.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("ALIGN",         (1, 0), (1, 0),  "RIGHT"),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (0, 0),  4),   # gap between text and QR
        ("RIGHTPADDING",  (1, 0), (1, 0),  0),
    ]))

    r1 = [vendor_para, "", comp_para, "", "", "", ref_inner, "", "", ""]

    # ── Row 2: preamble text ───────────────────────────────────────────────────
    pream = Paragraph(
        "<b>Dear Sir / Madam,</b><br/>"
        "With reference to your quotation and our discussions, we are pleased "
        "to place this Purchase Order for the supply of materials / services "
        "as detailed below. Please acknowledge receipt and confirm acceptance "
        "of this order.",
        ST_PREAM,
    )
    r2 = [pream, "", "", "", "", "", "", "", "", ""]

    rows = [r0, r1, r2]

    tbl = Table(rows, colWidths=COL_W)
    tbl.setStyle(TableStyle([
        # Global defaults
        ("FONTNAME",       (0, 0), (-1, -1), F),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("LEADING",        (0, 0), (-1, -1), 10.8),
        ("TOPPADDING",     (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 3),
        ("LEFTPADDING",    (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 4),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ("GRID",           (0, 0), (-1, -1), 0.5, C_BLACK),

        # Row 0: party header
        ("SPAN",           (0, 0), (1, 0)),    # vendor label
        ("SPAN",           (2, 0), (5, 0)),    # company label
        ("SPAN",           (6, 0), (9, 0)),    # reference label
        ("BACKGROUND",     (0, 0), (-1, 0), C_GRAY_HD),
        ("VALIGN",         (0, 0), (-1, 0), "MIDDLE"),
        ("MINROWHEIGHT",   (0, 0), (0, 0),  RH_PARTY),

        # Row 1: party body content
        ("SPAN",           (0, 1), (1, 1)),
        ("SPAN",           (2, 1), (5, 1)),
        ("SPAN",           (6, 1), (9, 1)),

        # Row 2: preamble full-width
        ("SPAN",           (0, 2), (9, 2)),
    ]))
    return tbl


# ══════════════════════════════════════════════════════════════════════════════
# ITEMS TABLE  (items header + item rows + all totals)
# repeatRows=1  →  items-header row repeats on every page this table spans.
# ══════════════════════════════════════════════════════════════════════════════

def _build_items_table(order, items):
    """
    Return a 10-column Table:
      Row 0      : items column header  (D9D9D9, 10 cols — REPEATS on page break)
      Row 1..N   : item data rows       (at least 4 rows, padded with blanks)
      Row N+1    : TOTAL               (D9D9D9, partial merge)
      Row N+2    : Total Basic Amount
      Row N+3    : CGST @
      Row N+4    : SGST @
      Row N+5    : IGST  @
      Row N+6    : Total Order Amount  (BFBFBF)
      Row N+7    : Amount in words     (full merge)
    """
    # Use exactly as many rows as there are items — no filler.
    # ReportLab handles page breaks automatically; totals always follow the last row.
    n_items = len(items) if items else 1   # at least 1 blank row so table renders

    # Pre-compute totals
    basic_total = sum(i.get("amount",     0) for i in items)
    gst_total   = sum(i.get("gst_amount", 0) for i in items)
    grand_total  = float(order.total_amount or 0)
    cgst = sgst  = 0.0
    for oi in order.items:
        g     = float(oi.gst_amount or 0)
        cgst += g / 2
        sgst += g / 2
    igst = 0.0

    rows = []

    # ── Row 0: items column header (repeats on page break) ────────────────────
    # Labels match the template (from tblGrid row in Order.docx)
    HDR_LABELS = [
        "SL.\nNo.", "Item Details", "HSN/\nSAC", "Unit",
        "Order\nQty", "Unit Rate\n(INR)", "Basic\nAmount",
        "GST\n%", "GST\nAmount", "Total\nAmount",
    ]
    rows.append([Paragraph(lbl, ST_BOLD_C) for lbl in HDR_LABELS])

    # ── Rows 1..N: item data ──────────────────────────────────────────────────
    # Alignment rules matching template:
    #   CENTER: SL(0), HSN(2), Unit(3), Qty(4)
    #   RIGHT : Rate(5), BasicAmt(6), GSTAmt(8), TotalAmt(9)
    #   LEFT  : ItemDetails(1), GST%(7) — GST% is center in template but using left here
    CENTER_CI = {0, 2, 3, 4}
    RIGHT_CI  = {5, 6, 8, 9}

    for ri in range(n_items):
        if ri < len(items):
            it = items[ri]
            row_cells = []
            for ci in range(10):
                if ci == 0:
                    row_cells.append(Paragraph(str(it.get("sl", "")), ST_BODY_C))
                elif ci == 1:
                    # Item name (bold) + optional note (7pt gray below)
                    name = it.get("item_name", "") or ""
                    note = it.get("note",      "") or ""
                    txt  = f"<b>{name}</b>"
                    if note:
                        txt += (f'<br/>'
                                f'<font name="{F}" size="7" color="#7F7F7F">'
                                f'{note}</font>')
                    row_cells.append(Paragraph(txt, ST_BODY))
                elif ci == 2:
                    row_cells.append(Paragraph(it.get("hsn_sac", "") or "", ST_BODY_C))
                elif ci == 3:
                    row_cells.append(Paragraph(it.get("unit", "") or "", ST_BODY_C))
                elif ci == 4:
                    row_cells.append(Paragraph(f"{it.get('qty', 0):.2f}", ST_BODY_C))
                elif ci == 5:
                    row_cells.append(Paragraph(f"{it.get('rate', 0):,.2f}", ST_BODY_R))
                elif ci == 6:
                    row_cells.append(Paragraph(f"{it.get('amount', 0):,.2f}", ST_BODY_R))
                elif ci == 7:
                    row_cells.append(Paragraph(f"{it.get('gst_percent', 0):.1f}", ST_BODY_C))
                elif ci == 8:
                    row_cells.append(Paragraph(f"{it.get('gst_amount', 0):,.2f}", ST_BODY_R))
                elif ci == 9:
                    row_cells.append(Paragraph(f"{it.get('total', 0):,.2f}", ST_BODY_R))
            rows.append(row_cells)
        else:
            # Single blank row when there are no items at all
            rows.append([""] * 10)

    # ── TOTAL row ──────────────────────────────────────────────────────────────
    # Col 0 blank | cols 1-5 "TOTAL" | col 6 basic | col 7 blank | col 8 gst | col 9 grand
    rows.append([
        "",
        Paragraph("TOTAL", ST_BOLD_C),             # spans 1-5
        "", "", "", "",
        Paragraph(f"{basic_total:,.2f}", ST_BOLD_R),
        "",
        Paragraph(f"{gst_total:,.2f}",  ST_BOLD_R),
        Paragraph(f"{grand_total:,.2f}", ST_BOLD_R),
    ])

    # ── Total Basic Amount row ─────────────────────────────────────────────────
    basic_val = float(order.basic_amount or 0)
    rows.append([
        Paragraph("Total Basic Amount", ST_10_BR),  # spans 0-4
        "", "", "", "",
        Paragraph(f"INR  {basic_val:,.2f}", ST_10_BR),  # spans 5-9
        "", "", "", "",
    ])

    # ── Tax rows: CGST / SGST / IGST ──────────────────────────────────────────
    for label, amt in [("CGST @", cgst), ("SGST @", sgst), ("IGST  @", igst)]:
        rows.append([
            Paragraph(label, ST_10_R),              # spans 0-4
            "", "", "", "",
            "", "", "",                             # spans 5-7 (blank)
            Paragraph(f"INR  {amt:,.2f}", ST_10_R), # spans 8-9
            "",
        ])

    # ── Grand Total row (BFBFBF background) ───────────────────────────────────
    rows.append([
        Paragraph("Total Order Amount", ST_10_BR),  # spans 0-4
        "", "", "", "",
        "", "", "",                                 # spans 5-7 (blank)
        Paragraph(f"INR  {grand_total:,.2f}", ST_10_BR),  # spans 8-9
        "",
    ])

    # ── Amount in words (full-width merge) ────────────────────────────────────
    words = _num_to_words(int(round(grand_total)))
    rows.append([
        Paragraph(
            f"Order Value in Words:  {words} Rupees Only",
            ST_WORDS,
        ),
        "", "", "", "", "", "", "", "", "",
    ])

    # ── Row index helpers ──────────────────────────────────────────────────────
    # Row 0 = items header
    # Rows 1..n_items = item data
    r_tot   = 1 + n_items          # TOTAL row
    r_basic = 2 + n_items
    r_cgst  = 3 + n_items
    r_sgst  = 4 + n_items
    r_igst  = 5 + n_items
    r_grand = 6 + n_items
    r_words = 7 + n_items

    # ── TableStyle ─────────────────────────────────────────────────────────────
    style = TableStyle([
        # Global
        ("FONTNAME",       (0, 0), (-1, -1), F),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("LEADING",        (0, 0), (-1, -1), 10.8),
        ("TOPPADDING",     (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 2),
        ("LEFTPADDING",    (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 3),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ("GRID",           (0, 0), (-1, -1), 0.5, C_BLACK),

        # ── Row 0: items header ────────────────────────────────────────────────
        ("BACKGROUND",     (0, 0), (-1, 0),  C_GRAY_HD),
        ("FONTNAME",       (0, 0), (-1, 0),  FB),
        ("ALIGN",          (0, 0), (-1, 0),  "CENTER"),
        ("VALIGN",         (0, 0), (-1, 0),  "MIDDLE"),
        ("MINROWHEIGHT",   (0, 0), (0, 0),   RH_ITEMS),

        # ── Item rows: column alignment ────────────────────────────────────────
        # CENTER columns: SL(0), HSN(2), Unit(3), Qty(4)
        ("ALIGN",          (0, 1), (0, r_tot - 1), "CENTER"),
        ("ALIGN",          (2, 1), (4, r_tot - 1), "CENTER"),
        # RIGHT columns: Rate(5), BasicAmt(6), GSTAmt(8), TotalAmt(9)
        ("ALIGN",          (5, 1), (6, r_tot - 1), "RIGHT"),
        ("ALIGN",          (8, 1), (9, r_tot - 1), "RIGHT"),

        # ── TOTAL row ──────────────────────────────────────────────────────────
        ("SPAN",           (1, r_tot),   (5, r_tot)),
        ("BACKGROUND",     (0, r_tot),   (-1, r_tot),   C_GRAY_HD),
        ("FONTNAME",       (0, r_tot),   (-1, r_tot),   FB),
        ("VALIGN",         (0, r_tot),   (-1, r_tot),   "MIDDLE"),
        ("ALIGN",          (1, r_tot),   (5, r_tot),    "CENTER"),
        ("ALIGN",          (6, r_tot),   (9, r_tot),    "RIGHT"),
        ("MINROWHEIGHT",   (0, r_tot),   (0, r_tot),    RH_TOTAL),

        # ── Total Basic Amount ──────────────────────────────────────────────────
        ("SPAN",           (0, r_basic), (4, r_basic)),
        ("SPAN",           (5, r_basic), (9, r_basic)),
        ("FONTNAME",       (0, r_basic), (-1, r_basic), FB),
        ("ALIGN",          (0, r_basic), (4, r_basic),  "RIGHT"),
        ("ALIGN",          (5, r_basic), (9, r_basic),  "RIGHT"),
        ("FONTSIZE",       (0, r_basic), (-1, r_basic), 10),

        # ── CGST row ───────────────────────────────────────────────────────────
        ("SPAN",           (0, r_cgst), (4, r_cgst)),
        ("SPAN",           (5, r_cgst), (7, r_cgst)),
        ("SPAN",           (8, r_cgst), (9, r_cgst)),
        ("ALIGN",          (0, r_cgst), (4, r_cgst), "RIGHT"),
        ("ALIGN",          (8, r_cgst), (9, r_cgst), "RIGHT"),
        ("FONTSIZE",       (0, r_cgst), (-1, r_cgst), 10),

        # ── SGST row ───────────────────────────────────────────────────────────
        ("SPAN",           (0, r_sgst), (4, r_sgst)),
        ("SPAN",           (5, r_sgst), (7, r_sgst)),
        ("SPAN",           (8, r_sgst), (9, r_sgst)),
        ("ALIGN",          (0, r_sgst), (4, r_sgst), "RIGHT"),
        ("ALIGN",          (8, r_sgst), (9, r_sgst), "RIGHT"),
        ("FONTSIZE",       (0, r_sgst), (-1, r_sgst), 10),

        # ── IGST row ───────────────────────────────────────────────────────────
        ("SPAN",           (0, r_igst), (4, r_igst)),
        ("SPAN",           (5, r_igst), (7, r_igst)),
        ("SPAN",           (8, r_igst), (9, r_igst)),
        ("ALIGN",          (0, r_igst), (4, r_igst), "RIGHT"),
        ("ALIGN",          (8, r_igst), (9, r_igst), "RIGHT"),
        ("FONTSIZE",       (0, r_igst), (-1, r_igst), 10),

        # ── Grand Total row (BFBFBF) ───────────────────────────────────────────
        ("SPAN",           (0, r_grand), (4, r_grand)),
        ("SPAN",           (5, r_grand), (7, r_grand)),
        ("SPAN",           (8, r_grand), (9, r_grand)),
        ("BACKGROUND",     (0, r_grand), (-1, r_grand), C_GRAY_TOT),
        ("FONTNAME",       (0, r_grand), (-1, r_grand), FB),
        ("ALIGN",          (0, r_grand), (4, r_grand), "RIGHT"),
        ("ALIGN",          (8, r_grand), (9, r_grand), "RIGHT"),
        ("VALIGN",         (0, r_grand), (-1, r_grand), "MIDDLE"),
        ("FONTSIZE",       (0, r_grand), (-1, r_grand), 10),

        # ── Amount in words ────────────────────────────────────────────────────
        ("SPAN",           (0, r_words), (9, r_words)),
        ("FONTNAME",       (0, r_words), (9, r_words), FBI),
        ("FONTSIZE",       (0, r_words), (9, r_words), 10),
        ("VALIGN",         (0, r_words), (9, r_words), "MIDDLE"),
    ])

    # repeatRows=1 — items header (row 0) repeats on every page this table spans
    tbl = Table(rows, colWidths=COL_W, repeatRows=1)
    tbl.setStyle(style)
    return tbl


# ══════════════════════════════════════════════════════════════════════════════
# TERMS & CONDITIONS SECTION
# ══════════════════════════════════════════════════════════════════════════════

def _build_terms(terms):
    """Return a list of Platypus flowables for the T&C section."""
    if not terms:
        return []
    elems = [Paragraph("SPECIFIC TERMS &amp; CONDITIONS", ST_TC_HDR)]
    for i, t in enumerate(terms, 1):
        hdr_text = t.get("header", "") or ""
        desc     = t.get("description", "") or ""
        elems.append(
            Paragraph(
                f"{i}. <b>{hdr_text}:</b> {desc}",
                ST_TC_NUM,
            )
        )
    return elems


# ══════════════════════════════════════════════════════════════════════════════
# SIGNATURE BLOCK
# ══════════════════════════════════════════════════════════════════════════════

def _build_signature(prepared_by, checked_by, authorised_by):
    """Return a 3-column signature Table."""
    slots = [
        ("Prepared By",   prepared_by),
        ("Checked By",    checked_by[0] if checked_by else None),
        ("Authorised By", authorised_by),
    ]
    col_w = TABLE_W / 3

    hdr_row  = []
    body_row = []
    for label, person in slots:
        hdr_row.append(Paragraph(label, ST_SIG_H))
        val = (f"{person['name']}\n{person['at']}"
               if person else "—")
        body_row.append(Paragraph(val, ST_SIG_B))

    sig_tbl = Table([hdr_row, body_row], colWidths=[col_w] * 3)
    sig_tbl.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, -1), F),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("GRID",          (0, 0), (-1, -1), 0.5, C_BLACK),
        ("BACKGROUND",    (0, 0), (-1, 0),  C_GRAY_HD),
        ("FONTNAME",      (0, 0), (-1, 0),  FB),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return sig_tbl


# ══════════════════════════════════════════════════════════════════════════════
# NUMBER TO WORDS HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _num_to_words(n):
    """Convert integer rupee amount to Indian English words."""
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
            "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
            "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty",
            "Sixty", "Seventy", "Eighty", "Ninety"]

    def _h(x):
        if x == 0:   return ""
        if x < 20:   return ones[x] + " "
        if x < 100:  return tens[x // 10] + (" " + ones[x % 10] if x % 10 else "") + " "
        return ones[x // 100] + " Hundred " + _h(x % 100)

    n = int(n)
    if n == 0:
        return "Zero"
    crore = n // 10_000_000;  n %= 10_000_000
    lakh  = n // 100_000;     n %= 100_000
    thou  = n // 1_000;       n %= 1_000
    parts = []
    if crore: parts.append(_h(crore).strip() + " Crore")
    if lakh:  parts.append(_h(lakh).strip()  + " Lakh")
    if thou:  parts.append(_h(thou).strip()  + " Thousand")
    if n:     parts.append(_h(n).strip())
    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_pdf(order, company, vendor, items, terms,
               prepared_by, checked_by, authorised_by,
               qr_bytes, fp, generated_at,
               creator_name="", category_name=""):
    """
    Build and return the complete PDF as bytes using ReportLab Platypus.

    Structure:
      - BaseDocTemplate with one PageTemplate
      - PageTemplate.onPage = _draw_page (draws header + microprint footer)
      - Frame = body content area (between header and bottom margin)
      - Story:
          1. Info table   (parties + preamble)         — KeepTogether if small
          2. Items table  (items header + data + totals)
          3. Terms & Conditions paragraphs
          4. Spacer + "For DISHAAN..." heading
          5. Signature table
    """
    buf = io.BytesIO()

    # ── Document ───────────────────────────────────────────────────────────────
    doc = BaseDocTemplate(
        buf,
        pagesize=(PG_W, PG_H),
        leftMargin=MG_L,
        rightMargin=MG_R,
        topMargin=MG_T,
        bottomMargin=MG_B,
        title=f"Purchase Order — {order.order_no or ''}",
        author="Dishaan Hi-Tech (India) Pvt. Ltd.",
    )

    # ── Frame (body area) ──────────────────────────────────────────────────────
    frame = Frame(
        MG_L,                          # x
        MG_B,                          # y (from page bottom)
        CONTENT_W,                     # width
        PG_H - MG_T - MG_B,           # height = 664.4 pt
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )

    # ── Page template (attaches onPage callback) ────────────────────────────────
    pt = PageTemplate(id="main", frames=[frame], onPage=_draw_page)
    doc.addPageTemplates([pt])

    # ── State passed to _draw_page via doc._pdf_state ──────────────────────────
    doc._pdf_state = {
        "company":      company,
        "qr_bytes":     qr_bytes,
        "fp":           fp,
        "generated_at": generated_at,
        "logo_path":    LOGO_PATH,
        "category_name": order.category_code
    }

    # ── Story (flowing body content) ───────────────────────────────────────────
    story = []

    # 1. Info table (parties + preamble) — keep as one block where possible
    info_tbl = _build_info_table(
        order, vendor, company,
        qr_bytes=qr_bytes,
        creator_name=creator_name,
        category_name=category_name,
    )
    story.append(KeepTogether(info_tbl))

    story.append(Spacer(1, 2))         # 2pt gap between info table and items

    # 2. Items + totals table (items header repeats on page break)
    items_tbl = _build_items_table(order, items)
    story.append(items_tbl)

    # 3. Terms & Conditions
    tc_elems = _build_terms(terms)
    if tc_elems:
        story.extend(tc_elems)

    # 4. Signature heading
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "For DISHAAN HI-TECH (INDIA) PVT. LTD.",
            _ps("sig_co", size=10, bold=True, sp_before=4, sp_after=4),
        )
    )

    # 5. Signature table
    story.append(_build_signature(prepared_by, checked_by, authorised_by))

    # ── Build PDF ──────────────────────────────────────────────────────────────
    doc.build(story)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def generate_order_pdf(order_id, base_url, force=False):
    """
    Generate (or serve cached) Order PDF.

    ?force=1  →  delete existing cached PDF and regenerate fresh.
    """
    try:
        order = OrderMaster.query.get(order_id)
        if not order:
            return res("Order not found", [], 404)

        # ── Force-delete: remove the specific cached file and clear DB fields ────
        if force:
            if getattr(order, "pdf_url", None):
                try:
                    base_prefix = current_app.config.get(
                        "PDF_BASE_URL", "/resource/order/pdf-file"
                    )
                    relative = order.pdf_url.replace(base_prefix + "/", "", 1)
                    old_path = os.path.join(_storage_root(), relative)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except Exception:
                    pass
            # Always clear DB fields on force so we never serve the old URL
            order.pdf_url = order.pdf_token = order.pdf_generated_at = None

        # ── Return cached PDF if still valid AND file exists on disk ─────────
        if (
            not force
            and getattr(order, "pdf_url",          None)
            and getattr(order, "pdf_generated_at", None)
        ):
            age = (datetime.utcnow() - order.pdf_generated_at).days
            if age < PDF_EXPIRY_DAYS:
                base_prefix = current_app.config.get(
                    "PDF_BASE_URL", "/resource/order/pdf-file"
                )
                relative  = order.pdf_url.replace(base_prefix + "/", "", 1)
                full_path = os.path.join(_storage_root(), relative)
                if os.path.exists(full_path):
                    return serve_pdf_file(relative)
                # File missing on disk — clear stale DB record and regenerate
                order.pdf_url = order.pdf_token = order.pdf_generated_at = None

        # ── Gather data ────────────────────────────────────────────────────────
        company = Company.query.first()
        fp      = _fingerprint(order)
        token   = _serializer().dumps(
            {"oid": order.id, "ono": order.order_no, "fp": fp},
            salt=PDF_TOKEN_SALT,
        )
        verify_url   = f"{base_url.rstrip('/')}/resource/order/verify/{token}"
        qr_bytes     = _qr_with_brackets(verify_url)
        generated_at = datetime.utcnow().strftime("%d-%b-%Y %H:%M UTC")

        # Vendor (use a fallback stub if not linked)
        vendor = order.vendor
        if not vendor:
            class _FV:
                ledger_name = registered_address = pan = gstin = ""
                state_name = state_code = primary_contact_person = ""
                primary_contact_number = email = ""
            vendor = _FV()

        # Items list
        items = []
        for i, oi in enumerate(order.items, 1):
            hsn  = getattr(oi.item, "hsn_sac", "") or "" if oi.item else ""
            unit = (oi.item.unit.unit_name
                    if oi.item and oi.item.unit else "")
            items.append({
                "sl":          i,
                "item_code":   oi.item_code or "",
                "item_name":   oi.item.item_name if oi.item else "",
                "note":        oi.custom_note or "",
                "hsn_sac":     hsn,
                "unit":        unit,
                "qty":         float(oi.qty         or 0),
                "rate":        float(oi.rate        or 0),
                "amount":      float(oi.amount      or 0),
                "gst_percent": float(oi.gst_percent or 0),
                "gst_amount":  float(oi.gst_amount  or 0),
                "total":       float(oi.amount or 0) + float(oi.gst_amount or 0),
            })

        # Terms & Conditions
        terms = [
            {
                "header":      t.term.header if t.term else "",
                "description": (t.custom_description
                                or (t.term.term_description if t.term else "")),
            }
            for t in order.terms_conditions
        ]

        # Approval history (Prepared / Checked / Authorised)
        history = (
            db.session.query(ApprovalHistory, User.username)
            .outerjoin(User, User.id == ApprovalHistory.action_by)
            .filter(
                ApprovalHistory.module_code == "order",
                ApprovalHistory.record_id   == order.id,
            )
            .order_by(ApprovalHistory.id.asc())
            .all()
        )
        prepared_by = None
        checked_by  = []
        authorised_by = None
        for h, username in history:
            name = username or "—"
            at   = (h.created_at.strftime("%d-%b-%Y; %H:%M")
                    if h.created_at else "")
            if   h.action == "SUBMIT":        prepared_by   = {"name": name, "at": at}
            elif h.action == "FINAL_APPROVE": authorised_by = {"name": name, "at": at}
            elif h.action == "APPROVE":       checked_by.append({"name": name, "at": at})

        # ── Creator name (from order.creator relationship → User.username) ──────
        creator_name = ""
        if order.creator:
            creator_name = (getattr(order.creator, "username", None)
                            or getattr(order.creator, "name", None)
                            or "")

        # ── Category label (dynamic — fetch from CategoryMaster by category_code) ─
        category_name = order.category_code
        # if order.category_code:
        #     cat = CategoryMaster.query.filter_by(
        #         fixed_code=order.category_code
        #     ).first()
        #     category_name = (cat.category_name if cat else order.category_code)

        # ── Generate PDF ───────────────────────────────────────────────────────
        pdf_bytes = _build_pdf(
            order, company, vendor, items, terms,
            prepared_by, checked_by, authorised_by,
            qr_bytes, fp, generated_at,
            creator_name=creator_name,
            category_name=category_name,
        )

        # ── Persist metadata ───────────────────────────────────────────────────
        pdf_url = _save_pdf(pdf_bytes, order.order_no)
        order.pdf_url          = pdf_url
        order.pdf_token        = token
        order.pdf_generated_at = datetime.utcnow()
        db.session.commit()

        # ── Return PDF response ────────────────────────────────────────────────
        response = make_response(pdf_bytes)
        response.headers["Content-Type"]        = "application/pdf"
        response.headers["Content-Disposition"] = (
            f'inline; filename="{order.order_no}.pdf"'
        )
        # Prevent ANY intermediate cache from returning a stale copy on force=1
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"]        = "no-cache"
        response.headers["Expires"]       = "0"
        return response

    except Exception as e:
        import traceback
        traceback.print_exc()          # prints full error to terminal
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════════════════
# QR VERIFICATION  (public endpoint, scanned by recipient)
# ══════════════════════════════════════════════════════════════════════════════

def verify_order_pdf(token):
    try:
        data  = _serializer().loads(token, salt=PDF_TOKEN_SALT,
                                    max_age=PDF_EXPIRY_DAYS * 86400)
        order = OrderMaster.query.get(data["oid"])
        if not order or order.pdf_token != token:
            return _page("invalid")
        if data.get("fp") != _fingerprint(order):
            return _page("tampered", order)
        # Serve PDF bytes directly — never expose real file path in browser URL.
        # Browser URL stays as /resource/order/verify/<token> permanently.
        base_prefix = current_app.config.get("PDF_BASE_URL", "/resource/order/pdf-file")
        relative    = order.pdf_url.replace(base_prefix + "/", "", 1)
        full_path   = os.path.join(_storage_root(), relative)
        with open(full_path, "rb") as fh:
            pdf_bytes = fh.read()
        resp = make_response(pdf_bytes)
        resp.headers["Content-Type"]        = "application/pdf"
        # Use order_no as filename so download name is clean, not the real path
        resp.headers["Content-Disposition"] = f'inline; filename="{order.order_no}.pdf"'
        resp.headers["Cache-Control"]       = "no-store"
        return resp
    except SignatureExpired as e:
        try:
            payload = e.payload
            if payload:
                order = OrderMaster.query.get(payload.get("oid"))
                if order and order.pdf_token == token:
                    order.pdf_url = order.pdf_token = order.pdf_generated_at = None
                    db.session.commit()
        except Exception:
            pass
        return _page("expired")
    except BadSignature:
        return _page("invalid")
    except Exception as e:
        return _page("error", msg=str(e))


def _page(status, order=None, msg=""):
    cfg = {
        "valid":    ("#2e7d32", "✓ DOCUMENT VERIFIED",
                     (f"Order <b>{order.order_no}</b> is authentic.<br/>"
                      f"Total: ₹{float(order.total_amount or 0):,.2f}")
                     if order else "Verified."),
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
<title>Order Verification</title>
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
