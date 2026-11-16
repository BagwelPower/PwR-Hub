"""Oyun ızgarası: veri modeli, arama/sıralama ve kart çizimi.

Qt'nin model/görünüm yapısını kullanıyoruz: yüzlerce oyun olsa bile yalnızca
ekranda görünen kartlar çizilir, bu yüzden kaydırma akıcı kalır.
"""

from __future__ import annotations

import re

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPolygonF
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate

from pwrhub.models import Game
from pwrhub.stats import format_duration
from pwrhub.ui import style
from pwrhub.ui.covers import CoverCache

GAME_ROLE = Qt.ItemDataRole.UserRole + 1
RUNNING_ROLE = Qt.ItemDataRole.UserRole + 2   # oyun şu an açık mı

# Sıralama seçenekleri: (anahtar, arayüzde görünen ad)
SORT_OPTIONS = [
    ("name_asc", "Ada göre (A-Z)"),
    ("name_desc", "Ada göre (Z-A)"),
    ("recent", "Son oynanan"),
    ("most_played", "En çok oynanan"),
    ("added", "Son eklenen"),
    ("source", "Kaynağa göre"),
]


def fold(text: str) -> str:
    """Aramada büyük/küçük harf ve Türkçe I/İ/ı farkını yok sayar."""
    return text.replace("İ", "i").replace("I", "i").replace("ı", "i").lower().strip()


_SORT_MAP = str.maketrans("çğöşüâîû", "cgosuaiu")


def sort_key(name: str) -> list:
    """Doğal sıralama anahtarı: "Oyun 2", "Oyun 10"dan önce gelir; Türkçe
    harfler (ç, ş, ö...) alfabedeki yerlerine yakın sıralanır."""
    folded = fold(name).translate(_SORT_MAP)
    return [(0, int(part), "") if part.isdigit() else (1, 0, part)
            for part in re.split(r"(\d+)", folded) if part]


class GameListModel(QAbstractListModel):
    """Kütüphanedeki oyunların düz listesi."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._games: list[Game] = []
        self._running: set[int] = set()

    def set_running(self, game_ids: set[int]) -> None:
        """Şu an açık olan oyunları işaretler (kartta "Oynanıyor" yazar)."""
        self._running = set(game_ids)
        if self._games:
            self.dataChanged.emit(self.index(0), self.index(len(self._games) - 1), [RUNNING_ROLE])

    def set_games(self, games: list[Game]) -> None:
        self.beginResetModel()
        self._games = list(games)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._games)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        game = self._games[index.row()]
        if role == GAME_ROLE:
            return game
        if role == RUNNING_ROLE:
            return game.id in self._running
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return game.name
        return None


class GameFilterProxy(QSortFilterProxyModel):
    """Arama kutusuna göre süzer, seçilen ölçüte göre sıralar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._query = ""
        self._sort_key = "name_asc"
        self.setDynamicSortFilter(True)
        self.sort(0)

    def set_query(self, text: str) -> None:
        self._query = fold(text)
        self.invalidate()

    def set_sort_key(self, key: str) -> None:
        self._sort_key = key
        self.invalidate()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        if not self._query:
            return True
        game: Game = self.sourceModel().index(row, 0, parent).data(GAME_ROLE)
        return self._query in fold(game.name)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        a: Game = left.data(GAME_ROLE)
        b: Game = right.data(GAME_ROLE)
        name_a, name_b = sort_key(a.name), sort_key(b.name)
        key = self._sort_key
        if key == "name_desc":
            return name_a > name_b
        if key == "recent" and a.last_activity != b.last_activity:
            return a.last_activity > b.last_activity  # yeni olan önce
        if key == "most_played" and a.total_seconds != b.total_seconds:
            return a.total_seconds > b.total_seconds
        if key == "added" and a.added_at != b.added_at:
            return a.added_at > b.added_at
        if key == "source" and a.source != b.source:
            return a.source_label < b.source_label
        return name_a < name_b


class GameCardDelegate(QStyledItemDelegate):
    """Tek bir oyun kartını çizer: kapak, ad, kaynak ve oynanma süresi."""

    def __init__(self, covers: CoverCache, parent=None):
        super().__init__(parent)
        self._covers = covers

    def sizeHint(self, option, index) -> QSize:
        return QSize(style.CARD_W, style.CARD_H)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        game: Game = index.data(GAME_ROLE)
        if game is None:
            return
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(option.rect).adjusted(2, 2, -2, -2)

        # Kart zemini (üzerine gelince ya da klavyeyle seçilince belirginleşir)
        if hovered or focused:
            painter.setPen(QColor(style.ACCENT_2) if focused else Qt.PenStyle.NoPen)
            painter.setBrush(QColor(style.SURFACE_HOVER))
            painter.drawRoundedRect(card, style.CARD_RADIUS + 2, style.CARD_RADIUS + 2)

        if game.hidden:
            painter.setOpacity(0.45)  # gizlenen oyunlar soluk görünür

        # Kapak
        cover_rect = QRect(
            option.rect.left() + style.CARD_PADDING,
            option.rect.top() + style.CARD_PADDING,
            style.COVER_W,
            style.COVER_H,
        )
        dpr = painter.device().devicePixelRatioF()
        painter.drawPixmap(cover_rect.topLeft(), self._covers.get(game, dpr))

        # Üzerine gelince "oynat" işareti
        if hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 110))
            painter.drawRoundedRect(QRectF(cover_rect), style.CARD_RADIUS, style.CARD_RADIUS)
            center = QPointF(cover_rect.center())
            painter.setBrush(QColor(style.ACCENT))
            painter.drawEllipse(center, 28, 28)
            painter.setBrush(QColor(style.ACCENT_TEXT))
            painter.drawPolygon(QPolygonF([
                center + QPointF(-8, -12), center + QPointF(-8, 12), center + QPointF(13, 0),
            ]))

        # Oyun adı (sığmazsa "…" ile kısaltılır)
        text_left = cover_rect.left() + 2
        text_width = style.COVER_W - 4
        name_font = QFont(option.font)
        name_font.setPixelSize(14)
        name_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(name_font)
        painter.setPen(QColor(style.TEXT))
        name_rect = QRect(text_left, cover_rect.bottom() + 8, text_width, 20)
        elided = QFontMetrics(name_font).elidedText(
            game.name, Qt.TextElideMode.ElideRight, text_width
        )
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        # Kaynak (Steam / Epic Games / Elle eklendi)
        sub_font = QFont(option.font)
        sub_font.setPixelSize(12)
        painter.setFont(sub_font)
        sub_rect = QRect(text_left, name_rect.bottom() + 1, text_width, 18)
        if index.data(RUNNING_ROLE):
            painter.setPen(QColor(style.STATUS["good"]))
            label = "● Oynanıyor"
        else:
            painter.setPen(QColor(style.TEXT_MUTED))
            label = game.source_label
            if game.total_seconds > 0:
                label += " · " + format_duration(game.total_seconds)
            if game.hidden:
                label += " · Gizli"
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

        painter.restore()


class GameGridView(QListView):
    """Kartları pencere genişliğine göre satırlara dizen ızgara."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setSpacing(8)
        self.setMouseTracking(True)  # üzerine gelme efekti için
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(40)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
