"""Kapak resimlerini yükler, ölçekler ve bellekte tutar.

Kapak bulunamayan oyunlar için internetten indirme yapılmaz; bunun yerine
oyunun .exe simgesi ve adıyla renkli bir yer tutucu kart çizilir.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QFileInfo, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from pwrhub.models import Game
from pwrhub.ui import style


class CoverCache:
    """Oyun başına hazır (ölçeklenmiş, köşeleri yuvarlatılmış) kapak tutar."""

    # Bellekte tutulan en fazla kapak sayısı. Her kapak yaklaşık 170-400 KB
    # yer kaplar; sınır olmasaydı büyük kütüphanelerde bellek sürekli artardı.
    MAX_ITEMS = 120

    def __init__(self) -> None:
        self._cache: dict[tuple, QPixmap] = {}
        self._icons = QFileIconProvider()

    def clear(self) -> None:
        self._cache.clear()

    def get(self, game: Game, dpr: float = 1.0) -> QPixmap:
        """Oyunun kart boyutundaki kapağını döndürür."""
        key = (game.source, game.source_id, game.effective_cover, round(dpr, 2))
        pixmap = self._cache.pop(key, None)
        if pixmap is None:
            pixmap = self._render(game, dpr)
            if len(self._cache) >= self.MAX_ITEMS:
                # En uzun süredir kullanılmayan kapağı at (sözlük ekleme sırasını korur).
                del self._cache[next(iter(self._cache))]
        self._cache[key] = pixmap   # en son kullanılan sona gider
        return pixmap

    # ------------------------------------------------------------------ çizim

    def _render(self, game: Game, dpr: float) -> QPixmap:
        w, h = int(style.COVER_W * dpr), int(style.COVER_H * dpr)
        source = QPixmap(game.effective_cover) if game.effective_cover else QPixmap()

        result = QPixmap(w, h)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        clip = QPainterPath()
        radius = style.CARD_RADIUS * dpr
        clip.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        painter.setClipPath(clip)

        if not source.isNull():
            # Kartı tamamen dolduracak şekilde ölçekle, taşan kısmı ortadan kırp.
            scaled = source.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
        else:
            self._draw_placeholder(painter, game, w, h, dpr)
        painter.end()
        result.setDevicePixelRatio(dpr)
        return result

    def _draw_placeholder(self, painter: QPainter, game: Game, w: int, h: int, dpr: float) -> None:
        """Kapak yoksa: ada göre sabit renkli zemin + exe simgesi + oyun adı."""
        hue = int(hashlib.md5(game.name.encode("utf-8")).hexdigest()[:4], 16) % 360
        gradient = QLinearGradient(0, 0, w, h)
        gradient.setColorAt(0, QColor.fromHsl(hue, 110, 78))
        gradient.setColorAt(1, QColor.fromHsl((hue + 40) % 360, 120, 38))
        painter.fillRect(0, 0, w, h, gradient)

        icon_size = int(72 * dpr)
        icon = self._exe_icon(game, icon_size)
        text_top = int(h * 0.30)
        if icon is not None:
            painter.drawPixmap((w - icon.width()) // 2, int(h * 0.22), icon)
            text_top = int(h * 0.22) + icon.height() + int(14 * dpr)

        font = QFont(painter.font())
        font.setPixelSize(int(17 * dpr))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 235))
        margin = int(14 * dpr)
        painter.drawText(
            QRect(margin, text_top, w - 2 * margin, h - text_top - margin),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            game.name,
        )

    def _exe_icon(self, game: Game, size: int) -> QPixmap | None:
        """Oyunun .exe dosyasındaki simgeyi döndürür (yoksa None)."""
        if not game.exe_path or not Path(game.exe_path).is_file():
            return None
        pixmap = self._icons.icon(QFileInfo(game.exe_path)).pixmap(size, size)
        if pixmap.isNull():
            return None
        return pixmap.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
