"""Renkler ve Qt stil sayfası. Görünümü değiştirmek için tek yer burası."""

# Renk paleti (koyu tema). Logonun renkleriyle uyumludur: lacivert zemin,
# turuncu ana vurgu, camgöbeği ikinci vurgu.
BG = "#0b101b"          # pencere arka planı
SURFACE = "#121a2b"     # kartlar, giriş kutuları
SURFACE_HOVER = "#1b2640"
BORDER = "#26334d"
TEXT = "#eceef4"
TEXT_MUTED = "#8a95ab"
ACCENT = "#ff7a1a"      # ana vurgu (turuncu): birincil düğmeler, oynat işareti
ACCENT_HOVER = "#ff9140"
ACCENT_TEXT = "#0f1626" # turuncu üzerindeki yazı (beyaz yeterince okunmuyor)
ACCENT_2 = "#22c8ff"    # ikinci vurgu (camgöbeği): odak çerçeveleri, seçili ögeler

# Grafik renkleri. Koyu zemin üzerinde renk körlüğü ayrımı ve karşıtlık
# açısından doğrulanmış bir palet; sırası sabittir (kaynak -> renk hiç değişmez).
SERIES = {"cpu": "#3987e5", "mem": "#d95926", "disk": "#199e70", "gpu": "#c98500"}
SERIES_LABELS = {"cpu": "İşlemci", "core": "En yoğun çekirdek", "mem": "Bellek",
                 "disk": "Disk", "gpu": "Ekran kartı", "vram": "Ekran kartı belleği (VRAM)",
                 "temp": "Ekran kartı sıcaklığı"}
BAR = "#3987e5"          # tek serili çubuk grafikler
GRID = "#1e2940"         # grafik ızgara çizgileri (geri planda kalmalı)

# Zorlanma düzeyi renkleri; her zaman bir etiketle birlikte kullanılır.
STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

# Kart ölçüleri (piksel). Kapak oranı 2:3 (Steam dikey kapaklarıyla aynı).
COVER_W = 168
COVER_H = 252
CARD_PADDING = 10
CARD_TEXT_H = 46
CARD_W = COVER_W + 2 * CARD_PADDING
CARD_H = COVER_H + 2 * CARD_PADDING + CARD_TEXT_H
CARD_RADIUS = 10

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 14px;
}}
QLabel#title {{
    font-size: 20px;
    font-weight: 700;
}}
QLabel#muted, QLabel#status {{
    color: {TEXT_MUTED};
}}
QLabel#emptyTitle {{
    font-size: 18px;
    font-weight: 600;
}}
QLineEdit, QComboBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {ACCENT_2};
    selection-color: {ACCENT_TEXT};
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {ACCENT_2};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    selection-background-color: {SURFACE_HOVER};
    outline: none;
}}
QPushButton, QToolButton {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
}}
QPushButton:hover, QToolButton:hover {{
    background: {SURFACE_HOVER};
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
}}
QPushButton#primary {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: {ACCENT_TEXT};
    font-weight: 700;
}}
QPushButton#primary:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#nav {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {TEXT_MUTED};
    font-weight: 600;
    padding: 7px 12px;
}}
QPushButton#nav:hover {{
    color: {TEXT};
}}
QPushButton#nav:checked {{
    background: {SURFACE};
    color: {ACCENT};
}}
QPushButton#segment {{
    padding: 5px 12px;
    color: {TEXT_MUTED};
}}
QPushButton#segment:checked {{
    background: {SURFACE_HOVER};
    border-color: {ACCENT_2};
    color: {TEXT};
}}
QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#card QLabel, QFrame#card QWidget {{
    background: transparent;
}}
QLabel#tileValue {{
    font-size: 22px;
    font-weight: 700;
}}
QLabel#tileLabel {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#cardTitle {{
    font-size: 15px;
    font-weight: 600;
}}
QLabel#score {{
    font-size: 34px;
    font-weight: 700;
}}
QLabel#tableHead {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QCheckBox {{
    spacing: 10px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {TEXT_MUTED};
    border-radius: 4px;
    background: {BG};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QCheckBox::indicator:disabled {{
    border-color: {BORDER};
}}
QCheckBox:disabled {{
    color: {TEXT_MUTED};
}}
QScrollArea {{
    border: none;
}}
QToolTip {{
    background: {SURFACE_HOVER};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5px 8px;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
}}
QListWidget::item:selected {{
    background: {SURFACE_HOVER};
    color: {TEXT};
}}
QToolButton::menu-indicator {{
    image: none;
}}
QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {SURFACE_HOVER};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 5px 8px;
}}
QListView {{
    border: none;
    outline: none;
}}
QListWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""
