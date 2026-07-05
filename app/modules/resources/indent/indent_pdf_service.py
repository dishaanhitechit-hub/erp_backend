import io, base64, os
from datetime import datetime
from xhtml2pdf import pisa
from jinja2 import Environment, FileSystemLoader
from flask import current_app, make_response, send_from_directory

from app.extensions import db
from app.models.indent_master import IndentMaster
from app.models.companies import Company
from app.models.approval_path import ApprovalHistory
from app.models.user import User
from app.response import res


def _storage_root():
    # [STORAGE] change path here or via INDENT_PDF_STORAGE_PATH env var
    return current_app.config.get(
        "INDENT_PDF_STORAGE_PATH",
        os.path.join(os.getcwd(), "storage", "pdf")
    )


def _save_pdf(pdf_buf, indent_no):
    # [STORAGE] saves to local disk
    root   = _storage_root()
    folder = os.path.join(root, "indent_pdf", indent_no)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "indent.pdf"), "wb") as f:
        f.write(pdf_buf.read())
    base_url = current_app.config.get("INDENT_PDF_BASE_URL", "/resource/indent/pdf-file")
    return f"{base_url}/indent_pdf/{indent_no}/indent.pdf"


def serve_indent_pdf(relative_path):
    # [STORAGE] serves local PDF
    root     = _storage_root()
    full_dir = os.path.join(root, os.path.dirname(relative_path))
    filename = os.path.basename(relative_path)
    return send_from_directory(full_dir, filename, mimetype="application/pdf")


def _img_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _build_signatures(indent_id):
    history = (
        db.session.query(ApprovalHistory, User.username)
        .outerjoin(User, User.id == ApprovalHistory.action_by)
        .filter(
            ApprovalHistory.module_code == "indent",
            ApprovalHistory.record_id   == indent_id
        )
        .order_by(ApprovalHistory.id.asc())
        .all()
    )

    prepared_by   = None
    checked_by    = []
    authorised_by = None

    for h, username in history:
        name = username or "—"
        at   = h.created_at.strftime("%d-%b-%Y") if h.created_at else ""
        if h.action == "SUBMIT":
            prepared_by = {"name": name, "at": at}
        elif h.action == "FINAL_APPROVE":
            authorised_by = {"name": name, "at": at}
        elif h.action == "APPROVE":
            checked_by.append({"name": name, "at": at})

    return prepared_by, checked_by, authorised_by


def generate_indent_pdf(indent_id):
    try:
        indent = IndentMaster.query.get(indent_id)
        if not indent:
            return res("Indent not found", [], 404)

        # serve cached if exists
        if getattr(indent, "pdf_url", None) and getattr(indent, "pdf_generated_at", None):
            age = (datetime.utcnow() - indent.pdf_generated_at).days
            if age < 2:
                base_prefix = current_app.config.get("INDENT_PDF_BASE_URL", "/resource/indent/pdf-file")
                relative = indent.pdf_url.replace(base_prefix + "/", "", 1)
                return serve_indent_pdf(relative)

        company = Company.query.first()

        logo_path = os.getenv("COMPANY_LOGO_PATH",
                              os.path.join(os.getcwd(), "asset", "order", "1000018063.jpeg"))
        logo_b64  = _img_b64(logo_path)

        items = [
            {
                "sl":        i,
                "item_code": ii.item_code,
                "item_name": ii.item.item_name if ii.item else "",
                "note":      ii.note or "",
                "unit":      ii.item.unit.unit_name if ii.item and ii.item.unit else "",
                "qty":       float(ii.qty or 0),
                "location":  ii.location or "",
            }
            for i, ii in enumerate(indent.indent_items, 1)
        ]

        prepared_by, checked_by, authorised_by = _build_signatures(indent.id)

        ctx = dict(
            logo_b64=logo_b64,
            generated_at=datetime.utcnow().strftime("%d-%b-%Y %H:%M UTC"),
            company=company,
            indent=indent,
            items=items,
            min_rows=max(5, len(items)),
            prepared_by=prepared_by,
            checked_by=checked_by,
            authorised_by=authorised_by,
        )

        tpl_dir = os.path.join(os.path.dirname(__file__))
        html    = Environment(loader=FileSystemLoader(tpl_dir)) \
                    .get_template("indent_pdf.html").render(**ctx)

        pdf_buf = io.BytesIO()
        if pisa.CreatePDF(html, dest=pdf_buf).err:
            return res("PDF render error", [], 500)
        pdf_buf.seek(0)

        # [STORAGE] save locally
        pdf_url = _save_pdf(pdf_buf, indent.indent_no)
        # [END STORAGE]

        # store url if model has pdf_url column (optional)
        if hasattr(indent, "pdf_url"):
            indent.pdf_url          = pdf_url
            indent.pdf_generated_at = datetime.utcnow()
            db.session.commit()

        # serve PDF directly
        pdf_buf.seek(0)
        response = make_response(pdf_buf.read())
        response.headers["Content-Type"]        = "application/pdf"
        response.headers["Content-Disposition"] = f'inline; filename="{indent.indent_no}.pdf"'
        return response

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
