"""Kütüphane taraması: bütün kaynakları tarar ve veritabanını günceller."""

from __future__ import annotations

import logging

from pwrhub.db import Database
from pwrhub.models import SOURCE_EPIC, SOURCE_STEAM, Game
from pwrhub.scanners import scan_epic, scan_exe, scan_folder, scan_steam

log = logging.getLogger(__name__)


def scan_manual(paths: list[tuple[str, str]]) -> list[Game]:
    """Kullanıcının eklediği klasör ve .exe'lerdeki oyunları döndürür."""
    games: list[Game] = []
    for path, kind in paths:
        if kind == "exe":
            game = scan_exe(path)
            if game:
                games.append(game)
        else:
            games.extend(scan_folder(path))
    return games


def refresh_library(db: Database) -> None:
    """Steam, Epic ve elle eklenen yolları tarayıp veritabanına yazar.

    Bir kaynak hata verirse diğerleri yine de taranır ve o kaynağın eski
    kayıtlarına dokunulmaz.
    """
    for source, scan in ((SOURCE_STEAM, scan_steam), (SOURCE_EPIC, scan_epic)):
        try:
            db.sync_source(source, scan())
        except Exception:  # tek bir bozuk dosya bütün taramayı durdurmasın
            log.exception("%s taraması başarısız", source)
    try:
        # Elle eklenenler en sonda: Steam/Epic ile çakışanlar elenebilsin.
        db.sync_manual(scan_manual(db.list_manual_paths()))
    except Exception:
        log.exception("Klasör taraması başarısız")
