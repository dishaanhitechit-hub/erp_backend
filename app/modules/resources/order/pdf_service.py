# app/modules/resources/order/pdf_service.py
# Order PDF generation + QR verification

import io, base64, hashlib, os
import qrcode
from datetime import datetime
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from xhtml2pdf import pisa
from jinja2 import Environment, FileSystemLoader
from flask import current_app, make_response, send_from_directory

from app.extensions import db
from app.models.orderMaster import OrderMaster
from app.models.companies import Company
from app.models.approval_path import ApprovalHistory
from app.models.user import User
from app.response import res

PDF_TOKEN_SALT  = "order-pdf-v1"
PDF_EXPIRY_DAYS = 2


# ══════════════════════════════════════════════════════════════════
# STORAGE — LOCAL SERVER
# ──────────────────────────────────────────────────────────────────
# When BunnyCDN is available again:
#   1. Remove save_pdf_file() and pdf_file_url() below
#   2. Import upload_file_to_bunny from app.cloudinary_uploader
#   3. In generate_order_pdf(), replace the "# [STORAGE]" block with:
#        pdf_url = upload_file_to_bunny(
#            file=_PDFFile(pdf_buf, "order.pdf"),
#            mainFolder="order_pdf", subFolder=order.order_no, fileName="order"
#        )
#   4. Remove the /pdf-file/<path> route from routes.py
# ══════════════════════════════════════════════════════════════════

def _storage_root():
    # [STORAGE] Single place to change the disk path
    return current_app.config.get("PDF_STORAGE_PATH")


def save_pdf_file(pdf_buf, order_no):
    # [STORAGE] Saves PDF to local disk, returns the public URL path
    root     = _storage_root()
    folder   = os.path.join(root, "order_pdf", order_no)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, "order.pdf")
    with open(filepath, "wb") as f:
        f.write(pdf_buf.read())
    # Returns a URL path — served by the /pdf-file route in routes.py
    base_url = current_app.config.get("PDF_BASE_URL", "/resource/order/pdf-file")
    return f"{base_url}/order_pdf/{order_no}/order.pdf"


def serve_pdf_file(relative_path):
    # [STORAGE] Serves a stored PDF file by its relative path
    root     = _storage_root()
    # relative_path example: "order_pdf/440001/order.pdf"
    full_dir = os.path.join(root, os.path.dirname(relative_path))
    filename = os.path.basename(relative_path)
    return send_from_directory(full_dir, filename, mimetype="application/pdf")


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _serializer():
    secret = current_app.config.get("JWT_SECRET_KEY", "erp-secret")
    return URLSafeTimedSerializer(secret)


def _fingerprint(order):
    raw = f"{order.order_no}|{float(order.basic_amount or 0):.2f}|{float(order.total_amount or 0):.2f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()


def _img_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _qr_b64(url):
    qr = qrcode.QRCode(box_size=4, border=2,
                        error_correction=qrcode.constants.ERROR_CORRECT_H)
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ══════════════════════════════════════════════════════════════════
# GENERATE PDF
# ══════════════════════════════════════════════════════════════════

def generate_order_pdf(order_id, base_url):
    try:
        order = OrderMaster.query.get(order_id)
        if not order:
            return res("Order not found", [], 404)

        # return cached if still within 2 days
        if order.pdf_url and order.pdf_generated_at:
            age = (datetime.utcnow() - order.pdf_generated_at).days
            if age < PDF_EXPIRY_DAYS:
                # [STORAGE] serve cached PDF directly
                base_prefix = current_app.config.get("PDF_BASE_URL", "/resource/order/pdf-file")
                relative = order.pdf_url.replace(base_prefix + "/", "", 1)
                return serve_pdf_file(relative)
                # [END STORAGE]

        company = Company.query.first()
        fp      = _fingerprint(order)
        token   = _serializer().dumps(
            {"oid": order.id, "ono": order.order_no, "fp": fp},
            salt=PDF_TOKEN_SALT
        )
        verify_url = f"{base_url.rstrip('/')}/resource/order/verify/{token}"

        logo_path = os.getenv("COMPANY_LOGO_PATH",
                              os.path.join(os.getcwd(), "asset", "order", "1000018063.jpeg"))
        logo_b64  = _img_b64(logo_path)
        qr_b64    = _qr_b64(verify_url)

        # party details by category
        cat = order.category_code
        if cat == "Customer_Supply_Order":
            p = order.project
            party_name, party_address, party_gstn = (
                (p.client_name, p.registered_address, p.gstn) if p else ("", "", ""))
        elif cat == "Site_Transfer_Order":
            p = order.transfer_site_project
            party_name, party_address, party_gstn = (
                (p.client_name, p.shipping_address, p.gstn) if p else ("", "", ""))
        else:
            v = order.vendor
            party_name, party_address, party_gstn = (
                (v.ledger_name, v.registered_address, v.gstin) if v else ("", "", ""))

        items = [
            {
                "sl": i, "item_code": oi.item_code,
                "item_name":   oi.item.item_name if oi.item else "",
                "note":        oi.custom_note or "",
                "qty":         float(oi.qty or 0),
                "unit":        oi.item.unit.unit_name if oi.item and oi.item.unit else "",
                "rate":        float(oi.rate or 0),
                "amount":      float(oi.amount or 0),
                "gst_percent": float(oi.gst_percent or 0),
                "gst_amount":  float(oi.gst_amount or 0),
            }
            for i, oi in enumerate(order.items, 1)
        ]

        terms = [
            {
                "header":      t.term.header if t.term else "",
                "description": t.custom_description or (t.term.term_description if t.term else ""),
            }
            for t in order.terms_conditions
        ]

        # build signature slots from approval history — join User to avoid lazy load issues
        history = (
            db.session.query(ApprovalHistory, User.username)
            .outerjoin(User, User.id == ApprovalHistory.action_by)
            .filter(
                ApprovalHistory.module_code == "order",
                ApprovalHistory.record_id   == order.id
            )
            .order_by(ApprovalHistory.id.asc())
            .all()
        )

        prepared_by   = None   # SUBMIT
        checked_by    = []     # APPROVE (intermediate)
        authorised_by = None   # FINAL_APPROVE

        for h, username in history:
            name = username or "—"
            at   = h.created_at.strftime("%d-%b-%Y") if h.created_at else ""
            if h.action == "SUBMIT":
                prepared_by = {"name": name, "at": at}
            elif h.action == "FINAL_APPROVE":
                authorised_by = {"name": name, "at": at}
            elif h.action == "APPROVE":
                checked_by.append({"name": name, "at": at})

        ctx = dict(
            logo_b64=logo_b64, qr_b64=qr_b64, fingerprint=fp,
            generated_at=datetime.utcnow().strftime("%d-%b-%Y %H:%M UTC"),
            company=company, order=order,
            party_name=party_name, party_address=party_address, party_gstn=party_gstn,
            items=items, terms=terms,
            prepared_by=prepared_by, checked_by=checked_by, authorised_by=authorised_by,
        )

        tpl_dir = os.path.join(os.path.dirname(__file__))
        html    = Environment(loader=FileSystemLoader(tpl_dir)) \
                    .get_template("order_pdf.html").render(**ctx)

        pdf_buf = io.BytesIO()
        if pisa.CreatePDF(html, dest=pdf_buf).err:
            return res("PDF render error", [], 500)
        pdf_buf.seek(0)

        # [STORAGE] — swap this block when switching to BunnyCDN
        pdf_url = save_pdf_file(pdf_buf, order.order_no)
        # [END STORAGE]

        order.pdf_url          = pdf_url
        order.pdf_token        = token
        order.pdf_generated_at = datetime.utcnow()
        db.session.commit()

        # [STORAGE] serve newly generated PDF directly
        pdf_buf.seek(0)
        response = make_response(pdf_buf.read())
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f'inline; filename="{order.order_no}.pdf"'
        return response
        # [END STORAGE]

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# VERIFY — QR scan landing page (public, no JWT)
# ══════════════════════════════════════════════════════════════════

def verify_order_pdf(token):
    try:
        data  = _serializer().loads(token, salt=PDF_TOKEN_SALT,
                                    max_age=PDF_EXPIRY_DAYS * 86400)
        order = OrderMaster.query.get(data["oid"])

        if not order or order.pdf_token != token:
            return _page("invalid")
        if data.get("fp") != _fingerprint(order):
            return _page("tampered", order)

        # [STORAGE] serve PDF directly on valid QR scan
        # When switching to BunnyCDN: replace with redirect(order.pdf_url)
        base_prefix = current_app.config.get("PDF_BASE_URL", "/resource/order/pdf-file")
        relative = order.pdf_url.replace(base_prefix + "/", "", 1)
        return serve_pdf_file(relative)
        # [END STORAGE]

    except SignatureExpired as e:
        # cleanup DB — payload still accessible from the expired exception
        try:
            payload = e.payload
            if payload:
                order = OrderMaster.query.get(payload.get("oid"))
                if order and order.pdf_token == token:
                    order.pdf_url = order.pdf_token = order.pdf_generated_at = None
                    db.session.commit()
                    # [STORAGE] if using local disk, optionally delete the file here too
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
                     f"Order <b>{order.order_no}</b> is authentic and unaltered.<br>"
                     f"Total: ₹{float(order.total_amount or 0):,.2f}" if order else "Verified."),
        "tampered": ("#b71c1c", "⚠ TAMPERED DOCUMENT",
                     "Data does not match the original.<br><b>Do not accept this document.</b>"),
        "expired":  ("#e65100", "⏱ QR CODE EXPIRED",
                     "This QR is valid for 2 days only.<br>Request a regenerated document."),
        "invalid":  ("#37474f", "✗ INVALID QR", "This QR code is not recognised."),
        "error":    ("#37474f", "Error", msg),
    }
    color, title, body = cfg.get(status, cfg["invalid"])
    code = 200 if status == "valid" else 410 if status == "expired" else 400
    return make_response(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Order Verification</title>
<style>
  body{{font-family:Arial,sans-serif;display:flex;justify-content:center;
       align-items:center;min-height:100vh;margin:0;background:#f5f5f5;}}
  .card{{background:#fff;border-radius:12px;padding:40px;max-width:480px;
         text-align:center;box-shadow:0 4px 20px rgba(0,0,0,.12);}}
  .icon{{font-size:52px;color:{color};}}
  .title{{font-size:20px;font-weight:bold;color:{color};margin:12px 0;}}
  .body{{font-size:14px;color:#555;line-height:1.7;}}
</style></head><body>
<div class="card">
  <div class="icon">{title[0]}</div>
  <div class="title">{title}</div>
  <div class="body">{body}</div>
</div></body></html>""", code)
