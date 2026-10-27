from datetime import datetime, date
import calendar


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
