"""Ana pencere: üst çubuk ve üç sayfa (Kütüphane, İstatistikler, Optimizasyon).

Pencere kapatıldığında uygulama sistem tepsisinde çalışmaya devam eder;
böylece oyun oturumları pencere açık olmasa da kaydedilir."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pwrhub import autostart, config, launcher, report, stats
from pwrhub.db import Database
from pwrhub.library import refresh_library
from pwrhub.models import SOURCE_LABELS, Game
from pwrhub.ui.covers import CoverCache
from pwrhub.ui.game_dialog import GameDialog
from pwrhub.ui.game_grid import (
    GAME_ROLE,
    SORT_OPTIONS,
    GameCardDelegate,
    GameFilterProxy,
    GameGridView,
    GameListModel,
)
from pwrhub.ui.icon import app_icon, logo_pixmap
from pwrhub.ui.monitor_thread import MonitorThread
from pwrhub.ui.optimize_page import OptimizePage
from pwrhub.ui.stats_page import StatsPage

# Aynı oyuna art arda tıklanırsa ikinci kez başlatmamak için bekleme (saniye).
_LAUNCH_COOLDOWN = 4.0


class ScanThread(QThread):
    """Kütüphane taramasını arka planda yapar; arayüz donmaz."""

    done = Signal()

    def __init__(self, db_path: Path, parent=None):
        super().__init__(parent)
        self._db_path = db_path

    def run(self) -> None:
        # SQLite bağlantıları iş parçacığına özeldir; burada ayrı bağlantı açılır.
        db = Database(self._db_path)
        try:
            refresh_library(db)
        finally:
            db.close()
        self.done.emit()


class ManualPathsDialog(QDialog):
    """Kullanıcının eklediği klasör ve .exe'leri listeler, kaldırmasına izin verir."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self._db = db
        self.changed = False
        self.setWindowTitle("Eklenen klasörler ve oyunlar")
        self.resize(560, 360)

        layout = QVBoxLayout(self)
        info = QLabel("Buradan kaldırdığın yollardaki oyunlar kütüphaneden çıkar. Dosyaların silinmez.")
        info.setObjectName("muted")
        info.setWordWrap(True)
        layout.addWidget(info)

        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        remove = QPushButton("Seçileni kaldır")
        remove.clicked.connect(self._remove_selected)
        close = QPushButton("Kapat")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._reload()

    def _reload(self) -> None:
        self._list.clear()
        for path, _kind in self._db.list_manual_paths():
            self._list.addItem(path)

    def _remove_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self._db.remove_manual_path(item.text())
        self.changed = True
        self._reload()


class MainWindow(QMainWindow):
    def __init__(self, db: Database, db_path: Path):
        super().__init__()
        self._db = db
        self._db_path = db_path
        self._scan_thread: ScanThread | None = None
        self._rescan_requested = False
        self._last_launch: dict[int, float] = {}
        self._show_hidden = False
        self._monitor: MonitorThread | None = None
        self._running: set[int] = set()       # şu an açık olan oyunlar
        self._dialogs: list[GameDialog] = []  # açık ayrıntı pencereleri
        self._tray: QSystemTrayIcon | None = None
        self._quitting = False                # gerçekten çıkılıyor mu (tepsiye küçülmek yerine)
        self._pending_report: tuple[int, int] | None = None   # pencere gizliyken biten oturum
        self.setWindowIcon(app_icon())

        self.setWindowTitle("PwR Hub")
        self.resize(1180, 760)
        self.setMinimumSize(640, 480)

        self._covers = CoverCache()
        self._model = GameListModel(self)
        self._proxy = GameFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 10)
        layout.setSpacing(12)
        layout.addLayout(self._build_top_bar())

        # Izgara ile "boş kütüphane" ekranı arasında geçiş
        self._stack = QStackedWidget()
        self._grid = GameGridView()
        self._grid.setModel(self._proxy)
        self._grid.setItemDelegate(GameCardDelegate(self._covers, self._grid))
        self._grid.clicked.connect(self._on_game_clicked)       # tek tıkla başlat
        self._grid.activated.connect(self._on_game_clicked)     # Enter ile başlat
        self._grid.customContextMenuRequested.connect(self._show_context_menu)
        self._stack.addWidget(self._grid)
        self._stack.addWidget(self._build_empty_page())

        # Kütüphane ile İstatistikler sayfası arasında geçiş
        self._stats = StatsPage(self._db)
        self._stats.gameRequested.connect(self._open_game_by_id)
        self._pages = QStackedWidget()
        self._pages.addWidget(self._stack)
        self._pages.addWidget(self._stats)
        self._optimize = OptimizePage(self._db)
        self._pages.addWidget(self._optimize)
        layout.addWidget(self._pages, 1)

        self._status = QLabel()
        self._status.setObjectName("status")
        layout.addWidget(self._status)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._show_counts)

        QShortcut(QKeySequence.StandardKey.Find, self, activated=self._search.setFocus)
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=self.start_scan)

        # Önce veritabanındaki son bilinen kütüphaneyi göster, sonra arka planda tara.
        self.reload_games()
        self.start_scan()
        self.start_monitor()
        self.setup_tray()

    # ------------------------------------------------------------ arayüz kurulumu

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(logo_pixmap(64))
        logo.setScaledContents(True)
        logo.setFixedSize(32, 32)
        bar.addWidget(logo)
        title = QLabel("PwR Hub")
        title.setObjectName("title")
        bar.addWidget(title)
        bar.addSpacing(10)

        # Sayfa düğmeleri
        nav = QButtonGroup(self)
        for page, text in enumerate(("Kütüphane", "İstatistikler", "Optimizasyon")):
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setChecked(page == 0)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked, p=page: self._show_page(p))
            nav.addButton(button, page)
            bar.addWidget(button)
        self._nav = nav
        bar.addSpacing(10)

        # Yalnızca Kütüphane sayfasında görünen araçlar
        self._library_tools = QWidget()
        tools = QHBoxLayout(self._library_tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(10)
        outer = bar
        outer.addWidget(self._library_tools, 1)
        outer.addStretch(0)   # araçlar gizlenince düğmeler sola yaslı kalsın
        bar = tools

        self._search = QLineEdit()
        self._search.setPlaceholderText("Oyun ara…")
        self._search.setClearButtonEnabled(True)
        self._search.setMaximumWidth(380)
        self._search.textChanged.connect(self._on_search_changed)
        bar.addWidget(self._search, 1)
        bar.addStretch(1)

        self._sort = QComboBox()
        for key, label in SORT_OPTIONS:
            self._sort.addItem(label, key)
        self._sort.currentIndexChanged.connect(
            lambda _i: self._proxy.set_sort_key(self._sort.currentData())
        )
        bar.addWidget(self._sort)

        self._refresh_btn = QPushButton("Yenile")
        self._refresh_btn.setToolTip("Kütüphaneyi yeniden tara (F5)")
        self._refresh_btn.clicked.connect(self.start_scan)
        bar.addWidget(self._refresh_btn)

        add_btn = QToolButton()
        add_btn.setText("+ Oyun ekle")
        add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        add_menu = QMenu(add_btn)
        add_menu.addAction("Oyun klasörü ekle…", self._add_folder)
        add_menu.addAction("Tek bir oyun (.exe) ekle…", self._add_exe)
        add_menu.addSeparator()
        add_menu.addAction("Eklenenleri yönet…", self._manage_paths)
        add_btn.setMenu(add_menu)
        bar.addWidget(add_btn)

        more_btn = QToolButton()
        more_btn.setText("⋯")
        more_btn.setToolTip("Diğer seçenekler")
        more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(more_btn)
        hidden_action = QAction("Gizlenen oyunları göster", more_menu)
        hidden_action.setCheckable(True)
        hidden_action.toggled.connect(self._toggle_show_hidden)
        more_menu.addAction(hidden_action)
        more_menu.addSeparator()
        tray_action = QAction("Pencere kapatılınca arka planda çalışmaya devam et", more_menu)
        tray_action.setCheckable(True)
        tray_action.setChecked(self._db.get_flag("close_to_tray", True))
        tray_action.toggled.connect(lambda on: self._db.set_flag("close_to_tray", on))
        more_menu.addAction(tray_action)
        autostart_action = QAction("Windows açılınca PwR Hub'ı başlat", more_menu)
        autostart_action.setCheckable(True)
        autostart_action.setChecked(autostart.is_enabled())
        autostart_action.setEnabled(autostart.SUPPORTED)
        autostart_action.toggled.connect(self._set_autostart)
        more_menu.addAction(autostart_action)
        more_menu.addSeparator()
        more_menu.addAction("PwR Hub'dan çık", self.quit)
        more_btn.setMenu(more_menu)
        bar.addWidget(more_btn)
        return outer

    def _set_autostart(self, enabled: bool) -> None:
        if not autostart.set_enabled(enabled):
            QMessageBox.warning(self, "Ayar değiştirilemedi",
                                "Windows başlangıç ayarı kaydedilemedi.")

    # ------------------------------------------------------ sistem tepsisi

    def setup_tray(self) -> None:
        """Saatin yanındaki bildirim alanına PwR Hub simgesini ekler."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(app_icon(), self)
        self._tray.setToolTip("PwR Hub")
        menu = QMenu(self)
        menu.addAction("PwR Hub'ı göster", self.show_window)
        menu.addSeparator()
        menu.addAction("Çıkış", self.quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.messageClicked.connect(self.show_window)
        self._tray.show()

    @property
    def has_tray(self) -> bool:
        return self._tray is not None

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self) -> None:
        """Pencereyi öne getirir; gizliyken biten oturumun raporu varsa açar."""
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.reload_games()
        if self._pages.currentIndex() == 1:
            self._stats.refresh()
        if self._pending_report is not None:
            game_id, session_id = self._pending_report
            self._pending_report = None
            game = self._db.get_game(game_id)
            if game:
                self._open_game(game, session_id)

    def quit(self) -> None:
        """Uygulamadan gerçekten çıkar (tepsiye küçülmez)."""
        self._quitting = True
        self.close()

    def _show_page(self, page: int) -> None:
        self._pages.setCurrentIndex(page)
        self._nav.button(page).setChecked(True)
        self._library_tools.setVisible(page == 0)
        if page == 1:
            self._stats.refresh()

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        self._empty_title = QLabel()
        self._empty_title.setObjectName("emptyTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_text = QLabel()
        self._empty_text.setObjectName("muted")
        self._empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_text.setWordWrap(True)
        self._empty_add = QPushButton("Oyun klasörü ekle")
        self._empty_add.setObjectName("primary")
        self._empty_add.clicked.connect(self._add_folder)

        layout.addWidget(self._empty_title)
        layout.addWidget(self._empty_text)
        layout.addSpacing(8)
        layout.addWidget(self._empty_add, 0, Qt.AlignmentFlag.AlignCenter)
        return page

    # ------------------------------------------------------------------ veri

    def reload_games(self) -> None:
        """Oyunları veritabanından okuyup ızgarayı yeniler."""
        self._model.set_games(self._db.list_games(include_hidden=self._show_hidden))
        self._model.set_running(self._running)
        self._update_view_state()
        if not self._status_timer.isActive():
            self._show_counts()

    def start_scan(self) -> None:
        """Arka planda kütüphane taraması başlatır."""
        if self._scan_thread is not None:
            # Tarama sürerken yeni istek gelirse bitince bir kez daha tara.
            self._rescan_requested = True
            return
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Taranıyor…")
        self._scan_thread = ScanThread(self._db_path, self)
        self._scan_thread.done.connect(self._on_scan_done)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()
        self._update_view_state()

    def _on_scan_done(self) -> None:
        self._scan_thread = None
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("Yenile")
        self._covers.clear()
        self.reload_games()
        if self._monitor is not None:
            self._monitor.request_reload()   # yeni bulunan oyunlar da izlensin
        if self._rescan_requested:
            self._rescan_requested = False
            self.start_scan()

    # ------------------------------------------------- oturum takibi (izleme)

    def start_monitor(self) -> None:
        """Oyun oturumlarını ve performansı kaydeden arka plan izlemesini başlatır."""
        self._monitor = MonitorThread(self._db_path, self)
        self._monitor.sessionStarted.connect(self._on_session_started)
        self._monitor.sessionEnded.connect(self._on_session_ended)
        # Düşük öncelik: ölçüm, oyunun işlemci zamanını hiçbir zaman kapmasın.
        self._monitor.start(QThread.Priority.LowPriority)

    def _on_session_started(self, game_id: int) -> None:
        self._running.add(game_id)
        self._model.set_running(self._running)
        game = self._db.get_game(game_id)
        if game:
            self._flash_status(f"{game.name} oynanıyor; oturum ve performans kaydediliyor.", 8000)

    def _on_session_ended(self, game_id: int, session_id: int) -> None:
        self._running.discard(game_id)
        self.reload_games()
        if self._pages.currentIndex() == 1:
            self._stats.refresh()
        if session_id < 0:
            return   # çok kısa oturum, kaydedilmedi
        game = self._db.get_game(game_id)
        session = self._db.get_session(session_id)
        if game and session:
            length = stats.format_duration(session.duration_s)
            self._flash_status(f"{game.name} oturumu kaydedildi ({length}).", 8000)
            if self.isVisible():
                self._open_game(game, session_id)   # oyun bitince raporu göster
            else:
                # Pencere tepside: bildirim göster, rapor pencere açılınca gelsin.
                self._pending_report = (game_id, session_id)
                if self._tray is not None:
                    text = f"{length} oynadın."
                    if session.strain_score is not None:
                        label, _level = report.score_level(session.strain_score)
                        text += f" Zorlanma notu: {session.strain_score} ({label})."
                    self._tray.showMessage(f"{game.name} oturumu kaydedildi",
                                           text + " Raporu görmek için tıkla.")

    def _open_game_by_id(self, game_id: int) -> None:
        game = self._db.get_game(game_id)
        if game:
            self._open_game(game)

    def _open_game(self, game: Game, session_id: int | None = None) -> None:
        """Oyunun istatistik ve performans penceresini açar (ana pencereyi kilitlemez)."""
        dialog = GameDialog(self._db, game, session_id, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._dialogs.append(dialog)
        dialog.finished.connect(lambda _result, d=dialog: self._dialogs.remove(d))
        dialog.show()

    def _update_view_state(self) -> None:
        """Izgarayı mı yoksa açıklama ekranını mı göstereceğine karar verir."""
        if self._proxy.rowCount() > 0:
            self._stack.setCurrentIndex(0)
            return
        searching = bool(self._search.text().strip()) and self._model.rowCount() > 0
        if searching:
            self._empty_title.setText("Aramanla eşleşen oyun yok")
            self._empty_text.setText("Farklı bir ad yazmayı dene.")
        elif self._scan_thread is not None:
            self._empty_title.setText("Oyunların aranıyor…")
            self._empty_text.setText("Steam ve Epic Games kütüphanelerine bakılıyor.")
        else:
            self._empty_title.setText("Henüz oyun bulunamadı")
            self._empty_text.setText(
                "Steam ve Epic Games oyunları kendiliğinden bulunur.\n"
                "Başka bir yerdeki oyunların için oyun klasörünü ekleyebilirsin."
            )
        self._empty_add.setVisible(not searching and self._scan_thread is None)
        self._stack.setCurrentIndex(1)

    def _show_counts(self) -> None:
        games = [self._model.index(r).data(GAME_ROLE) for r in range(self._model.rowCount())]
        if not games:
            self._status.setText("")
            return
        parts = [f"{len(games)} oyun"]
        for source, label in SOURCE_LABELS.items():
            count = sum(1 for g in games if g.source == source)
            if count:
                parts.append(f"{label}: {count}")
        self._status.setText("  ·  ".join(parts))

    def _flash_status(self, text: str, msec: int = 4000) -> None:
        """Alt satırda kısa süreli bilgi mesajı gösterir."""
        self._status.setText(text)
        self._status_timer.start(msec)

    # ------------------------------------------------------------- olaylar

    def _on_search_changed(self, text: str) -> None:
        self._proxy.set_query(text)
        self._update_view_state()

    def _toggle_show_hidden(self, checked: bool) -> None:
        self._show_hidden = checked
        self.reload_games()

    def _on_game_clicked(self, index: QModelIndex) -> None:
        game: Game | None = index.data(GAME_ROLE)
        if game is not None:
            self._launch(game)

    def _launch(self, game: Game) -> None:
        now = time.monotonic()
        if now - self._last_launch.get(game.id, 0.0) < _LAUNCH_COOLDOWN:
            return  # çift tıklama / sabırsız tıklama: ikinci kez başlatma
        self._last_launch[game.id] = now
        try:
            launcher.launch(game)
        except launcher.LaunchError as exc:
            self._last_launch.pop(game.id, None)
            QMessageBox.warning(self, "Oyun başlatılamadı", str(exc))
            return
        game.last_launched_at = self._db.mark_launched(game.id)
        # "Son açılan" sıralaması güncellensin. Tıklama olayı bitmeden yeniden
        # sıralamak elimizdeki satır bilgisini geçersiz kılacağı için erteliyoruz.
        QTimer.singleShot(0, self._proxy.invalidate)
        self._flash_status(f"{game.name} başlatılıyor…")

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self._grid.indexAt(pos)
        game: Game | None = index.data(GAME_ROLE) if index.isValid() else None
        if game is None:
            return
        menu = QMenu(self)
        menu.addAction("Oyna", lambda: self._launch(game))
        menu.addAction("İstatistikler ve performans", lambda: self._open_game(game))
        menu.addAction("Oyun klasörünü aç", lambda: self._open_folder(game))
        menu.addSeparator()
        menu.addAction("Kapak resmi seç…", lambda: self._choose_cover(game))
        if game.custom_cover:
            menu.addAction("Seçilen kapağı kaldır", lambda: self._set_cover(game, ""))
        menu.addSeparator()
        if game.hidden:
            menu.addAction("Kütüphanede göster", lambda: self._set_hidden(game, False))
        else:
            menu.addAction("Kütüphaneden gizle", lambda: self._set_hidden(game, True))
        menu.exec(self._grid.viewport().mapToGlobal(pos))

    def _open_folder(self, game: Game) -> None:
        try:
            launcher.open_install_dir(game)
        except (launcher.LaunchError, OSError) as exc:
            QMessageBox.warning(self, "Klasör açılamadı", str(exc))

    def _set_hidden(self, game: Game, hidden: bool) -> None:
        self._db.set_hidden(game.id, hidden)
        self.reload_games()
        if hidden:
            self._flash_status(f"{game.name} gizlendi. Geri getirmek için ⋯ menüsünü kullan.")

    def _choose_cover(self, game: Game) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Kapak resmi seç", "", "Resimler (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not path:
            return
        # Resmi kendi veri klasörümüze kopyala; asıl dosya taşınsa da kapak kalır.
        target = config.covers_dir() / f"{game.id}_{int(time.time())}{Path(path).suffix.lower()}"
        try:
            shutil.copyfile(path, target)
        except OSError as exc:
            QMessageBox.warning(self, "Kapak ayarlanamadı", str(exc))
            return
        self._set_cover(game, str(target))

    def _set_cover(self, game: Game, path: str) -> None:
        old = game.custom_cover
        self._db.set_custom_cover(game.id, path)
        # Eski kopyayı temizle (yalnızca bizim kapak klasörümüzdeyse).
        if old and Path(old).parent == config.covers_dir():
            Path(old).unlink(missing_ok=True)
        self.reload_games()

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Oyun klasörünü seç")
        if path:
            self._db.add_manual_path(str(Path(path)), "folder")
            self._flash_status("Klasör eklendi, oyunlar aranıyor…")
            self.start_scan()

    def _add_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Oyunun .exe dosyasını seç", "", "Uygulamalar (*.exe);;Tüm dosyalar (*)"
        )
        if path:
            self._db.add_manual_path(str(Path(path)), "exe")
            self.start_scan()

    def _manage_paths(self) -> None:
        dialog = ManualPathsDialog(self._db, self)
        dialog.exec()
        if dialog.changed:
            self.start_scan()

    def closeEvent(self, event) -> None:
        # Pencere kapatılınca tepside çalışmaya devam et (oturumlar kaydedilsin).
        if (not self._quitting and self._tray is not None
                and self._db.get_flag("close_to_tray", True)):
            event.ignore()
            self.hide()
            # Pencere görünmezken kapak resimlerini bellekte tutmaya gerek yok.
            self._covers.clear()
            if not self._db.get_flag("tray_hint_shown"):
                self._db.set_flag("tray_hint_shown", True)
                self._tray.showMessage(
                    "PwR Hub arka planda çalışıyor",
                    "Oyun oturumların kaydedilmeye devam ediyor. Tamamen kapatmak için "
                    "bu simgeye sağ tıklayıp Çıkış'ı seç.",
                )
            return
        # Tarama sürüyorsa bitmesini bekle; yarım yazılmış kayıt kalmasın.
        if self._scan_thread is not None:
            self._scan_thread.wait(5000)
        # İzlemeyi durdur; süren oturum varsa son hâliyle kaydedilir.
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor.wait(5000)
            self._monitor = None
        if self._tray is not None:
            self._tray.hide()
        super().closeEvent(event)
        QApplication.quit()
