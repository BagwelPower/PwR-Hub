"""Grafik bileşenleri (QPainter ile çizilir, ek kütüphane gerektirmez).

  - BarChart:  süre çubukları (günlük / haftalık oynama süresi)
  - HBarList:  yatay çubuklu sıralı liste (en çok oynanan oyunlar)
  - LineChart: 0-100 arası yüzde çizgileri (işlemci, bellek, disk)

Hepsinde fareyle üzerine gelince değerler gösterilir.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from pwrhub.stats import Bar, format_duration
from pwrhub.ui import style

# Süre ekseni için "güzel" adım değerleri (saniye): 5 dk ... 24 sa
_STEPS = [300, 600, 900, 1800, 3600, 7200, 10800, 14400, 21600, 43200, 86400]


def _font(widget: QWidget, pixel_size: int, bold: bool = False) -> QFont:
    font = QFont(widget.font())
    font.setPixelSize(pixel_size)
    font.setBold(bold)
    return font


def _axis_step(maximum: float) -> int:
    """En fazla dört ızgara çizgisi çıkaracak adımı seçer."""
    for step in _STEPS:
        if maximum / step <= 4:
            return step
    return int(maximum // 4 // 86400 + 1) * 86400


def _axis_label(seconds: int) -> str:
    if seconds == 0:
        return "0"
    return f"{seconds // 3600} sa" if seconds % 3600 == 0 else f"{seconds // 60} dk"


def _bar_path(rect: QRectF, radius: float, right: bool = False) -> QPainterPath:
    """Taban çizgisine oturan, yalnızca veri ucu yuvarlatılmış çubuk."""
    radius = min(radius, rect.width() / 2, rect.height())
    path = QPainterPath()
    if right:   # yatay çubuk: sağ ucu yuvarlak
        path.moveTo(rect.topLeft())
        path.lineTo(rect.right() - radius, rect.top())
        path.quadTo(rect.topRight(), QPointF(rect.right(), rect.top() + radius))
        path.lineTo(rect.right(), rect.bottom() - radius)
        path.quadTo(rect.bottomRight(), QPointF(rect.right() - radius, rect.bottom()))
        path.lineTo(rect.bottomLeft())
    else:       # dikey çubuk: üst ucu yuvarlak
        path.moveTo(rect.bottomLeft())
        path.lineTo(rect.left(), rect.top() + radius)
        path.quadTo(rect.topLeft(), QPointF(rect.left() + radius, rect.top()))
        path.lineTo(rect.right() - radius, rect.top())
        path.quadTo(rect.topRight(), QPointF(rect.right(), rect.top() + radius))
        path.lineTo(rect.bottomRight())
    path.closeSubpath()
    return path


class BarChart(QWidget):
    """Oynama süresi çubuk grafiği."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars: list[Bar] = []
        self._rects: list[QRectF] = []   # fare algılama alanları (çubuktan geniş)
        self._hover = -1
        self.setMinimumHeight(220)
        self.setMouseTracking(True)

    def set_bars(self, bars: list[Bar]) -> None:
        self._bars = bars
        self._hover = -1
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, right, bottom = 48, 12, 8, 26
        plot = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        self._rects = []

        maximum = max((bar.seconds for bar in self._bars), default=0)
        if maximum <= 0:
            painter.setPen(QColor(style.TEXT_MUTED))
            painter.setFont(_font(self, 13))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Bu dönemde oynama kaydı yok")
            return

        step = _axis_step(maximum)
        top_value = (int(maximum // step) + (1 if maximum % step else 0)) * step

        # Izgara ve süre ekseni
        painter.setFont(_font(self, 11))
        for value in range(0, top_value + 1, step):
            y = plot.bottom() - value / top_value * plot.height()
            painter.setPen(QPen(QColor(style.GRID), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(style.TEXT_MUTED))
            painter.drawText(QRectF(0, y - 9, left - 8, 18),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             _axis_label(value))

        # Çubuklar
        slot = plot.width() / len(self._bars)
        width = min(max(slot - 8, 4), 32)   # ince çubuk, aralarında boşluk
        metrics = QFontMetrics(painter.font())
        for i, bar in enumerate(self._bars):
            x = plot.left() + i * slot
            self._rects.append(QRectF(x, plot.top(), slot, plot.height() + bottom))
            height = bar.seconds / top_value * plot.height()
            if height > 0:
                rect = QRectF(x + (slot - width) / 2, plot.bottom() - max(height, 2), width, max(height, 2))
                color = QColor(style.BAR)
                if i == self._hover:
                    color = color.lighter(125)
                painter.fillPath(_bar_path(rect, 4), color)
            # Eksen etiketi (dar yerde sığmayanlar atlanır)
            if metrics.horizontalAdvance(bar.label) <= slot - 2 or i % 2 == 0:
                painter.setPen(QColor(style.TEXT if i == self._hover else style.TEXT_MUTED))
                painter.drawText(QRectF(x - 20, plot.bottom() + 6, slot + 40, 18),
                                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, bar.label)

    def mouseMoveEvent(self, event) -> None:
        hover = next((i for i, r in enumerate(self._rects) if r.contains(event.position())), -1)
        if hover != self._hover:
            self._hover = hover
            self.update()
        if hover >= 0:
            bar = self._bars[hover]
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{bar.detail}\n{format_duration(bar.seconds)}", self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, _event) -> None:
        self._hover = -1
        self.update()


class HBarList(QWidget):
    """Sıralı yatay çubuk listesi: ad | çubuk | değer. Satıra tıklanabilir."""

    clicked = Signal(object)   # tıklanan satırın anahtarı
    ROW = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[object, str, float, str]] = []  # (anahtar, ad, değer, metin)
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_rows(self, rows: list[tuple[object, str, float, str]]) -> None:
        self._rows = rows
        self._hover = -1
        self.setFixedHeight(max(len(rows), 2) * self.ROW)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(400, max(len(self._rows), 2) * self.ROW)

    minimumSizeHint = sizeHint

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._rows:
            painter.setPen(QColor(style.TEXT_MUTED))
            painter.setFont(_font(self, 13))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Henüz oynama kaydı yok")
            return

        name_w = min(220, int(self.width() * 0.34))
        value_w = 96
        bar_left = name_w + 12
        bar_max = max(self.width() - bar_left - value_w - 8, 10)
        maximum = max(row[2] for row in self._rows) or 1
        painter.setFont(_font(self, 13))
        metrics = QFontMetrics(painter.font())

        for i, (_key, name, value, text) in enumerate(self._rows):
            y = i * self.ROW
            if i == self._hover:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(style.SURFACE_HOVER))
                painter.drawRoundedRect(QRectF(0, y + 2, self.width(), self.ROW - 4), 6, 6)
            painter.setPen(QColor(style.TEXT))
            painter.drawText(QRectF(8, y, name_w - 8, self.ROW),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             metrics.elidedText(name, Qt.TextElideMode.ElideRight, name_w - 8))
            length = max(value / maximum * bar_max, 3)
            painter.fillPath(_bar_path(QRectF(bar_left, y + 12, length, self.ROW - 24), 4, right=True),
                             QColor(style.BAR))
            painter.setPen(QColor(style.TEXT_MUTED))
            painter.drawText(QRectF(self.width() - value_w - 8, y, value_w, self.ROW),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

    def _row_at(self, pos) -> int:
        index = int(pos.y() // self.ROW)
        return index if 0 <= index < len(self._rows) else -1

    def mouseMoveEvent(self, event) -> None:
        hover = self._row_at(event.position())
        if hover != self._hover:
            self._hover = hover
            self.update()

    def leaveEvent(self, _event) -> None:
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        index = self._row_at(event.position())
        if index >= 0 and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._rows[index][0])


class LineChart(QWidget):
    """Zaman içinde yüzde (0-100) çizgi grafiği: işlemci, bellek, disk.

    Üç seri de aynı 0-100 eksenini paylaşır; ikinci bir eksen yoktur.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._times: list[datetime] = []
        self._series: list[tuple[str, str, list[float]]] = []   # (ad, renk, değerler)
        self._marker: datetime | None = None
        self._marker_text = ""
        self._hover = -1
        self.setMinimumHeight(230)
        self.setMouseTracking(True)

    def set_data(
        self,
        times: list[datetime],
        series: list[tuple[str, str, list[float]]],
        marker: datetime | None = None,
        marker_text: str = "",
    ) -> None:
        self._times, self._series = times, series
        self._marker, self._marker_text = marker, marker_text
        self._hover = -1
        self.update()

    # Çizim alanı ve koordinat dönüşümleri
    def _plot(self) -> QRectF:
        return QRectF(44, 48, self.width() - 44 - 14, self.height() - 48 - 26)

    def _x(self, index: int, plot: QRectF) -> float:
        last = max(len(self._times) - 1, 1)
        return plot.left() + index / last * plot.width()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = self._plot()

        # Gösterge: her zaman görünür, kimlik yalnızca renge bırakılmaz
        painter.setFont(_font(self, 12))
        metrics = QFontMetrics(painter.font())
        x = plot.left()
        for name, color, _values in self._series:
            painter.setPen(QPen(QColor(color), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x, 14), QPointF(x + 14, 14))
            painter.setPen(QColor(style.TEXT_MUTED))
            painter.drawText(QPointF(x + 20, 18), name)
            x += 20 + metrics.horizontalAdvance(name) + 20

        # Izgara ve yüzde ekseni
        painter.setFont(_font(self, 11))
        for value in (0, 25, 50, 75, 100):
            y = plot.bottom() - value / 100 * plot.height()
            painter.setPen(QPen(QColor(style.GRID), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(style.TEXT_MUTED))
            painter.drawText(QRectF(0, y - 9, plot.left() - 8, 18),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"%{value}")

        if len(self._times) < 2:
            painter.setPen(QColor(style.TEXT_MUTED))
            painter.setFont(_font(self, 13))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Grafik için yeterli ölçüm yok")
            return

        # Zaman ekseni: başlangıç, orta, bitiş
        painter.setPen(QColor(style.TEXT_MUTED))
        last = len(self._times) - 1
        for index, align in ((0, Qt.AlignmentFlag.AlignLeft), (last // 2, Qt.AlignmentFlag.AlignHCenter),
                             (last, Qt.AlignmentFlag.AlignRight)):
            x = self._x(index, plot)
            painter.drawText(QRectF(x - 40, plot.bottom() + 6, 80, 18)
                             .translated({Qt.AlignmentFlag.AlignLeft: 40,
                                          Qt.AlignmentFlag.AlignRight: -40}.get(align, 0), 0),
                             align | Qt.AlignmentFlag.AlignTop, f"{self._times[index]:%H:%M}")

        # "En zor an" işareti
        if self._marker is not None:
            index = min(range(len(self._times)), key=lambda i: abs(self._times[i] - self._marker))
            x = self._x(index, plot)
            painter.setPen(QPen(QColor(style.TEXT_MUTED), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            width = metrics.horizontalAdvance(self._marker_text) + 10
            label_x = min(max(x - width / 2, plot.left()), plot.right() - width)
            painter.setPen(QColor(style.TEXT))
            painter.drawText(QRectF(label_x, plot.top() - 20, width, 16),
                             Qt.AlignmentFlag.AlignCenter, self._marker_text)

        # Çizgiler (2 piksel)
        painter.setClipRect(plot.adjusted(-2, -2, 2, 2))
        for _name, color, values in self._series:
            path = QPainterPath()
            for i, value in enumerate(values):
                point = QPointF(self._x(i, plot), plot.bottom() - min(max(value, 0), 100) / 100 * plot.height())
                path.lineTo(point) if i else path.moveTo(point)
            painter.setPen(QPen(QColor(color), 2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.setClipping(False)

        # Üzerine gelinen an: dikey kılavuz ve zemin rengiyle çevrili noktalar
        if 0 <= self._hover < len(self._times):
            x = self._x(self._hover, plot)
            painter.setPen(QPen(QColor(style.BORDER).lighter(160), 1))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            for _name, color, values in self._series:
                y = plot.bottom() - min(max(values[self._hover], 0), 100) / 100 * plot.height()
                painter.setPen(QPen(QColor(style.SURFACE), 2))
                painter.setBrush(QColor(color))
                painter.drawEllipse(QPointF(x, y), 5, 5)

    def mouseMoveEvent(self, event) -> None:
        plot = self._plot()
        if len(self._times) < 2 or not plot.adjusted(-6, 0, 6, 0).contains(event.position()):
            self._set_hover(-1)
            QToolTip.hideText()
            return
        ratio = (event.position().x() - plot.left()) / plot.width()
        index = round(min(max(ratio, 0), 1) * (len(self._times) - 1))
        self._set_hover(index)
        rows = "".join(
            f"<tr><td><span style='color:{color}'>■</span> {name}</td>"
            f"<td align='right'>&nbsp;&nbsp;%{round(values[index])}</td></tr>"
            for name, color, values in self._series
        )
        QToolTip.showText(event.globalPosition().toPoint(),
                          f"<b>{self._times[index]:%H:%M:%S}</b><table>{rows}</table>", self)

    def _set_hover(self, index: int) -> None:
        if index != self._hover:
            self._hover = index
            self.update()

    def leaveEvent(self, _event) -> None:
        self._set_hover(-1)
