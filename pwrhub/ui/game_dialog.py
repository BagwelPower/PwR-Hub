"""Oyun ayrıntı penceresi: oynanma özeti, oturum listesi ve performans raporu."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pwrhub import report, stats
from pwrhub.db import Database
from pwrhub.models import Game, Session
from pwrhub.ui import style
from pwrhub.ui.charts import LineChart
from pwrhub.ui.widgets import Card, StatTile, tile_row

_TABLE_ROWS = report.RESOURCES                        # tablodaki satırlar
_CHART_LINES = ("cpu", "mem", "disk", "gpu")          # grafikteki çizgiler


class ReportPanel(Card):
    """Seçilen oturumun performans raporu: not, yorumlar, tablo ve grafik."""

    def __init__(self, parent=None):
        super().__init__("Performans raporu", parent)

        # Zorlanma notu ve etiketi
        head = QHBoxLayout()
        head.setSpacing(14)
        self._score = QLabel()
        self._score.setObjectName("score")
        self._level = QLabel()
        self._level.setTextFormat(Qt.TextFormat.RichText)
        head.addWidget(self._score)
        head.addWidget(self._level, 1)
        self.body.addLayout(head)

        # Sade dilde yorumlar
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setTextFormat(Qt.TextFormat.RichText)
        self.body.addWidget(self._text)

        # Ortalama / en yüksek tablosu
        self._table = QWidget()
        grid = QGridLayout(self._table)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(6)
        for column, title in enumerate(("Kaynak", "Ortalama", "En yüksek", "Oyunun payı (ort.)")):
            label = QLabel(title)
            label.setObjectName("tableHead")
            grid.addWidget(label, 0, column)
        self._cells: dict[tuple[str, int], QLabel] = {}
        self._row_widgets: dict[str, list[QLabel]] = {}
        for row, resource in enumerate(_TABLE_ROWS, start=1):
            # Grafikte çizgisi olan kaynakların yanında çizgi rengi gösterilir.
            color = style.SERIES.get(resource)
            swatch = f"<span style='color:{color}'>■</span> " if color else "&nbsp;&nbsp;&nbsp;&nbsp;"
            name = QLabel(swatch + style.SERIES_LABELS[resource])
            name.setTextFormat(Qt.TextFormat.RichText)
            grid.addWidget(name, row, 0)
            self._row_widgets[resource] = [name]
            for column in (1, 2, 3):
                cell = QLabel()
                self._cells[(resource, column)] = cell
                self._row_widgets[resource].append(cell)
                grid.addWidget(cell, row, column)
        grid.setColumnStretch(4, 1)
        self.body.addWidget(self._table)

        self._chart = LineChart()
        self.body.addWidget(self._chart, 1)

    def show_session(self, db: Database, game: Game, session: Session | None) -> None:
        samples = db.list_samples(session.id) if session else []
        result = report.analyze(samples, game.name)
        has_report = result is not None
        self._table.setVisible(has_report)
        self._chart.setVisible(has_report)
        self._score.setVisible(has_report)
        self._level.setVisible(has_report)

        if result is None:
            self._text.setText(
                "<span style='color:%s'>%s</span>" % (
                    style.TEXT_MUTED,
                    "Bu oturum için performans kaydı yok." if session
                    else "Bu oyun henüz oynanmadı. İlk oturumdan sonra rapor burada görünecek.",
                )
            )
            return

        color = style.STATUS[result.level]
        self._score.setText(f"{result.score}<span style='font-size:15px; color:{style.TEXT_MUTED}'> / 100</span>")
        self._level.setText(
            f"<span style='color:{color}; font-size:16px'>●</span> "
            f"<b style='font-size:16px'>{result.label}</b><br>"
            f"<span style='color:{style.TEXT_MUTED}'>Zorlanma notu: 0 rahat, 100 sürekli sınırda</span>"
        )
        self._text.setText("<br>".join(result.lines))

        for resource in report.OPTIONAL:
            for widget in self._row_widgets[resource]:
                widget.setVisible(resource in result.available)   # ölçülemeyen satır gizlenir
        for resource in _TABLE_ROWS:
            self._cells[(resource, 1)].setText(report.format_value(resource, result.average[resource]))
            self._cells[(resource, 2)].setText(report.format_value(resource, result.peak[resource]))
            share = result.game_average.get(resource)
            self._cells[(resource, 3)].setText("-" if share is None else f"%{round(share)}")

        worst = result.worst
        self._chart.set_data(
            [s.ts for s in samples],
            [(style.SERIES_LABELS[r], style.SERIES[r], [report.value_of(s, r) for s in samples])
             for r in _CHART_LINES if r != "gpu" or result.has_gpu],
            marker=worst.ts if worst else None,
            marker_text="En zor an",
        )


class GameDialog(QDialog):
    def __init__(self, db: Database, game: Game, session_id: int | None = None, parent=None):
        super().__init__(parent)
        self._db = db
        self._game = game
        self._sessions = db.list_sessions(game.id)
        self.setWindowTitle(game.name)
        self.resize(980, 860)   # ekrana sığmazsa rapor kaydırılır

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(14)

        title = QLabel(game.name)
        title.setObjectName("title")
        layout.addWidget(title)

        # Oynanma özeti
        count = len(self._sessions)
        total = sum(s.duration_s for s in self._sessions)
        tiles = [StatTile("Toplam süre"), StatTile("Son oynanma"),
                 StatTile("Oturum sayısı"), StatTile("Ortalama oturum")]
        tiles[0].set_value(stats.format_duration(total))
        tiles[1].set_value(stats.format_date(self._sessions[0].ended_at) if count else "Hiç")
        tiles[2].set_value(str(count))
        tiles[3].set_value(stats.format_duration(total / count) if count else "-")
        layout.addWidget(tile_row(tiles))

        # Solda oturumlar, sağda seçilen oturumun raporu
        body = QHBoxLayout()
        body.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(8)
        heading = QLabel("Oturumlar")
        heading.setObjectName("cardTitle")
        left.addWidget(heading)
        self._list = QListWidget()
        self._list.setFixedWidth(250)
        for session in self._sessions:
            self._list.addItem(QListWidgetItem(self._session_text(session)))
        self._list.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self._list, 1)
        body.addLayout(left)

        # Rapor uzun olabildiği için küçük ekranlarda kaydırılabilir.
        self._report = ReportPanel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._report)
        body.addWidget(scroll, 1)
        layout.addLayout(body, 1)

        # İstenen oturumu (yoksa en yenisini) seç
        row = next((i for i, s in enumerate(self._sessions) if s.id == session_id), 0)
        if self._sessions:
            self._list.setCurrentRow(row)
        else:
            self._report.show_session(db, game, None)

    @staticmethod
    def _session_text(session: Session) -> str:
        when = stats.format_date(session.started_at)
        if ":" not in when:   # eski tarihlerde saat de görünsün
            when += f" {session.started_at:%H:%M}"
        line = f"{when}  ·  {stats.format_duration(session.duration_s)}"
        if session.strain_score is None:
            return f"{line}\nPerformans kaydı yok"
        label, _level = report.score_level(session.strain_score)
        return f"{line}\nZorlanma {session.strain_score} · {label}"

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._sessions):
            self._report.show_session(self._db, self._game, self._sessions[row])
