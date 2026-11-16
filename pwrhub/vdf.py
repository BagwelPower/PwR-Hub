"""Valve'ın metin tabanlı VDF/ACF biçimi için küçük bir ayrıştırıcı.

Steam'in `libraryfolders.vdf` ve `appmanifest_*.acf` dosyaları şu biçimdedir:

    "AppState"
    {
        "appid"   "730"
        "name"    "Counter-Strike 2"
    }

Dış kütüphane gerektirmemek için yalnızca ihtiyacımız olan kısmı
(tırnaklı metinler, iç içe bloklar, // yorumları) destekliyoruz.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator


class VDFError(ValueError):
    """Dosya beklenen biçimde değilse fırlatılır."""


def _tokenize(text: str) -> Iterator[str]:
    """Metni `{`, `}` ve metin parçalarına ayırır."""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch == "/" and text[i:i + 2] == "//":
            # Satır sonuna kadar yorum
            while i < n and text[i] != "\n":
                i += 1
        elif ch in "{}":
            yield ch
            i += 1
        elif ch == '"':
            i += 1
            parts: list[str] = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    # Kaçış dizileri: \\ -> \, \" -> ", \n, \t
                    nxt = text[i + 1]
                    parts.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
                    i += 2
                else:
                    parts.append(text[i])
                    i += 1
            if i >= n:
                raise VDFError("Kapanmamış tırnak")
            i += 1  # kapanış tırnağı
            # Yapısal `{` `}` ile karışmasın diye metinleri işaretliyoruz.
            yield "\0" + "".join(parts)
        else:
            # Tırnaksız metin (nadir ama geçerli)
            start = i
            while i < n and not text[i].isspace() and text[i] not in '{}"':
                i += 1
            yield "\0" + text[start:i]


def loads(text: str) -> dict:
    """VDF metnini iç içe sözlüklere çevirir. Anahtarlar küçük harfe çevrilir
    (Steam sürümleri arasında büyük/küçük harf farkı olabiliyor)."""
    root: dict = {}
    stack = [root]
    key: str | None = None
    for tok in _tokenize(text):
        if tok == "{":
            if key is None:
                raise VDFError("Anahtarsız blok")
            child: dict = {}
            stack[-1][key] = child
            stack.append(child)
            key = None
        elif tok == "}":
            if len(stack) == 1 or key is not None:
                raise VDFError("Beklenmeyen '}'")
            stack.pop()
        else:
            value = tok[1:]
            if key is None:
                key = value.lower()
            else:
                stack[-1][key] = value
                key = None
    if len(stack) != 1 or key is not None:
        raise VDFError("Dosya eksik bitiyor")
    return root


def load(path: str | Path) -> dict:
    """Dosyadan VDF okur."""
    return loads(Path(path).read_text(encoding="utf-8", errors="replace"))
