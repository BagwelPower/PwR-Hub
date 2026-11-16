"""Arayüz duman testleri (ekransız çalışır)."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from pwrhub import launcher  # noqa: E402
from pwrhub.db import Database  # noqa: E402
from pwrhub.models import SOURCE_STEAM, Game  # noqa: E402
from pwrhub.ui.game_grid import GAME_ROLE, fold  # noqa: E402
from pwrhub.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("PWRHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("pwrhub.scanners.steam.find_steam_root", lambda: None)
    monkeypatch.setattr("pwrhub.scanners.epic.find_manifests_dir", lambda: None)
    # Tarama gerçek sistemi karıştırmasın; testte kütüphaneyi elle dolduruyoruz.
    monkeypatch.setattr(MainWindow, "start_scan", lambda self: None)
    monkeypatch.setattr(MainWindow, "start_monitor", lambda self: None)
    monkeypatch.setattr(MainWindow, "setup_tray", lambda self: None)
    db_path = tmp_path / "ui.db"
    db = Database(db_path)
    db.sync_source(SOURCE_STEAM, [
        Game(source=SOURCE_STEAM, source_id=str(i), name=name, launch_uri=f"steam://rungameid/{i}")
        for i, name in enumerate(["Hades", "Celeste", "IŞIK Oyunu", "Portal 2", "Portal 10"])
    ])
    win = MainWindow(db, db_path)
    win.show()
    app.processEvents()
    yield win
    # Pencereyi Qt tarafında da hemen yok et; yoksa pencereler program
    # kapanışına kadar yaşar ve Qt kapanırken sorun çıkarabilir.
    win.close()
    win.deleteLater()
    app.processEvents()
    db.close()


def names(win):
    proxy = win._proxy
    return [proxy.index(r, 0).data(GAME_ROLE).name for r in range(proxy.rowCount())]


def test_fold_handles_turkish_letters():
    assert fold("IŞIK") == fold("ışık") == "işik"


def test_grid_lists_sorts_and_searches(window):
    assert names(window) == ["Celeste", "Hades", "IŞIK Oyunu", "Portal 2", "Portal 10"]

    window._sort.setCurrentIndex(window._sort.findData("name_desc"))
    assert names(window)[0] == "Portal 10"

    window._search.setText("ışık")
    assert names(window) == ["IŞIK Oyunu"]

    window._search.setText("böyle bir oyun yok")
    assert window._stack.currentIndex() == 1  # "eşleşen oyun yok" ekranı


def test_click_launches_once(window, monkeypatch):
    launched = []
    monkeypatch.setattr(launcher, "launch", lambda game: launched.append(game.name))
    game = window._proxy.index(0, 0).data(GAME_ROLE)
    window._grid.clicked.emit(window._proxy.index(0, 0))
    window._grid.clicked.emit(window._proxy.index(0, 0))  # ikinci tıklama yok sayılır
    assert launched == ["Celeste"]
    assert window._db.get_game(game.id).last_launched_at

    QApplication.processEvents()
    window._sort.setCurrentIndex(window._sort.findData("recent"))
    assert names(window)[0] == "Celeste"


def test_hide_and_show_hidden(window):
    game = window._proxy.index(0, 0).data(GAME_ROLE)
    window._set_hidden(game, True)
    assert "Celeste" not in names(window)
    window._toggle_show_hidden(True)
    assert "Celeste" in names(window)


# ---------------------------------------------------- 2. ve 3. aşama ekranları

from datetime import datetime, timedelta  # noqa: E402

from pwrhub.models import Sample  # noqa: E402
from pwrhub.ui.game_dialog import GameDialog  # noqa: E402


def add_session(db, game_id, minutes, with_samples=False):
    start = datetime.now().replace(microsecond=0) - timedelta(minutes=minutes + 5)
    session_id = db.start_session(game_id, start)
    db.touch_session(session_id, start + timedelta(minutes=minutes))
    if with_samples:
        for i in range(60):
            db.add_sample(session_id, Sample(start + timedelta(seconds=3 * i), cpu=40, mem=96, disk=5,
                                             game_mem=20, top_mem_name="chrome.exe", top_mem=50))
        db.set_session_score(session_id, 80)
    return session_id


def test_stats_page_shows_real_play_data(window):
    hades = next(g for g in window._db.list_games() if g.name == "Hades")
    add_session(window._db, hades.id, 90)
    add_session(window._db, hades.id, 30)
    window._show_page(1)

    page = window._stats
    assert page._total._value.text() == "2 sa"
    assert page._count._value.text() == "2"
    assert sum(bar.seconds for bar in page._chart._bars) == 7200
    assert [row[1] for row in page._top._rows] == ["Hades"]
    assert not window._library_tools.isVisible()

    # Kütüphane kartı ve "En çok oynanan" sıralaması da güncellenir.
    window._show_page(0)
    window.reload_games()
    window._sort.setCurrentIndex(window._sort.findData("most_played"))
    assert names(window)[0] == "Hades"


def test_game_dialog_shows_report(window):
    hades = next(g for g in window._db.list_games() if g.name == "Hades")
    plain = add_session(window._db, hades.id, 200)
    recorded = add_session(window._db, hades.id, 40, with_samples=True)

    dialog = GameDialog(window._db, window._db.get_game(hades.id), recorded)
    dialog.show()
    QApplication.processEvents()
    panel = dialog._report
    assert "80" in panel._score.text() and "Çok zorlandı" in panel._level.text()
    assert "Chrome (tarayıcı)" in panel._text.text()
    assert panel._cells[("mem", 2)].text() == "%96"
    assert panel._chart.isVisible() and len(panel._chart._times) == 60

    row = next(i for i, s in enumerate(dialog._sessions) if s.id == plain)
    dialog._list.setCurrentRow(row)
    assert "performans kaydı yok" in panel._text.text()
    assert not panel._chart.isVisible()
    dialog.close()


def test_session_events_update_library_and_open_report(window):
    hades = next(g for g in window._db.list_games() if g.name == "Hades")
    window._on_session_started(hades.id)
    assert window._running == {hades.id}

    session_id = add_session(window._db, hades.id, 40, with_samples=True)
    window._on_session_ended(hades.id, session_id)
    assert window._running == set()
    assert len(window._dialogs) == 1                       # rapor kendiliğinden açıldı
    assert "40 dk" in window._status.text()
    window._dialogs[0].close()
    QApplication.processEvents()
    assert window._dialogs == []

    window._on_session_ended(hades.id, -1)                 # kaydedilmeyen kısa oturum
    assert window._dialogs == []


def test_optimize_page_lists_programs_and_saves_game_mode(window, monkeypatch):
    from pwrhub import boost, optimizer

    window._show_page(2)
    page = window._optimize
    QApplication.processEvents()
    page.refresh()                                   # gerçek sistemden canlı ölçüm
    assert page._cpu._value.text().startswith("%")
    assert not window._library_tools.isVisible()

    # Oyun Modu ayarları veritabanına yazılır; alt seçenekler ana anahtara bağlıdır.
    assert not page._enabled.isChecked() and not page._options[0].isEnabled()
    page._enabled.setChecked(True)
    assert window._db.get_flag(boost.KEY_ENABLED) and page._options[0].isEnabled()
    page._options[2].setChecked(False)
    assert window._db.get_flag(boost.KEY_POWER_PLAN, True) is False

    # "Kapat" yalnızca kullanıcı onaylarsa çalışır.
    closed = []
    monkeypatch.setattr(optimizer, "close_program", lambda program: closed.append(program.name) or (1, 0))
    program = optimizer.ProgramUsage("chrome.exe", "Chrome (tarayıcı)", pids=[1])
    monkeypatch.setattr("pwrhub.ui.optimize_page.QMessageBox.question",
                        lambda *a, **k: QMessageBox.StandardButton.No)
    page._close(program)
    assert closed == []
    monkeypatch.setattr("pwrhub.ui.optimize_page.QMessageBox.question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    page._close(program)
    assert closed == ["chrome.exe"]
    window._show_page(0)


def test_logo_assets_load(window):
    from pwrhub.ui.icon import ASSETS, app_icon, logo_pixmap

    assert not window.windowIcon().isNull()
    assert len(app_icon().availableSizes()) == 10
    assert logo_pixmap(64).width() == 64 and logo_pixmap(100).width() == 100
    ico = (ASSETS / "pwrhub.ico").read_bytes()
    assert ico[:4] == b"\x00\x00\x01\x00" and ico[4] == 9      # geçerli .ico, 9 boyut
    for name in ("logo.svg", "logo-mark.svg"):
        text = (ASSETS / name).read_text(encoding="utf-8")
        assert "linearGradient" in text and "<text" not in text   # yazı tipi gerektirmez


def test_cover_cache_is_bounded(window):
    from pwrhub.ui.covers import CoverCache

    cache = CoverCache()
    cache.MAX_ITEMS = 3
    games = [Game(source=SOURCE_STEAM, source_id=str(i), name=f"Oyun {i}") for i in range(5)]
    for game in games[:3]:
        cache.get(game)
    cache.get(games[0])                  # 0 yeniden kullanıldı: en eski artık 1
    cache.get(games[3])
    kept = {key[1] for key in cache._cache}
    assert kept == {"0", "2", "3"} and len(cache._cache) == 3
