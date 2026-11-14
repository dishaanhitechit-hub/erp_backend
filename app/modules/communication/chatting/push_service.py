# app/modules/communication/chatting/push_service.py
"""
Firebase Cloud Messaging push to the mobile app.

The push is a small high-priority *data* message ("something new — check").
The app wakes up, fetches pings / alerts / chats through the normal API and
shows the notification itself, so the push never needs to carry full content.

Setup (server):
    pip install firebase-admin            (in requirements.txt)
    FIREBASE_CREDENTIALS=/srv/backend/firebase-key.json   (service-account JSON, keep out of git)

If the env var / file / package is missing, every call is a silent no-op, so
the rest of the ERP keeps working exactly as before.
"""
import os
import threading
import logging

from flask import current_app

log = logging.getLogger(__name__)

_app = None
_init_lock = threading.Lock()
_disabled = False


def _firebase():
    """Lazy-initialise firebase_admin once. Returns the messaging module or None."""
    global _app, _disabled
    if _disabled:
        return None
    if _app is not None:
        from firebase_admin import messaging
        return messaging
    with _init_lock:
        if _app is None and not _disabled:
            path = os.getenv("FIREBASE_CREDENTIALS")
            if not path or not os.path.isfile(path):
                _disabled = True
                log.info("FCM push disabled (FIREBASE_CREDENTIALS not set or file missing)")
                return None
            try:
                import firebase_admin
                from firebase_admin import credentials
                # httpTimeout (seconds): without it a stuck request waits forever
                _app = firebase_admin.initialize_app(credentials.Certificate(path), {"httpTimeout": 10})
            except Exception as e:  # package missing / bad key
                _disabled = True
                log.warning("FCM push disabled: %s", e)
                return None
    from firebase_admin import messaging
    return messaging


# ── Device tokens ────────────────────────────────────────────────────────────

def register_device(user_id: int, token: str, platform: str = None) -> None:
    from app.extensions import db
    from app.models.communication_models import CommDeviceToken

    token = (token or "").strip()
    if not token:
        return
    row = CommDeviceToken.query.filter_by(token=token).first()
    if row:
        row.user_id = user_id            # same phone, different login
        row.platform = platform or row.platform
    else:
        db.session.add(CommDeviceToken(user_id=user_id, token=token, platform=platform))
    db.session.commit()


def remove_device(user_id: int, token: str) -> None:
    from app.extensions import db
    from app.models.communication_models import CommDeviceToken

    CommDeviceToken.query.filter_by(user_id=user_id, token=(token or "").strip()).delete()
    db.session.commit()


# ── Sending ──────────────────────────────────────────────────────────────────

def notify_users(user_ids, title: str, body: str = "", kind: str = "comm") -> None:
    """Fire-and-forget push to every device of these users (background thread)."""
    ids = sorted({int(u) for u in (user_ids or []) if u})
    if not ids or _disabled:
        return
    try:
        app = current_app._get_current_object()
    except RuntimeError:
        return
    from app.utils.background import run_in_background
    run_in_background(_send, app, ids, title or "", body or "", kind)


def _send(app, user_ids, title, body, kind):
    with app.app_context():
        messaging = _firebase()
        if messaging is None:
            return
        from app.extensions import db
        from app.models.communication_models import CommDeviceToken

        try:
            rows = CommDeviceToken.query.filter(CommDeviceToken.user_id.in_(user_ids)).all()
            tokens = [r.token for r in rows]
            if not tokens:
                return
            msg = messaging.MulticastMessage(
                tokens=tokens,
                data={"type": kind, "title": title[:200], "body": body[:500]},
                # A call is only worth ringing for a minute; other pushes keep an hour.
                android=messaging.AndroidConfig(priority="high", ttl=60 if kind == "incoming_call" else 3600),
            )
            from app.utils.resilience import breaker
            with breaker("firebase").protect():
                resp = messaging.send_each_for_multicast(msg)

            # drop tokens Firebase says are dead (app uninstalled, logged out, …)
            dead = []
            for tok, r in zip(tokens, resp.responses):
                if not r.success and type(r.exception).__name__ in (
                    "UnregisteredError", "SenderIdMismatchError", "InvalidArgumentError"
                ):
                    dead.append(tok)
            if dead:
                CommDeviceToken.query.filter(CommDeviceToken.token.in_(dead)).delete(synchronize_session=False)
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            log.warning("FCM push failed: %s", e)
        finally:
            db.session.remove()
