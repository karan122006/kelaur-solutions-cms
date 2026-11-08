"""Small input helpers shared by every process, so bad input gives a clear 4xx message instead of a crash."""
from datetime import date, datetime

from .db import one


class Invalid(Exception):
    """Raised for bad input; app.py turns it into a 422 (or 404) JSON response."""
    def __init__(self, message, status=422, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields


def to_int(v, name="Quantity", lo=None, hi=None):
    try:
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError
        f = float(v)
        if f != int(f):
            raise ValueError
        n = int(f)
    except (TypeError, ValueError, OverflowError):
        raise Invalid(f"{name} must be a whole number.")
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        raise Invalid(f"{name} must be between {lo} and {hi}." if hi is not None else f"{name} must be at least {lo}.")
    return n


def to_money(v, name="Amount"):
    try:
        if isinstance(v, bool) or isinstance(v, (list, dict)) or v is None:
            raise ValueError
        return round(float(v), 2)
    except (TypeError, ValueError):
        raise Invalid(f"{name} must be a number.")


def to_date(v, name="Date"):
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except (TypeError, ValueError):
        raise Invalid(f"{name} must be a valid date (YYYY-MM-DD).")


def to_time(v, name="Time"):
    try:
        return datetime.strptime(str(v), "%H:%M").strftime("%H:%M")
    except (TypeError, ValueError):
        raise Invalid(f"{name} must be a time like 09:00.")


def text(v):
    return v.strip() if isinstance(v, str) else ""


def must_exist(table, col, value, label, status=404):
    row = one(f"SELECT * FROM {table} WHERE {col}=?", value) if isinstance(value, str) else None
    if not row:
        raise Invalid(f"{label} not found.", status)
    return row
