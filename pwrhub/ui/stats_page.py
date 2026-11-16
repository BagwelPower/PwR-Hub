"""Genel istatistik sayfası: toplam süreler, günlük/haftalık grafik, en çok oynananlar."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from pwrhub import stats
from pwrhub.db import Database
from pwrhub.ui.charts import BarChart, HBarList
from pwrhub.ui.widgets import Card, StatTile, tile_row

_DAILY_DAYS = 14
_WEEKLY_WEEKS = 8


class StatsPage(QScrollArea):
    gameRequested = Signal(int)   # listeden bir oyuna tıklandı

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self._db = db
        self._weekly = False
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(14)

        # Öne çıkan sayılar
        self._total = StatTile("Toplam oynama süresi")
        self._week = StatTile("Bu hafta")
        self._today = StatTile("Bugün")
        self._count = StatTile("Oturum sayısı")
        layout.addWidget(tile_row([self._total, self._week, self._today, self._count]))

        # Günlük / haftalık grafik
        chart_card = Card("Oynama süresi")
        group = QButtonGroup(self)
        for text, weekly in ((f"Günlük (son {_DAILY_DAYS} gün)", False),
                             (f"Haftalık (son {_WEEKLY_WEEKS} hafta)", True)):
            button = QPushButton(text)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setChecked(weekly == self._weekly)
            button.clicked.connect(lambda _checked, w=weekly: self._set_weekly(w))
            group.addButton(button)
            chart_card.header.addWidget(button)
        self._chart = BarChart()
        chart_card.body.addWidget(self._chart)
        layout.addWidget(chart_card)

        # En çok oynanan oyunlar
        top_card = Card("En çok oynanan oyunlar")
        hint = QLabel("Ayrıntılar ve performans raporları için bir oyuna tıkla.")
        hint.setObjectName("muted")
        top_card.body.addWidget(hint)
        self._top = HBarList()
        self._top.clicked.connect(self.gameRequested.emit)
        top_card.body.addWidget(self._top)
        layout.addWidget(top_card)
        layout.addStretch(1)
        self.setWidget(content)

    def _set_weekly(self, weekly: bool) -> None:
        self._weekly = weekly
        self.refresh()

    def refresh(self, today: date | None = None) -> None:
        """Bütün değerleri veritabanından yeniden hesaplar."""
        today = today or date.today()
        every = self._db.list_sessions()
        monday = today - timedelta(days=today.weekday())

        self._total.set_value(stats.format_duration(sum(s.duration_s for s in every)))
        self._week.set_value(stats.format_duration(stats.total_between(every, monday, today)))
        self._today.set_value(stats.format_duration(stats.total_between(every, today, today)))
        self._count.set_value(str(len(every)))

        # Grafik yalnızca gösterilen döneme düşen oturumlara bakar.
        span = _WEEKLY_WEEKS * 7 if self._weekly else _DAILY_DAYS
        since = datetime.combine(today - timedelta(days=span + 7), time.min)
        recent = [s for s in every if s.ended_at >= since]
        if self._weekly:
            self._chart.set_bars(stats.weekly_bars(recent, _WEEKLY_WEEKS, today))
        else:
            self._chart.set_bars(stats.daily_bars(recent, _DAILY_DAYS, today))

        self._top.set_rows([
            (game.id, game.name, game.total_seconds, stats.format_duration(game.total_seconds))
            for game in self._db.top_games(10)
        ])
