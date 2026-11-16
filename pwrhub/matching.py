"""Çalışan programları kütüphanedeki oyunlarla eşleştirir.

Bir program, dosya yolu bir oyunun kurulum klasörünün içindeyse o oyuna
aittir. Böylece oyun PwR Hub'dan da, Steam'den ya da masaüstü kısayolundan
da açılsa oturum kaydedilir.
"""

from __future__ import annotations

import os

from pwrhub.models import SOURCE_MANUAL, Game
from pwrhub.procscan import ProcInfo
from pwrhub.scanners.folder import is_helper_exe


def norm_path(path: str) -> str:
    """Yolları karşılaştırmak için ortak biçim (küçük harf, tek tip ayraç)."""
    return os.path.normcase(os.path.normpath(path)).lower() if path else ""


class GameMatcher:
    def __init__(self, games: list[Game], exe_names: dict[int, set[str]] | None = None):
        """`exe_names`: oyun -> kurulum klasöründeki .exe adları. Dosya yolu
        okunamayan (hile koruması olan) süreçleri adından tanımak için kullanılır."""
        self._dirs: list[tuple[str, int]] = []     # (kurulum klasörü + ayraç, oyun)
        self._exact: dict[str, int] = {}           # tam exe yolu -> oyun
        self._cache: dict[str, int | None] = {}    # dosya yolu -> oyun (hesaplanmış sonuçlar)
        name_owners: dict[str, set[int]] = {}

        for game in games:
            if game.id is None:
                continue
            exe = norm_path(game.exe_path)
            if game.source == SOURCE_MANUAL and exe and game.source_id == exe:
                # Tek .exe olarak eklenen oyun: klasöründeki başka programlar
                # (ör. İndirilenler klasörü) oyun sayılmasın diye yalnızca o dosya.
                self._exact[exe] = game.id
            elif game.install_dir:
                self._dirs.append((norm_path(game.install_dir) + os.sep, game.id))
            if exe:
                name_owners.setdefault(os.path.basename(exe), set()).add(game.id)
            for name in (exe_names or {}).get(game.id, ()):
                name_owners.setdefault(name.lower(), set()).add(game.id)

        # İç içe klasörlerde en özel (en uzun) yol kazansın.
        self._dirs.sort(key=lambda item: len(item[0]), reverse=True)
        # Dosya yolu okunamayan süreçler için ad ile eşleştirme; yalnızca adı
        # kütüphanede tek bir oyuna ait olan dosyalar kullanılır.
        self._names = {
            name: next(iter(ids)) for name, ids in name_owners.items() if len(ids) == 1
        }

    def game_for(self, proc: ProcInfo) -> int | None:
        """Sürecin ait olduğu oyunun kimliği; oyun değilse None."""
        if not proc.exe:
            return self._names.get(proc.name.lower())
        # Aynı dosya yolu her turda yeniden sorulur; sonucu saklıyoruz.
        try:
            return self._cache[proc.exe]
        except KeyError:
            pass
        exe = norm_path(proc.exe)
        game_id = self._exact.get(exe)
        if game_id is None:
            game_id = next((gid for prefix, gid in self._dirs if exe.startswith(prefix)), None)
        if len(self._cache) > 4000:
            self._cache.clear()
        self._cache[proc.exe] = game_id
        return game_id

    def match(self, procs: list[ProcInfo]) -> dict[int, list[ProcInfo]]:
        """Çalışan oyunları ve her birine ait süreçleri döndürür."""
        found: dict[int, list[ProcInfo]] = {}
        for proc in procs:
            game_id = self.game_for(proc)
            if game_id is not None:
                found.setdefault(game_id, []).append(proc)
        # Yalnızca yardımcı programı (çökme raporlayıcı, güncelleyici...) çalışan
        # oyun "açık" sayılmaz.
        return {
            game_id: items
            for game_id, items in found.items()
            if any(not is_helper_exe(p.name) for p in items)
        }
