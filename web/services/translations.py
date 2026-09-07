# -*- coding: utf-8 -*-
"""RB48 localization service."""

from datetime import datetime
from flask import has_request_context, session
from markupsafe import Markup

from web.translations.de import TRANSLATIONS_DE
from web.translations.en import TRANSLATIONS_EN

TRANSLATIONS = {
    "de": TRANSLATIONS_DE,
    "en": TRANSLATIONS_EN,
}

GERMAN_WEEKDAYS = {
    0: "Montag",
    1: "Dienstag",
    2: "Mittwoch",
    3: "Donnerstag",
    4: "Freitag",
    5: "Samstag",
    6: "Sonntag",
}

ENGLISH_WEEKDAYS = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}

GERMAN_MONTHS = {
    1: "Januar",
    2: "Februar",
    3: "März",
    4: "April",
    5: "Mai",
    6: "Juni",
    7: "Juli",
    8: "August",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Dezember",
}

ENGLISH_MONTHS = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}


def get_current_lang():
    """Return the active language code for the current session, default 'de'."""
    if has_request_context():
        return session.get("lang", "de")
    return "de"


def set_current_lang(lang):
    """Set the active language in the session if valid."""
    if lang in ("de", "en") and has_request_context():
        session["lang"] = lang


def t(key, default=None, **kwargs):
    """Lookup translation for key in active language catalog with formatting support.

    Returns Markup string so embedded safe HTML is not double-escaped by Jinja.
    """
    lang = kwargs.pop("lang", None)
    if lang is None:
        lang = get_current_lang()
    catalog = TRANSLATIONS.get(lang, TRANSLATIONS_DE)

    text = catalog.get(key)
    if text is None:
        # If key not in catalog, check fallback
        if lang == "en" and default is not None:
            text = default
        elif lang == "de":
            text = default if default is not None else key
        else:
            text = default if default is not None else key

    if kwargs and text is not None:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass

    return Markup(text) if text is not None else ""


def format_date_localized(dt_or_str, lang=None):
    """Format a datetime or ISO date string into a localized date representation."""
    if lang is None:
        lang = get_current_lang()

    if isinstance(dt_or_str, str):
        try:
            if "T" in dt_or_str:
                dt = datetime.fromisoformat(dt_or_str)
            elif len(dt_or_str) >= 10:
                dt = datetime.strptime(dt_or_str[:10], "%Y-%m-%d")
            else:
                return dt_or_str
        except Exception:
            return dt_or_str
    elif isinstance(dt_or_str, datetime):
        dt = dt_or_str
    else:
        return str(dt_or_str)

    weekday_map = GERMAN_WEEKDAYS if lang == "de" else ENGLISH_WEEKDAYS
    weekday_name = weekday_map.get(dt.weekday(), dt.strftime("%A"))
    return f"{weekday_name}, {dt.strftime('%d.%m.%Y')}"


def format_month_localized(month_or_dt, lang=None):
    """Return localized month name by month number 1-12, datetime, or date string."""
    if lang is None:
        lang = get_current_lang()
    months = GERMAN_MONTHS if lang == "de" else ENGLISH_MONTHS

    if isinstance(month_or_dt, int):
        return months.get(month_or_dt, "")
    if isinstance(month_or_dt, str):
        try:
            if "-" in month_or_dt:
                parts = month_or_dt.split("-")
                m = int(parts[1])
                year = parts[0]
                return f"{months.get(m, '')} {year}"
            return months.get(int(month_or_dt), "")
        except Exception:
            return month_or_dt
    if isinstance(month_or_dt, datetime):
        return f"{months.get(month_or_dt.month, '')} {month_or_dt.year}"
    return str(month_or_dt)
