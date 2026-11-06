from datetime import datetime, date, time
import calendar

def parse_date(value, field_name="date"):
    """Parse and validate a date value before writing to the DB.

    Rules:
      - None / empty string → returns None (safe for optional fields)
      - date/datetime object → validates year is 4 digits, returns as-is
      - string → must match YYYY-MM-DD strictly with a 4-digit year and be
        a real calendar date (e.g. 2024-02-30 is rejected)

    Raises ValueError with a clear message so callers can return a 400
    before any corrupt value reaches the database.
    """
    if value is None or value == "":
        return None

    if isinstance(value, (date, datetime)):
        if not (1000 <= value.year <= 9999):
            raise ValueError(
                f"{field_name}: year must be 4 digits (got {value.year})"
            )
        return value

    raw = str(value).strip()
    # Enforce strict YYYY-MM-DD format — rejects partial strings like "62026-1-1"
    import re as _re
    if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValueError(
            f"{field_name}: '{raw}' is not a valid date — expected YYYY-MM-DD"
        )
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(
            f"{field_name}: '{raw}' is not a real calendar date (e.g. month/day out of range)"
        )
    if parsed.year < 1000:
        raise ValueError(
            f"{field_name}: year must be 4 digits (got {parsed.year})"
        )
    return parsed


def parse_datetime(value, field_name="datetime"):
    """Parse a date/datetime string from the frontend into a datetime object.

    Accepts: None/empty → None; datetime object → as-is; strings in any of
    these formats: YYYY-MM-DD HH:MM:SS, YYYY-MM-DD HH:MM, YYYY-MM-DDTHH:MM:SS,
    YYYY-MM-DDTHH:MM, YYYY-MM-DD (treated as midnight).
    Raises ValueError with a clear message on unrecognised input.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"{field_name}: '{raw}' is not a recognised datetime — "
        "expected YYYY-MM-DD or YYYY-MM-DD HH:MM"
    )


def parse_time(value, field_name="time"):
    """Parse and validate a time value before writing to the DB.

    Accepts: None/empty → None; time object → as-is; strings HH:MM or HH:MM:SS.
    Raises ValueError with a clear message on invalid input.
    """
    if value is None or value == "":
        return None

    if isinstance(value, time):
        return value

    import re as _re
    raw = str(value).strip()
    if not _re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", raw):
        raise ValueError(
            f"{field_name}: '{raw}' is not a valid time — expected HH:MM or HH:MM:SS"
        )
    fmt = "%H:%M:%S" if len(raw) == 8 else "%H:%M"
    try:
        return datetime.strptime(raw, fmt).time()
    except ValueError:
        raise ValueError(
            f"{field_name}: '{raw}' is not a valid time (hours 0-23, minutes 0-59)"
        )


def last_month_range() -> tuple[datetime, datetime]:
    """Return (start, end) datetime for the previous calendar month (UTC-midnight boundaries)."""
    today = date.today()
    first_this_month = today.replace(day=1)
    last_day_prev    = first_this_month.replace(day=1) - __import__("datetime").timedelta(days=1)
    first_day_prev   = last_day_prev.replace(day=1)

    start = datetime(first_day_prev.year, first_day_prev.month, 1, 0, 0, 0)
    end   = datetime(
        last_day_prev.year,
        last_day_prev.month,
        calendar.monthrange(last_day_prev.year, last_day_prev.month)[1],
        23, 59, 59,
    )
    return start, end


def month_label(start: datetime) -> str:
    return start.strftime("%B %Y")


def period_label(start: datetime, end: datetime) -> str:
    return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
