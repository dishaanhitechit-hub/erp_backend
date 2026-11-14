import os
import anthropic

from app.utils.resilience import breaker

_client = None

# The SDK default is a 10-minute timeout with 2 retries. A web request is
# killed by Gunicorn after 30 s anyway, so interactive calls get a short
# limit; background jobs (DPR) pass a longer one with with_options().
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT_SECONDS") or 25)
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES") or 1)


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            timeout=AI_TIMEOUT,
            max_retries=AI_MAX_RETRIES,
        )
    return _client


def _counts_as_outage(exc) -> bool:
    """Connection problems, timeouts, rate limits and 5xx — not bad requests."""
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.RateLimitError)):
        return True
    return isinstance(exc, anthropic.APIStatusError) and getattr(exc, "status_code", 0) >= 500


def call_with_breaker(fn):
    """
    Run fn() (a Messages call) through the AI circuit breaker. Raises
    ServiceUnavailableError (HTTP 503) at once while the AI service is down.
    """
    ai = breaker("anthropic")
    error = None
    with ai.protect():
        try:
            return fn()
        except Exception as exc:
            if _counts_as_outage(exc):
                raise  # counted as a failure by the breaker
            error = exc  # the service answered; the request itself was wrong
    raise error


def ask_claude(system_prompt: str, user_message: str, max_tokens: int = 1024) -> str:
    client = get_client()
    msg = call_with_breaker(lambda: client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    ))
    return msg.content[0].text
