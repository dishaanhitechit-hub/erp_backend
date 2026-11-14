# app/utils/resilience.py
"""
Circuit breakers for outside services (WhatsApp, e-mail, Firebase push,
Anthropic AI, Groq search parser).

Why: when an outside service is down, every call waits for its timeout
(10–30 s). With a few workers that quickly ties up the whole backend, and
pages that have nothing to do with that service stop answering. A breaker
notices repeated failures and, for a short while, fails those calls at once
instead of waiting — the rest of the ERP keeps working.

    from app.utils.resilience import breaker, ServiceUnavailableError

    with breaker("whatsapp").protect():
        resp = requests.post(url, ..., timeout=10)
        if resp.status_code >= 500:
            breaker("whatsapp").record_failure(f"HTTP {resp.status_code}")

States (per service, per worker process):
    closed     normal; failures are counted
    open       after FAILURE_THRESHOLD failures in a row: calls fail at once
               with ServiceUnavailableError for RESET_SECONDS
    half-open  after that, ONE trial call is let through: success closes the
               breaker, failure opens it again

ServiceUnavailableError is an HTTP 503, so a request that hits an open
breaker gets {"message": "... is temporarily unavailable", "data": []}
with status 503 from the global error handler. Fire-and-forget senders
already catch every exception, so for them the message is just logged as
failed — exactly what happens today when the service is down, only faster.

Tuning (environment, all services): BREAKER_FAILURES (default 5),
BREAKER_RESET_SECONDS (default 60).
"""

import logging
import os
import threading
import time
from contextlib import contextmanager

from werkzeug.exceptions import ServiceUnavailable

log = logging.getLogger(__name__)

FAILURE_THRESHOLD = max(1, int(os.getenv("BREAKER_FAILURES") or 5))
RESET_SECONDS = max(1, int(os.getenv("BREAKER_RESET_SECONDS") or 60))

LABELS = {
    "whatsapp": "WhatsApp messaging",
    "email": "E-mail",
    "firebase": "Push notifications",
    "anthropic": "The AI service",
    "groq": "The AI search parser",
}


class ServiceUnavailableError(ServiceUnavailable):
    """Raised instead of calling a service whose breaker is open (HTTP 503)."""

    def __init__(self, service):
        self.service = service
        super().__init__(f"{LABELS.get(service, service)} is temporarily unavailable. Please try again in a minute.")


class CircuitBreaker:
    def __init__(self, name, failure_threshold=FAILURE_THRESHOLD, reset_seconds=RESET_SECONDS):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._lock = threading.Lock()
        self._state = "closed"
        self._failures = 0            # in a row
        self._opened_at = None
        self._trial_running = False
        self.total_calls = 0
        self.total_failures = 0
        self.total_rejected = 0
        self.last_error = None
        self.last_error_at = None
        self.last_success_at = None

    # ── state ────────────────────────────────────────────────────
    @property
    def state(self):
        with self._lock:
            return self._current_state()

    def _current_state(self):
        if self._state == "open" and time.monotonic() - self._opened_at >= self.reset_seconds:
            self._state = "half-open"
            self._trial_running = False
        return self._state

    def allow(self):
        """True if a call may go ahead now."""
        with self._lock:
            state = self._current_state()
            if state == "closed":
                return True
            if state == "half-open" and not self._trial_running:
                self._trial_running = True  # exactly one trial call
                return True
            self.total_rejected += 1
            return False

    def record_success(self):
        with self._lock:
            if self._state != "closed":
                log.info("Circuit %s closed again — service is answering", self.name)
            self._state = "closed"
            self._failures = 0
            self._trial_running = False
            self.last_success_at = time.time()

    def record_failure(self, error=None):
        with self._lock:
            self.total_failures += 1
            self._failures += 1
            self.last_error = (str(error) if error else "failure")[:300]
            self.last_error_at = time.time()
            if self._state == "half-open" or self._failures >= self.failure_threshold:
                if self._state != "open":
                    log.warning(
                        "Circuit %s OPEN for %ss after %s failure(s) in a row: %s",
                        self.name, self.reset_seconds, self._failures, self.last_error,
                    )
                self._state = "open"
                self._opened_at = time.monotonic()
                self._trial_running = False

    # ── use ──────────────────────────────────────────────────────
    @contextmanager
    def protect(self):
        """
        Run the block if allowed. An exception inside counts as a failure and
        is re-raised. Raises ServiceUnavailableError when the breaker is open.
        A block that ends normally counts as a success unless it called
        record_failure() itself.
        """
        if not self.allow():
            raise ServiceUnavailableError(self.name)
        self.total_calls += 1
        failures_before = self.total_failures
        try:
            yield self
        except Exception as exc:
            if self.total_failures == failures_before:
                self.record_failure(f"{type(exc).__name__}: {exc}")
            raise
        else:
            if self.total_failures == failures_before:
                self.record_success()

    def snapshot(self):
        with self._lock:
            state = self._current_state()
            retry_in = None
            if state == "open":
                retry_in = max(0, round(self.reset_seconds - (time.monotonic() - self._opened_at)))
        return {
            "service": self.name,
            "label": LABELS.get(self.name, self.name),
            "state": state,
            "failuresInARow": self._failures,
            "retryInSeconds": retry_in,
            "calls": self.total_calls,
            "failures": self.total_failures,
            "rejectedWhileOpen": self.total_rejected,
            "lastError": self.last_error,
            "lastErrorAt": self.last_error_at,
            "lastSuccessAt": self.last_success_at,
        }


_breakers = {}
_registry_lock = threading.Lock()


def breaker(name):
    """The breaker for this service (created on first use)."""
    b = _breakers.get(name)
    if b is None:
        with _registry_lock:
            b = _breakers.setdefault(name, CircuitBreaker(name))
    return b


def all_breakers():
    for name in LABELS:
        breaker(name)
    return [b.snapshot() for b in _breakers.values()]
