"""Oturum takibi: oyun ne zaman açıldı, ne zaman kapandı.

Bu sınıf yalnızca "şu an hangi oyunlar çalışıyor" bilgisini alır; süreçleri
kendisi okumaz. Bu sayede zaman ve süreçler testlerde kolayca taklit edilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from pwrhub.db import Database

# Oyun kısa süre kaybolup geri gelirse (başlatıcıdan asıl oyuna geçiş, yeniden
# başlatma) aynı oturum sayılır.
GRACE = timedelta(seconds=30)
# Bundan kısa oturumlar (yanlışlıkla açıp kapatma) kaydedilmez.
MIN_SESSION = timedelta(seconds=20)
# PwR Hub yeniden açıldığında oyun hâlâ çalışıyorsa son oturuma devam edilir.
RESUME_WINDOW = timedelta(seconds=90)
# Oyun açıkken oturumun bitiş zamanı diske bu aralıkla yazılır (her turda değil).
# PwR Hub beklenmedik kapanırsa en fazla bu kadar süre kaybolur.
SAVE_EVERY = timedelta(seconds=15)


@dataclass
class SessionEvent:
    kind: str                # "started" ya da "ended"
    game_id: int
    session_id: int | None   # çok kısa olduğu için silinen oturumlarda None


@dataclass
class _Active:
    session_id: int
    started_at: datetime
    last_seen: datetime
    saved_at: datetime      # bitiş zamanının diske en son yazıldığı an


class SessionTracker:
    def __init__(self, db: Database):
        self._db = db
        self._active: dict[int, _Active] = {}

    @property
    def active(self) -> dict[int, int]:
        """Şu an süren oturumlar: oyun kimliği -> oturum kimliği."""
        return {game_id: item.session_id for game_id, item in self._active.items()}

    def update(self, running: set[int], now: datetime) -> list[SessionEvent]:
        """Çalışan oyun listesine göre oturumları başlatır, uzatır, bitirir."""
        events: list[SessionEvent] = []

        for game_id in running:
            item = self._active.get(game_id)
            if item is None:
                item = self._start(game_id, now)
                events.append(SessionEvent("started", game_id, item.session_id))
            item.last_seen = now
            if now - item.saved_at >= SAVE_EVERY:
                self._db.touch_session(item.session_id, now)
                item.saved_at = now

        for game_id, item in list(self._active.items()):
            if game_id not in running and now - item.last_seen > GRACE:
                events.append(self._finish(game_id, item))
        return events

    def close_all(self) -> list[SessionEvent]:
        """Uygulama kapanırken süren oturumları son görüldükleri anda bitirir."""
        return [self._finish(game_id, item) for game_id, item in list(self._active.items())]

    def _start(self, game_id: int, now: datetime) -> _Active:
        last = self._db.last_session(game_id)
        if last is not None and timedelta(0) <= now - last.ended_at <= RESUME_WINDOW:
            item = _Active(last.id, last.started_at, now, last.ended_at)  # kaldığı yerden devam
        else:
            item = _Active(self._db.start_session(game_id, now), now, now, now)
        self._active[game_id] = item
        return item

    def _finish(self, game_id: int, item: _Active) -> SessionEvent:
        del self._active[game_id]
        if item.last_seen - item.started_at < MIN_SESSION:
            self._db.delete_session(item.session_id)
            return SessionEvent("ended", game_id, None)
        # Kesin bitiş zamanını yaz (aradaki yazmalar seyrek yapılıyordu).
        self._db.touch_session(item.session_id, item.last_seen)
        return SessionEvent("ended", game_id, item.session_id)
