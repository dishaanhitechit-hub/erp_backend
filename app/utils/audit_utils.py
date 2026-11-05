"""Shared helper to include audit fields in any service response dict."""


def audit_fields(record):
    """Return createdAt / updatedAt / createdBy / updatedBy for any model record.

    Works with:
    - models that have a ``creator`` / ``updater`` relationship (uses .username)
    - models that only store a raw user ID in created_by / updated_by
    - models that have no user tracking at all (fields come back as None)
    """
    from app.models.user import User  # local import to avoid circular deps

    created_at = getattr(record, "created_at", None)
    updated_at = getattr(record, "updated_at", None)

    # Prefer ORM relationship if already loaded
    creator = getattr(record, "creator", None)
    updater = getattr(record, "updater", None)

    created_by_name = None
    updated_by_name = None

    if creator:
        created_by_name = creator.username
    else:
        cb_id = getattr(record, "created_by", None)
        if cb_id:
            try:
                u = User.query.get(cb_id)
                created_by_name = u.username if u else None
            except Exception:
                pass

    if updater:
        updated_by_name = updater.username
    else:
        ub_id = getattr(record, "updated_by", None)
        if ub_id:
            try:
                u = User.query.get(ub_id)
                updated_by_name = u.username if u else None
            except Exception:
                pass

    return {
        "createdAt": created_at.strftime("%Y-%m-%d %H:%M") if created_at else None,
        "updatedAt": updated_at.strftime("%Y-%m-%d %H:%M") if updated_at else None,
        "createdBy": created_by_name,
        "updatedBy": updated_by_name,
    }
