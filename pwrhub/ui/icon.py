"""Uygulama simgesi ve logosu.

Logo dosyaları `pwrhub/assets` klasöründedir ve `tools/make_logo.py` ile
üretilir. Boyuta göre üç sürüm vardır: büyüklerde çerçeveli tam logo,
ortalarda yalnızca oyun kolu, en küçüklerde (32 piksel ve altı) yalnızca
güç düğmesi; çünkü ince ayrıntılar küçük boyutta okunmaz.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

ASSETS = Path(__file__).resolve().parent.parent / "assets"
_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256, 512)


def _fallback(size: int) -> QPixmap:
    """Logo dosyası bulunamazsa çizilen yedek simge (lacivert kare içinde P)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#0f1626"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    font = QFont()
    font.setPixelSize(int(size * 0.62))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#ff7a1a"))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "P")
    painter.end()
    return pixmap


def logo_pixmap(size: int) -> QPixmap:
    """İstenen boyuta en uygun logo resmi."""
    source = next((s for s in _SIZES if s >= size), _SIZES[-1])
    pixmap = QPixmap(str(ASSETS / f"logo-{source}.png"))
    if pixmap.isNull():
        return _fallback(size)
    if source != size:
        pixmap = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
    return pixmap


def app_icon() -> QIcon:
    """Pencere, görev çubuğu ve sistem tepsisi simgesi (bütün boyutlarıyla)."""
    icon = QIcon()
    for size in _SIZES:
        icon.addPixmap(logo_pixmap(size))
    return icon
