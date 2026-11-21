"""
Document Cancellation API helpers.

Thin wrapper over reversal_service (the single engine that takes a posted
document out of the books). Kept so the /finance/accounting/cancel and
/cancellation-status routes keep their request shape.
"""

from .deletion_guard import CANCELLABLE_SOURCE_TYPES, is_posted, is_reversed
from . import reversal_service as RS


def cancel_posted_document(source_type, source_id, user_id, reason=None):
    """Cancel by accounting source_type + id. Returns (response_dict, status_code)."""
    if source_type not in CANCELLABLE_SOURCE_TYPES:
        return {"message": f"Unknown source_type: {source_type}"}, 400
    key = RS.key_for_source(source_type)
    if not key:
        return {"message": f"Unknown source_type: {source_type}"}, 400

    payload, status = RS.cancel_document(key, source_id, user_id, reason)
    if status != 200:
        return {"message": payload.get("message")}, status
    return {
        "message": payload["message"],
        "data": {
            "reversalId": payload["reversalId"],
            "reversalVoucherNo": payload["reversalVoucherNo"],
            "originalSourceType": payload["sourceType"],
            "originalSourceId": payload["sourceId"],
            "cancelledBy": user_id,
            "reason": payload["reason"],
        },
    }, 200


def get_cancellation_info(source_type, source_id):
    """Posting / reversal state of a document, with its full posting history."""
    history = RS.posting_history(source_type, source_id)
    if not history:
        return {"posted": False, "reversed": False, "history": []}, 200

    originals = [h for h in history if not h["isReversal"]]
    reversals = [h for h in history if h["isReversal"]]
    active = next((h for h in originals if not h["isReversed"]), None)
    last_rev = reversals[-1] if reversals else None

    return {
        "posted": is_posted(source_type, source_id),          # in the books right now
        "reversed": is_reversed(source_type, source_id),      # ever reversed
        "postingId": (active or originals[-1])["id"] if originals else None,
        "voucherNo": (active or originals[-1])["voucherNo"] if originals else None,
        "postingDate": (active or originals[-1])["postingDate"] if originals else None,
        "reversalId": last_rev["id"] if last_rev else None,
        "reversalVoucherNo": last_rev["voucherNo"] if last_rev else None,
        "reversedAt": last_rev["createdAt"] if last_rev else None,
        "reversedBy": last_rev["createdBy"] if last_rev else None,
        "history": history,
    }, 200
