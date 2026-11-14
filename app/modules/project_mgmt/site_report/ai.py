"""AI for the Daily Progress Report.

read_photo(jpeg)          → what is in one site photo (structured)
write_report(day_input)   → the day's report (structured)

Provider is chosen with AI_PROVIDER in the server's .env:
  claude (default)  — Claude API (needs ANTHROPIC_API_KEY)
  local             — a model on this server (not built yet; photos stay "skipped")
  off               — no AI; photos are kept, report is written by hand

Models (Claude): DPR_VISION_MODEL (default claude-haiku-5-5) reads photos,
DPR_REPORT_MODEL (default claude-sonnet-5-5) writes the report.
"""

import base64
import json
import logging
import os

logger = logging.getLogger(__name__)


class AiUnavailable(RuntimeError):
    """AI is switched off or not configured — not an error in the photo."""


class AiFailed(RuntimeError):
    """The AI call itself failed (network, refusal, bad output)."""


def provider():
    return (os.getenv("AI_PROVIDER") or "claude").strip().lower()


def vision_model():
    return os.getenv("DPR_VISION_MODEL") or "claude-haiku-5-5"


def report_model():
    return os.getenv("DPR_REPORT_MODEL") or "claude-sonnet-5-5"


# ── Schemas (structured output: the reply is always valid JSON of this shape) ──

PHOTO_SCHEMA = {
    "type": "object",
    "properties": {
        "is_site_photo": {"type": "boolean"},
        "activity": {"type": "string"},
        "stage": {"type": "string"},
        "workers_visible": {"type": "integer"},
        "machinery": {"type": "array", "items": {"type": "string"}},
        "materials": {"type": "array", "items": {"type": "string"}},
        "safety_issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["issue", "severity"],
                "additionalProperties": False,
            },
        },
        "weather": {"type": "string"},
        "notes": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": [
        "is_site_photo", "activity", "stage", "workers_visible", "machinery",
        "materials", "safety_issues", "weather", "notes", "confidence",
    ],
    "additionalProperties": False,
}

PHOTO_SYSTEM = """You review photos from Indian construction sites (buildings, roads, bridges, \
industrial works) for a site engineer's daily progress report.

For the photo, report only what is actually visible:
- activity: the work happening, in a short phrase (e.g. "Slab shuttering", "Brickwork on 2nd floor", \
"Excavation for footing"). Use "No work visible" if nothing is being done.
- stage: the construction stage it belongs to (e.g. "Foundation", "Superstructure", "Finishing", \
"Earthwork", "Road base course"). Empty if unclear.
- workers_visible: people you can count in the photo (0 if none). Count only clearly visible people.
- machinery: equipment seen (e.g. "Excavator", "Transit mixer", "Tower crane", "Concrete vibrator").
- materials: materials seen (e.g. "TMT bars", "Cement bags", "Bricks", "Ready-mix concrete").
- safety_issues: real hazards seen, each with severity. high = could cause serious injury now \
(work at height without harness or edge protection, open excavation without barricade near people, \
person under a suspended load). medium = missing PPE such as helmets or shoes, poor housekeeping \
that could trip people, unsafe ladder. low = minor. Empty list if none seen; never invent issues.
- weather: what the sky/ground shows (e.g. "Sunny", "Overcast", "Rain, waterlogged"). Empty if indoors.
- notes: one sentence a project manager would find useful (progress, quality concern, or what is \
pending). Keep it factual.
- confidence: how sure you are overall.
- is_site_photo: false if the photo is not of a construction site (a document, a selfie, a blank \
or blurred image) — then keep the other fields empty or zero.

If the user gives a caption or location, use it as context but do not contradict the photo."""

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "work_done": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "area": {"type": "string"},
                    "description": {"type": "string"},
                    "photo_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["area", "description", "photo_ids"],
                "additionalProperties": False,
            },
        },
        "manpower": {
            "type": "object",
            "properties": {
                "total": {"type": "integer"},
                "by_category": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"category": {"type": "string"}, "count": {"type": "integer"}},
                        "required": ["category", "count"],
                        "additionalProperties": False,
                    },
                },
                "note": {"type": "string"},
            },
            "required": ["total", "by_category", "note"],
            "additionalProperties": False,
        },
        "machinery": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "note": {"type": "string"}},
                "required": ["name", "note"],
                "additionalProperties": False,
            },
        },
        "materials": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"item": {"type": "string"}, "quantity": {"type": "string"}, "note": {"type": "string"}},
                "required": ["item", "quantity", "note"],
                "additionalProperties": False,
            },
        },
        "issues": {"type": "array", "items": {"type": "string"}},
        "safety": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "photo_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["issue", "severity", "photo_ids"],
                "additionalProperties": False,
            },
        },
        "weather": {"type": "string"},
        "highlight_photo_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": [
        "summary", "work_done", "manpower", "machinery", "materials",
        "issues", "safety", "weather", "highlight_photo_ids",
    ],
    "additionalProperties": False,
}

REPORT_SYSTEM = """You write the Daily Progress Report (DPR) for an Indian construction project, \
for the project manager and the company owner.

You get, as JSON, everything recorded on site for one day: what the AI saw in each site photo \
(with photo id, time, location on site and who took it) and the site records entered in the ERP \
(daily labour report, concrete pours, materials received, machinery log entries, hindrances).

Write the report from that data only:
- summary: 2-3 plain sentences — the main work done, anything that needs the reader's attention \
(delays, hindrances, high-severity safety issues). No greetings.
- work_done: one entry per area or activity, merging photos that show the same work. description \
says what was done and its visible state. photo_ids lists the photos that show it.
- manpower: prefer the daily labour report figures; if there is none, estimate from photos and say \
so in note ("Estimated from photos — no labour report entered").
- machinery: from log entries and photos.
- materials: materials received (from GRNs) with quantity; materials only seen in photos can be \
listed with quantity "-".
- issues: hindrances and other problems, one line each.
- safety: issues seen in photos, merged when the same issue repeats, keeping the highest severity.
- weather: one short phrase, or empty if unknown.
- highlight_photo_ids: up to 6 photos that best show the day's progress.

Never invent work, numbers or problems that are not in the data. If the data is thin, keep the \
report short. Use plain English that a site engineer would use; Indian units (cum, MT, bags, rft) \
as given."""


def _client():
    if provider() == "off":
        raise AiUnavailable("AI is switched off (AI_PROVIDER=off)")
    if provider() == "local":
        raise AiUnavailable("Local AI is not set up yet (AI_PROVIDER=local)")
    if provider() != "claude":
        raise AiUnavailable(f"Unknown AI_PROVIDER: {provider()}")
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise AiUnavailable("ANTHROPIC_API_KEY is not set on the server")
    from app.modules.ai.client import get_client

    return get_client()


def _structured_call(model, system, content, schema, max_tokens, effort):
    """One Messages call whose reply is JSON matching `schema`."""
    import anthropic
    from app.modules.ai.client import call_with_breaker
    from app.utils.resilience import ServiceUnavailableError

    # photo reading / report writing may take longer than a chat answer
    client = _client().with_options(timeout=float(os.getenv("DPR_AI_TIMEOUT_SECONDS") or 90))
    try:
        msg = call_with_breaker(lambda: client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            # output_config isn't a named argument in the SDK version pinned here, so send it raw.
            extra_body={"output_config": {"format": {"type": "json_schema", "schema": schema}, "effort": effort}},
        ))
    except ServiceUnavailableError as e:
        raise AiFailed("AI service is temporarily unavailable — will retry") from e
    except anthropic.RateLimitError as e:
        raise AiFailed(f"AI is busy (rate limit) — will retry: {e}") from e
    except anthropic.APIStatusError as e:
        raise AiFailed(f"AI error {e.status_code}: {getattr(e, 'message', e)}") from e
    except anthropic.APIConnectionError as e:
        raise AiFailed(f"Could not reach the AI service: {e}") from e

    if msg.stop_reason == "refusal":
        raise AiFailed("The AI declined to read this photo")
    if msg.stop_reason == "max_tokens":
        raise AiFailed("The AI reply was cut off")
    text = next((b.text for b in msg.content if getattr(b, "type", "") == "text"), "")
    try:
        return json.loads(text)
    except (TypeError, ValueError) as e:
        raise AiFailed("The AI reply was not valid JSON") from e


def read_photo(jpeg: bytes, context: dict):
    """What is in one site photo. `context`: caption, sub_location, taken_at (all optional)."""
    hints = []
    if context.get("caption"):
        hints.append(f"Caption from the engineer: {context['caption']}")
    if context.get("sub_location"):
        hints.append(f"Location on site: {context['sub_location']}")
    if context.get("taken_at"):
        hints.append(f"Taken at: {context['taken_at']}")
    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode()},
        },
        {"type": "text", "text": "\n".join(hints) or "Review this site photo."},
    ]
    return _structured_call(vision_model(), PHOTO_SYSTEM, content, PHOTO_SCHEMA, max_tokens=4000, effort="low")


def write_report(day_input: dict):
    """The day's report from photos + site records (see service.build_day_input)."""
    content = [{"type": "text", "text": json.dumps(day_input, ensure_ascii=False, default=str)}]
    return _structured_call(report_model(), REPORT_SYSTEM, content, REPORT_SCHEMA, max_tokens=16000, effort="medium")
