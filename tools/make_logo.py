"""PwR Hub logosunu üretir: SVG, PNG'ler ve Windows .ico dosyası.

Logo: koyu lacivert yuvarlak köşeli kare, camgöbeğinden turuncuya geçen ince
çerçeve, ortasında güç düğmesi olan çizgisel bir oyun kolu ve altında
"PwR Hub" yazısı.

Küçük boyutlarda ince ayrıntılar okunmadığı için üç sürüm vardır:
  - tam      (128 piksel ve üstü): çerçeve + oyun kolu + yazı
  - işaret   (40-64 piksel):       yalnızca kalın çizgili oyun kolu
  - simge    (32 piksel ve altı):  yalnızca güç düğmesi

Bütün şekiller ve harfler çizim yollarına çevrilir; üretilen dosyalar hiçbir
bilgisayarda yazı tipine ihtiyaç duymaz. Bu betiğin kendisi "Inter" yazı
tipinin kurulu olmasını bekler ve yalnızca logo değiştirilecekse çalıştırılır:

    python tools/make_logo.py
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
    QTransform,
)

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "pwrhub" / "assets"

SIZE = 1000                     # tasarım tuvali (birim)
NAVY = "#0f1626"                # zemin
CYAN = "#22c8ff"
ORANGE = "#ff7a1a"
# Geçişin yönü: sol alttan (camgöbeği) sağ üste (turuncu).
GRADIENT = ((150.0, 700.0), (850.0, 150.0))
# Ara duraklar geçişin ortasındaki soluk bölgeyi daraltır.
STOPS = ((0.0, CYAN), (0.36, "#3cc3ee"), (0.64, "#f28a3e"), (1.0, ORANGE))
PNG_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256, 512)

# Çizim işlemi: (tür, yol, boya, çizgi kalınlığı). Tür "fill" ya da "stroke";
# boya bir renk kodu ya da geçiş için "grad".
Op = tuple[str, QPainterPath, str, float]


def mirrored(path: QPainterPath) -> QPainterPath:
    """Yolun dikey eksene (x = 500) göre ayna görüntüsü."""
    return QTransform(-1, 0, 0, 1, SIZE, 0).map(path)


def text_path(text: str, cap_height: float, center_x: float, baseline: float) -> QPainterPath:
    """Geniş ve kalın yazıyı yola çevirir, istenen büyük harf yüksekliğine ölçekler."""
    font = QFont("Inter Display")
    font.setPixelSize(200)
    font.setWeight(QFont.Weight.Black)
    font.setStretch(118)                              # logodaki gibi geniş harfler
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 104)
    path = QPainterPath()
    path.addText(0, 0, font, text)
    box = path.boundingRect()
    scale = cap_height / box.height()
    path = QTransform.fromScale(scale, scale).map(path)
    box = path.boundingRect()
    path.translate(center_x - box.center().x(), baseline - box.bottom())
    return path


def controller(detail: bool = True) -> list[QPainterPath]:
    """Oyun kolunun çizgileri ([dış hatlar], dolu parçalar ayrı döner)."""
    # Gövdenin sol yarısı: üst kenarın ortasından başlar, sol kulptan dolaşıp
    # alt kenarın ortasına gelir. Sağ yarı aynalanır.
    half = QPainterPath()
    half.moveTo(500, 190)
    half.lineTo(374, 190)
    half.cubicTo(366, 164, 356, 150, 338, 148)        # omuz tuşunun iç yanı
    half.cubicTo(288, 146, 236, 172, 220, 220)        # omuz tuşunun üstü
    half.cubicTo(172, 340, 128, 520, 134, 592)        # sol kenar
    half.cubicTo(140, 655, 205, 672, 245, 632)        # sol kulbun ucu
    half.cubicTo(290, 585, 325, 545, 352, 520)        # kulbun iç kenarı
    half.cubicTo(362, 511, 372, 507, 388, 507)
    half.lineTo(500, 507)
    paths = [half, mirrored(half)]

    if detail:
        # Omuz tuşunu gövdeden ayıran çizgi
        shoulder = QPainterPath()
        shoulder.moveTo(214, 238)
        shoulder.cubicTo(262, 208, 322, 196, 374, 190)
        paths += [shoulder, mirrored(shoulder)]
        # Üst kenardan ortadaki daireye inen çizgiler
        brace = QPainterPath()
        brace.moveTo(374, 190)
        brace.lineTo(424, 262)
        paths += [brace, mirrored(brace)]
        # Analog çubuklar ve kulpların iç çizgileri
        stick = QPainterPath()
        stick.addEllipse(QPointF(388, 446), 40, 40)
        grip = QPainterPath()
        grip.moveTo(350, 462)
        grip.cubicTo(310, 520, 262, 585, 238, 636)
        paths += [stick, mirrored(stick), grip, mirrored(grip)]

    # Ortadaki daire
    ring = QPainterPath()
    ring.addEllipse(QPointF(500, 345), 116, 116)
    paths.append(ring)
    return paths


def power_symbol(cx: float, cy: float, radius: float) -> QPainterPath:
    """Güç düğmesi işareti: üstü açık çember ve dikey çizgi."""
    path = QPainterPath()
    box = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)
    path.arcMoveTo(box, 90 - 38)
    path.arcTo(box, 90 - 38, -(360 - 76))
    path.moveTo(cx, cy - radius * 1.18)
    path.lineTo(cx, cy - radius * 0.12)
    return path


def dpad_and_buttons() -> QPainterPath:
    """Sol yön tuşları (dört küçük kare) ve sağdaki dört yuvarlak tuş."""
    path = QPainterPath()
    cx, cy = 292.0, 300.0
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        path.addRoundedRect(QRectF(cx + dx * 40 - 17, cy + dy * 40 - 17, 34, 34), 7, 7)
    cx = 708.0
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        path.addEllipse(QPointF(cx + dx * 46, cy + dy * 46), 21, 21)
    return path


def scaled(ops: list[Op], factor: float, center=(500.0, 400.0)) -> list[Op]:
    """Çizimi tuvalin ortasına alıp büyütür (küçük sürümler için)."""
    t = QTransform()
    t.translate(SIZE / 2, SIZE / 2)
    t.scale(factor, factor)
    t.translate(-center[0], -center[1])
    return [(kind, t.map(path), paint, width * factor) for kind, path, paint, width in ops]


def build(variant: str) -> list[Op]:
    """Sürüme göre çizim işlemlerini döndürür (zemin hariç)."""
    if variant == "icon":
        return [("stroke", power_symbol(500, 520, 250), "grad", 112)]

    if variant == "mark":
        ops: list[Op] = [("stroke", p, "grad", 30) for p in controller(detail=False)]
        ops.append(("stroke", power_symbol(500, 350, 56), "grad", 26))
        return scaled(ops, 1.22, center=(500, 405))

    frame = QPainterPath()
    frame.addRoundedRect(QRectF(30, 30, SIZE - 60, SIZE - 60), 132, 132)
    ops = [("stroke", frame, "grad", 7)]
    ops += [("stroke", p, "grad", 12) for p in controller()]
    ops.append(("stroke", power_symbol(500, 350, 60), "grad", 13))
    ops.append(("fill", dpad_and_buttons(), "grad", 0))
    ops.append(("fill", text_path("PwR", 96, 500, 800), ORANGE, 0))
    ops.append(("fill", text_path("Hub", 76, 500, 908), CYAN, 0))
    return ops


def variant_for(pixels: int) -> str:
    return "icon" if pixels <= 32 else "mark" if pixels <= 64 else "full"


def render(pixels: int, variant: str | None = None) -> QImage:
    image = QImage(pixels, pixels, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(pixels / SIZE, pixels / SIZE)
    gradient = QLinearGradient(QPointF(*GRADIENT[0]), QPointF(*GRADIENT[1]))
    for offset, color in STOPS:
        gradient.setColorAt(offset, QColor(color))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(NAVY))
    painter.drawRoundedRect(QRectF(0, 0, SIZE, SIZE), 160, 160)
    for kind, path, paint, width in build(variant or variant_for(pixels)):
        brush = gradient if paint == "grad" else QColor(paint)
        if kind == "fill":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(brush)
        else:
            painter.setPen(QPen(brush, width, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    painter.end()
    return image


def svg_path(path: QPainterPath) -> str:
    """QPainterPath'i SVG 'd' metnine çevirir."""
    parts, i = [], 0
    while i < path.elementCount():
        e = path.elementAt(i)
        if e.isMoveTo():
            parts.append(f"M{e.x:.1f} {e.y:.1f}")
        elif e.isLineTo():
            parts.append(f"L{e.x:.1f} {e.y:.1f}")
        else:   # eğri: bu ve sonraki iki öge birlikte tek bir kübik eğridir
            c1, c2 = path.elementAt(i + 1), path.elementAt(i + 2)
            parts.append(f"C{e.x:.1f} {e.y:.1f} {c1.x:.1f} {c1.y:.1f} {c2.x:.1f} {c2.y:.1f}")
            i += 2
        i += 1
    return " ".join(parts)


def write_svg(target: Path, variant: str) -> None:
    shapes = []
    for kind, path, paint, width in build(variant):
        color = "url(#g)" if paint == "grad" else paint
        if kind == "fill":
            shapes.append(f'  <path d="{svg_path(path)}" fill="{color}" fill-rule="evenodd"/>')
        else:
            shapes.append(
                f'  <path d="{svg_path(path)}" fill="none" stroke="{color}" '
                f'stroke-width="{width:.1f}" stroke-linecap="round" stroke-linejoin="round"/>'
            )
    (x1, y1), (x2, y2) = GRADIENT
    target.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" role="img" '
        f'aria-label="PwR Hub">\n'
        f'  <defs>\n'
        f'    <linearGradient id="g" gradientUnits="userSpaceOnUse" x1="{x1}" y1="{y1}" '
        f'x2="{x2}" y2="{y2}">\n'
        + "".join(f'      <stop offset="{o}" stop-color="{c}"/>\n' for o, c in STOPS) +
        f'    </linearGradient>\n'
        f'  </defs>\n'
        f'  <rect width="{SIZE}" height="{SIZE}" rx="160" fill="{NAVY}"/>\n'
        + "\n".join(shapes) + "\n</svg>\n",
        encoding="utf-8",
    )


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def write_ico(target: Path, images: dict[int, QImage]) -> None:
    """Birden çok boyut içeren .ico dosyası yazar (her boyut PNG olarak gömülür)."""
    blobs = [(size, png_bytes(image)) for size, image in sorted(images.items()) if size <= 256]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = len(header) + 16 * len(blobs)
    entries, body = b"", b""
    for size, blob in blobs:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset)
        body += blob
        offset += len(blob)
    target.write_bytes(header + entries + body)


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 - yazı tipleri için gerekli
    ASSETS.mkdir(parents=True, exist_ok=True)
    for old in ASSETS.glob("logo*"):
        old.unlink()
    images = {size: render(size) for size in PNG_SIZES}
    for size, image in images.items():
        image.save(str(ASSETS / f"logo-{size}.png"))
    write_svg(ASSETS / "logo.svg", "full")
    write_svg(ASSETS / "logo-mark.svg", "mark")
    write_ico(ASSETS / "pwrhub.ico", images)
    print("Logo dosyaları yazıldı:", ASSETS)


if __name__ == "__main__":
    main()
