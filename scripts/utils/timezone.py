"""
Central timezone handling for RB48.
The official timezone for RB48 (Cologne, Germany) is Europe/Berlin (GMT+1 in CET / GMT+2 in CEST).
"""
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo
from typing import Union

COLOGNE_TZ = ZoneInfo("Europe/Berlin")


def get_cologne_now() -> datetime:
    """Return the current datetime in Cologne timezone (Europe/Berlin)."""
    return datetime.now(COLOGNE_TZ)


def get_cologne_date() -> date:
    """Return today's date in Cologne timezone."""
    return get_cologne_now().date()


def get_cologne_date_str(fmt: str = "%Y-%m-%d") -> str:
    """Return today's date formatted as string in Cologne timezone (default: YYYY-MM-DD)."""
    return get_cologne_now().strftime(fmt)


def get_cologne_time_str(fmt: str = "%H:%M:%S") -> str:
    """Return the current time formatted as string in Cologne timezone (default: HH:MM:SS)."""
    return get_cologne_now().strftime(fmt)


def get_cologne_timestamp_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Return current timestamp formatted as string in Cologne timezone."""
    return get_cologne_now().strftime(fmt)


def get_cologne_file_timestamp(fmt: str = "%Y%m%d_%H%M%S") -> str:
    """Return current timestamp suitable for filenames (e.g. 20261004_183000)."""
    return get_cologne_now().strftime(fmt)


def to_cologne_datetime(dt: Union[datetime, str, None]) -> datetime | None:
    """
    Convert a datetime or ISO string to Cologne timezone (Europe/Berlin).
    If dt is a string, it parses ISO format.
    If dt has no tzinfo (naive), it assumes UTC (the default server timezone).
    """
    if dt is None:
        return None

    if isinstance(dt, str):
        try:
            # Handle ISO string with or without Z / offset
            clean_str = dt.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(clean_str)
            return to_cologne_datetime(parsed)
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(COLOGNE_TZ)


def format_cologne_datetime(dt: Union[datetime, str, None], fmt: str = "%d.%m.%Y %H:%M") -> str:
    """
    Format a datetime or ISO string as a human-readable Cologne time string.
    Returns empty string if dt cannot be parsed.
    """
    col_dt = to_cologne_datetime(dt)
    if col_dt is None:
        return ""
    return col_dt.strftime(fmt)
