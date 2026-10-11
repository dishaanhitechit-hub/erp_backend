from app.extensions import db


class WhatsappLog(db.Model):
    __tablename__ = "whatsapp_log"

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), nullable=False)
    module_code = db.Column(db.String(50))
    record_id = db.Column(db.Integer)
    project_code = db.Column(db.String(50))
    event = db.Column(db.String(30))  # SUBMIT/APPROVE/FINAL_APPROVE/REBACK/REJECT/PENDING_REBACK/PENDING_REJECT
    message_text = db.Column(db.Text)
    status = db.Column(db.String(10))  # sent / failed / pending
    wa_message_id = db.Column(db.String(100), index=True)
    error_msg = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, server_default=db.func.now())
