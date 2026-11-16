"""Uygulamanın giriş noktası."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from pwrhub import config
from pwrhub.db import Database
from pwrhub.ui import style
from pwrhub.ui.icon import app_icon
from pwrhub.ui.main_window import MainWindow


def _setup_logging() -> None:
    """Günlüğü veri klasöründeki pwrhub.log dosyasına yazar.

    Tek dosyalık .exe'nin konsol penceresi olmadığı için sorunları (ör. ekran
    kartının neden ölçülemediğini) görmenin yolu bu dosyadır. Dosya 500 KB'ı
    geçince eskisi pwrhub.log.1 olarak saklanır; yalnızca yerelde durur.
    """
    handlers: list[logging.Handler] = []
    try:
        handlers.append(RotatingFileHandler(
            config.data_dir() / "pwrhub.log", maxBytes=500_000, backupCount=1, encoding="utf-8"))
    except OSError:
        pass   # dosyaya yazılamıyorsa günlük tutulmaz; uygulama yine çalışır
    if sys.stderr is not None:
        # Konsolun dili Türkçe karakterleri desteklemiyorsa (ör. İngilizce
        # Windows) günlük yazarken hata çıkmasın; yazılamayan harf "?" olur.
        try:
            sys.stderr.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Beklenmeyen hatalar da günlüğe düşsün.
    sys.excepthook = lambda kind, value, trace: logging.getLogger("pwrhub").critical(
        "Beklenmeyen hata", exc_info=(kind, value, trace))


def main() -> int:
    _setup_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("PwR Hub")
    app.setStyle("Fusion")  # her Windows sürümünde aynı görünüm
    app.setStyleSheet(style.STYLESHEET)
    app.setWindowIcon(app_icon())
    # Pencere tepsiye küçülünce uygulama kapanmasın; çıkışı pencere kendisi yönetir.
    app.setQuitOnLastWindowClosed(False)

    # Aynı anda tek kopya çalışsın: iki kopya aynı oturumu iki kez kaydederdi.
    lock = QLockFile(str(config.data_dir() / "pwrhub.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(
            None, "PwR Hub zaten çalışıyor",
            "PwR Hub arka planda açık. Saatin yanındaki bildirim alanındaki "
            "simgesine tıklayarak pencereyi açabilirsin.",
        )
        return 0

    db_path = config.db_path()
    db = Database(db_path)
    window = MainWindow(db, db_path)
    # Windows açılışında "--minimized" ile başlar: pencere açılmaz, tepside bekler.
    if not ("--minimized" in sys.argv and window.has_tray):
        window.show()
    if "--selftest" in sys.argv:
        # Paketin (ör. .exe) açılıp düzgün kapanabildiğini sınamak için:
        # birkaç saniye çalışıp kendiliğinden çıkar.
        QTimer.singleShot(4000, window.quit)
    try:
        return app.exec()
    finally:
        # Pencereyi Qt uygulamasından ÖNCE yok et. Sıra Python'a bırakılırsa
        # kapanışta (resimler, simgeler serbest bırakılırken) çökme olabiliyor.
        window.deleteLater()
        app.processEvents()
        del window
        db.close()
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
