"""Oynanma istatistikleri: günlük/haftalık toplamlar ve süre biçimlendirme."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from pwrhub.models import Session

_DAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
_MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def format_duration(seconds: float) -> str:
    """Saniyeyi okunur süreye çevirir: 8100 -> '2 sa 15 dk'."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "1 dk'dan az" if seconds > 0 else "0 dk"
    hours, minutes = divmod(minutes, 60)
    if hours == 0:
        return f"{minutes} dk"
    return f"{hours} sa {minutes} dk" if minutes else f"{hours} sa"


def format_date(moment: datetime, today: date | None = None) -> str:
    """'Bugün 21:40', 'Dün 18:05' ya da '3 Kas 2026' biçiminde tarih."""
    today = today or date.today()
    if moment.date() == today:
        return f"Bugün {moment:%H:%M}"
    if moment.date() == today - timedelta(days=1):
        return f"Dün {moment:%H:%M}"
    text = f"{moment.day} {_MONTHS[moment.month - 1]}"
    return text if moment.year == today.year else f"{text} {moment.year}"


def seconds_per_day(sessions: list[Session]) -> dict[date, float]:
    """Her güne düşen oynama süresi. Gece yarısını aşan oturumlar günlere bölünür."""
    totals: dict[date, float] = {}
    for session in sessions:
        start, end = session.started_at, session.ended_at
        while start < end:
            midnight = datetime.combine(start.date() + timedelta(days=1), time.min)
            piece_end = min(end, midnight)
            totals[start.date()] = totals.get(start.date(), 0.0) + (piece_end - start).total_seconds()
            start = piece_end
    return totals


@dataclass
class Bar:
    label: str      # eksen etiketi (ör. "Pzt", "3 Kas")
    detail: str     # ipucu metni için uzun ad
    seconds: float


def daily_bars(sessions: list[Session], days: int = 14, today: date | None = None) -> list[Bar]:
    """Son `days` günün her biri için oynama süresi (eskiden yeniye)."""
    today = today or date.today()
    per_day = seconds_per_day(sessions)
    bars = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        long_name = f"{day.day} {_MONTHS[day.month - 1]} {_DAYS[day.weekday()]}"
        bars.append(Bar(_DAYS[day.weekday()], long_name, per_day.get(day, 0.0)))
    return bars


def weekly_bars(sessions: list[Session], weeks: int = 8, today: date | None = None) -> list[Bar]:
    """Son `weeks` haftanın (Pazartesi başlangıçlı) oynama süreleri."""
    today = today or date.today()
    per_day = seconds_per_day(sessions)
    this_monday = today - timedelta(days=today.weekday())
    bars = []
    for offset in range(weeks - 1, -1, -1):
        monday = this_monday - timedelta(weeks=offset)
        sunday = monday + timedelta(days=6)
        total = sum(per_day.get(monday + timedelta(days=i), 0.0) for i in range(7))
        label = f"{monday.day} {_MONTHS[monday.month - 1]}"
        detail = f"{label} - {sunday.day} {_MONTHS[sunday.month - 1]}"
        bars.append(Bar(label, detail, total))
    return bars


def total_between(sessions: list[Session], first: date, last: date) -> float:
    """İki gün arasında (ikisi de dahil) toplam oynama süresi, saniye."""
    per_day = seconds_per_day(sessions)
    return sum(seconds for day, seconds in per_day.items() if first <= day <= last)
