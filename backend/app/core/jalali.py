"""Jalali (Shamsi) calendar helpers — internal implementation (TDR-010).

Ported from the proven ``jalaali-js`` algorithm used by the reference
implementation (``Server_01_Utils.gs``), so reports and filters keep exactly
the same boundaries: Asia/Tehran days, Saturday-based weeks and Jalali months
(DEC-06 / DEC-07).

No third-party dependency is used.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Final

_BREAKS: Final[tuple[int, ...]] = (
    -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097,
    2192, 2262, 2324, 2394, 2456, 3178,
)

_MAX_BUCKETS: Final = 420


def _div(a: int, b: int) -> int:
    return int(a / b)


def _mod(a: int, b: int) -> int:
    return a - _div(a, b) * b


def _jal_cal(jy: int) -> dict[str, int]:
    bl = len(_BREAKS)
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    if jy < jp or jy >= _BREAKS[bl - 1]:
        raise ValueError(f"invalid Jalali year: {jy}")
    for i in range(1, bl):
        jm = _BREAKS[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j = leap_j + _div(jump, 33) * 8 + _div(_mod(jump, 33), 4)
        jp = jm
    n = jy - jp
    leap_j = leap_j + _div(n, 33) * 8 + _div(_mod(n, 33) + 3, 4)
    if _mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = _mod(_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return {"leap": leap, "gy": gy, "march": march}


def _g2d(gy: int, gm: int, gd: int) -> int:
    d = _div((gy + _div(gm - 8, 6) + 100100) * 1461, 4) + _div(153 * _mod(gm + 9, 12) + 2, 5) + gd - 34840408
    return d - _div(_div(gy + 100100 + _div(gm - 8, 6), 100) * 3, 4) + 752


def _d2g(jdn: int) -> tuple[int, int, int]:
    j = 4 * jdn + 139361631
    j = j + _div(_div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = _div(_mod(j, 1461), 4) * 5 + 308
    gd = _div(_mod(i, 153), 5) + 1
    gm = _mod(_div(i, 153), 12) + 1
    gy = _div(j, 1461) - 100100 + _div(8 - gm, 6)
    return gy, gm, gd


def _j2d(jy: int, jm: int, jd: int) -> int:
    r = _jal_cal(jy)
    return _g2d(r["gy"], 3, r["march"]) + (jm - 1) * 31 - _div(jm, 7) * (jm - 7) + jd - 1


def _d2j(jdn: int) -> tuple[int, int, int]:
    gy = _d2g(jdn)[0]
    jy = gy - 621
    r = _jal_cal(jy)
    jdn1f = _g2d(gy, 3, r["march"])
    k = jdn - jdn1f
    if k >= 0:
        if k <= 185:
            return jy, 1 + _div(k, 31), _mod(k, 31) + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if r["leap"] == 1:
            k += 1
    return jy, 7 + _div(k, 30), _mod(k, 30) + 1


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    return _d2j(_g2d(gy, gm, gd))


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    return _d2g(_j2d(jy, jm, jd))


def parse_iso(value: str | date) -> date | None:
    """Parse a ``YYYY-MM-DD`` string (or accept a date) into a ``date``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def iso_from_jalali(jy: int, jm: int, jd: int) -> str:
    gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
    return f"{gy:04d}-{gm:02d}-{gd:02d}"


def jalali_from_iso(value: str | date) -> tuple[int, int, int] | None:
    parsed = parse_iso(value)
    if parsed is None:
        return None
    return gregorian_to_jalali(parsed.year, parsed.month, parsed.day)


def jalali_month_start_iso(value: str | date) -> str:
    j = jalali_from_iso(value)
    if j is None:
        return ""
    return iso_from_jalali(j[0], j[1], 1)


def jalali_month_end_iso(value: str | date) -> str:
    j = jalali_from_iso(value)
    if j is None:
        return ""
    next_y, next_m = (j[0] + 1, 1) if j[1] == 12 else (j[0], j[1] + 1)
    start = date.fromisoformat(iso_from_jalali(next_y, next_m, 1))
    return (start - timedelta(days=1)).isoformat()


def jalali_label(value: str | date, granularity: str = "day") -> str:
    j = jalali_from_iso(value)
    if j is None:
        return str(value or "")
    jy, jm, jd = j
    if granularity == "month":
        return f"{jy}-{jm:02d}"
    return f"{jm:02d}/{jd:02d}"


def week_start_iso(value: str | date) -> str:
    """Saturday-based week start (DEC-07)."""
    parsed = parse_iso(value)
    if parsed is None:
        return ""
    # Python: Monday=0 ... Saturday=5 -> offset to Saturday
    offset = (parsed.weekday() - 5) % 7
    return (parsed - timedelta(days=offset)).isoformat()


def calendar_info(today: str | date | None = None) -> dict[str, object]:
    parsed = parse_iso(today) if today else date.today()
    if parsed is None:
        parsed = date.today()
    iso = parsed.isoformat()
    j = jalali_from_iso(iso)
    return {
        "today": iso,
        "week_start": week_start_iso(iso),
        "month_start": jalali_month_start_iso(iso),
        "month_end": jalali_month_end_iso(iso),
        "jalali": {"year": j[0], "month": j[1], "day": j[2]} if j else None,
        "jalali_label": jalali_label(iso, "day"),
        "week_label": "شنبه‌محور",
        "month_label": f"{j[0]}-{j[1]:02d}" if j else "",
    }
