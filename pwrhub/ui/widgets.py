"""Birden fazla sayfada kullanılan küçük arayüz parçaları."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class Card(QFrame):
    """Başlıklı, çerçeveli içerik kutusu."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 14, 18, 16)
        self.body.setSpacing(12)
        self.header = QHBoxLayout()
        if title:
            label = QLabel(title)
            label.setObjectName("cardTitle")
            self.header.addWidget(label)
        self.header.addStretch(1)
        self.body.addLayout(self.header)


class StatTile(QFrame):
    """Tek bir öne çıkan değer: büyük sayı ve altında açıklaması."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        self._value = QLabel("-")
        self._value.setObjectName("tileValue")
        caption = QLabel(label)
        caption.setObjectName("tileLabel")
        layout.addWidget(self._value)
        layout.addWidget(caption)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


def tile_row(tiles: list[StatTile]) -> QWidget:
    """Kutucukları eşit genişlikte yan yana dizer."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    for tile in tiles:
        layout.addWidget(tile, 1)
    return row
