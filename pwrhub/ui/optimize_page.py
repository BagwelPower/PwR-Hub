"""Optimizasyon sayfası: anlık kaynak kullanımı, arka plan programları, Oyun Modu."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pwrhub import boost, optimizer
from pwrhub.db import Database
from pwrhub.matching import GameMatcher
from pwrhub.procscan import ProcessScanner, SystemReader
from pwrhub.ui.widgets import Card, StatTile, tile_row

_REFRESH_MS = 3000
_GB = 1024 ** 3
_MB = 1024 ** 2


def _format_bytes(count: int) -> str:
    return f"{count / _GB:.1f} GB" if count >= _GB else f"{count / _MB:.0f} MB"


class OptimizePage(QScrollArea):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self._db = db
        # Ölçüm araçları sayfa ilk kez açıldığında kurulur; sayfayı hiç açmayan
        # kullanıcı için bellek ve açılış süresi harcanmaz.
        self._scanner: ProcessScanner | None = None
        self._system: SystemReader | None = None
        self._matcher = GameMatcher([])
        self._programs: list[optimizer.ProgramUsage] = []
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(14)

        # Şu anki kullanım
        self._cpu = StatTile("İşlemci")
        self._mem = StatTile("Bellek")
        self._disk = StatTile("Disk")
        self._gpu = StatTile("Ekran kartı")
        self._vram = StatTile("Ekran kartı belleği")
        self._temp = StatTile("Ekran kartı sıcaklığı")
        layout.addWidget(tile_row([self._cpu, self._mem, self._disk]))
        layout.addWidget(tile_row([self._gpu, self._vram, self._temp]))

        # Arka plan programları
        programs = Card("Arka planda en çok kaynak kullanan programlar")
        hint = QLabel(
            "Oynamadan önce kullanmadığın programları kapatmak işlemciyi ve belleği oyuna bırakır. "
            "Windows'un kendi programları kapatılamaz."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        programs.body.addWidget(hint)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(24)
        self._grid.setVerticalSpacing(8)
        self._grid.setColumnStretch(0, 1)
        programs.body.addLayout(self._grid)
        layout.addWidget(programs)

        # Oyun Modu
        mode = Card("Oyun Modu")
        info = QLabel(
            "Bir oyun açıldığında kendiliğinden devreye girer, oyun kapanınca yapılan her şeyi "
            "geri alır. Oyun dosyalarına, oyun ayarlarına ve ekran kartı ayarlarına dokunmaz."
        )
        info.setObjectName("muted")
        info.setWordWrap(True)
        mode.body.addWidget(info)
        self._enabled = self._checkbox(mode, boost.KEY_ENABLED, False,
                                       "Oyun açılınca Oyun Modu'nu kendiliğinden uygula")
        self._options = [
            self._checkbox(mode, boost.KEY_GAME_PRIORITY, True,
                           "Oyuna işlemci önceliği ver", indent=True),
            self._checkbox(mode, boost.KEY_BACKGROUND, True,
                           "Tarayıcı ve dosya eşitleme programlarının önceliğini düşür "
                           "(kapatılmazlar)", indent=True),
            self._checkbox(mode, boost.KEY_POWER_PLAN, True,
                           "Windows güç planını \"Yüksek performans\" yap", indent=True),
        ]
        self._enabled.toggled.connect(self._sync_options)
        self._sync_options(self._enabled.isChecked())
        layout.addWidget(mode)
        layout.addStretch(1)
        self.setWidget(content)

        # Sayfa yalnızca görünürken ölçüm yapar.
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self.refresh)

    def _checkbox(self, card: Card, key: str, default: bool, text: str, indent: bool = False) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(self._db.get_flag(key, default))
        box.toggled.connect(lambda checked, k=key: self._db.set_flag(k, checked))
        if indent:
            box.setStyleSheet("margin-left: 26px;")
        card.body.addWidget(box)
        return box

    def _sync_options(self, enabled: bool) -> None:
        for box in self._options:
            box.setEnabled(enabled)

    # ----------------------------------------------------------- canlı ölçüm

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._scanner is None:
            self._scanner = ProcessScanner()
            self._system = SystemReader()
        self._matcher = GameMatcher(self._db.list_games(include_hidden=True))
        self._scanner.scan(detailed=True)   # işlemci ölçümü için başlangıç noktası
        self._system.read()
        self._show_programs([])
        QTimer.singleShot(700, self.refresh)
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        if self._scanner is None or not self.isVisible():
            return
        procs = self._scanner.scan(detailed=True)
        usage = self._system.read()
        self._cpu.set_value(f"%{round(usage.cpu)}")
        self._mem.set_value(f"%{round(usage.mem)}")
        self._disk.set_value(f"%{round(usage.disk)}")
        self._gpu.set_value("Ölçülemiyor" if usage.gpu is None else f"%{round(usage.gpu)}")
        if usage.gpu_mem is None:
            self._vram.set_value("Ölçülemiyor")
        else:
            self._vram.set_value(
                f"%{round(usage.gpu_mem)}  ·  {usage.gpu_mem_used / _GB:.1f} / "
                f"{usage.gpu_mem_total / _GB:.0f} GB"
            )
        self._temp.set_value("Ölçülemiyor" if usage.gpu_temp is None
                             else f"{round(usage.gpu_temp)}°C")

        game_pids = {p.pid for items in self._matcher.match(procs).values() for p in items}
        self._show_programs(optimizer.top_programs(procs, usage.mem_total, game_pids))

    def _show_programs(self, programs: list[optimizer.ProgramUsage]) -> None:
        self._programs = programs
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Hemen gizle ve ayır; yoksa silinene kadar eski satırlar görünür kalır.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        for column, title in enumerate(("Program", "İşlemci", "Bellek", "")):
            label = QLabel(title)
            label.setObjectName("tableHead")
            self._grid.addWidget(label, 0, column)
        if not programs:
            waiting = QLabel("Ölçülüyor…")
            waiting.setObjectName("muted")
            self._grid.addWidget(waiting, 1, 0)
            return
        for row, program in enumerate(programs, start=1):
            self._grid.addWidget(QLabel(program.title), row, 0)
            self._grid.addWidget(QLabel(f"%{round(program.cpu)}"), row, 1)
            self._grid.addWidget(
                QLabel(f"{_format_bytes(program.mem_bytes)}  (%{round(program.mem)})"), row, 2)
            if program.closable:
                button = QPushButton("Kapat")
                button.clicked.connect(lambda _checked, p=program: self._close(p))
                self._grid.addWidget(button, row, 3)
            else:
                system = QLabel("Sistem programı")
                system.setObjectName("muted")
                self._grid.addWidget(system, row, 3)

    def _close(self, program: optimizer.ProgramUsage) -> None:
        answer = QMessageBox.question(
            self, "Program kapatılsın mı?",
            f"{program.title} kapatılacak.\n\n"
            "Bu programda kaydetmediğin bir çalışma varsa kaybolur. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        _closed, failed = optimizer.close_program(program)
        if failed:
            QMessageBox.information(
                self, "Tamamen kapatılamadı",
                f"{program.title} programının bazı parçaları kapatılamadı. "
                "Programı kendi penceresinden kapatmayı deneyebilirsin.",
            )
        self.refresh()
