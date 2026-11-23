"""Jalali calendar tests (DEC-06 / DEC-07 parity with the reference engine)."""

from __future__ import annotations

from app.core.jalali import (
    calendar_info,
    gregorian_to_jalali,
    iso_from_jalali,
    jalali_from_iso,
    jalali_label,
    jalali_month_end_iso,
    jalali_month_start_iso,
    jalali_to_gregorian,
    week_start_iso,
)


def test_nowruz_boundaries() -> None:
    # 1403-01-01 == 2024-03-20 ; 1404-01-01 == 2025-03-21
    assert jalali_from_iso("2024-03-20") == (1403, 1, 1)
    assert iso_from_jalali(1403, 1, 1) == "2024-03-20"
    assert jalali_from_iso("2025-03-21") == (1404, 1, 1)


def test_gregorian_jalali_roundtrip() -> None:
    for iso in ("2024-01-01", "2024-12-31", "2025-07-15", "2026-11-23"):
        j = jalali_from_iso(iso)
        assert j is not None
        assert iso_from_jalali(*j) == iso


def test_reverse_roundtrip() -> None:
    gy, gm, gd = jalali_to_gregorian(1402, 12, 29)
    assert gregorian_to_jalali(gy, gm, gd) == (1402, 12, 29)


def test_jalali_month_boundaries() -> None:
    assert jalali_month_start_iso("2024-04-10") == "2024-03-20"
    assert jalali_month_end_iso("2024-04-10") == "2024-04-19"  # Farvardin = 31 days


def test_week_starts_on_saturday() -> None:
    # 2026-11-21 is a Saturday; 2026-11-23 is a Monday (same Iranian week)
    assert week_start_iso("2026-11-23") == "2026-11-21"
    assert week_start_iso("2026-11-21") == "2026-11-21"
    assert week_start_iso("2026-11-20") == "2026-11-14"


def test_labels() -> None:
    assert jalali_label("2024-03-20", "day") == "01/01"
    assert jalali_label("2024-03-20", "month") == "1403-01"


def test_calendar_info_shape() -> None:
    info = calendar_info("2026-11-23")
    assert info["today"] == "2026-11-23"
    assert info["week_start"] == "2026-11-21"
    assert info["month_start"] <= info["today"] <= info["month_end"]
    assert info["jalali"]["year"] >= 1400
    assert info["month_label"].startswith("14")
    assert info["week_label"] == "شنبه‌محور"


def test_invalid_input_is_tolerated() -> None:
    assert jalali_from_iso("") is None
    assert jalali_month_start_iso("not-a-date") == ""
    assert week_start_iso("") == ""
