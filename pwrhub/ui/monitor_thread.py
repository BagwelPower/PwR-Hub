"""İzleme motorunu arka planda çalıştıran iş parçacığı.

Oyun açık değilken 5 saniyede bir yalnızca "oyun başladı mı" diye bakar;
oyun açıkken 3 saniyede bir performans örneği kaydeder.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from pwrhub.db import Database
from pwrhub.monitor import MonitorEngine

log = logging.getLogger(__name__)


class MonitorThread(QThread):
    sessionStarted = Signal(int)        # oyun kimliği
    sessionEnded = Signal(int, int)     # oyun kimliği, oturum kimliği (kaydedilmediyse -1)

    def __init__(self, db_path: Path, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._stop = threading.Event()
        self._reload = threading.Event()

    def request_reload(self) -> None:
        """Kütüphane değişti; bir sonraki turda oyun listesi yenilensin."""
        self._reload.set()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        db = Database(self._db_path)   # bu iş parçacığına özel bağlantı
        try:
            engine = MonitorEngine(db)
            while not self._stop.is_set():
                try:
                    if self._reload.is_set():
                        self._reload.clear()
                        engine.reload_games()
                    for event in engine.tick():
                        if event.kind == "started":
                            self.sessionStarted.emit(event.game_id)
                        else:
                            self.sessionEnded.emit(event.game_id, event.session_id or -1)
                except Exception:   # tek bir hatalı ölçüm izlemeyi durdurmasın
                    log.exception("İzleme turu başarısız")
                self._stop.wait(engine.interval)
            engine.shutdown()
        finally:
            db.close()
