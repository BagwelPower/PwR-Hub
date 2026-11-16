"""Kullanıcının elle eklediği klasörlerdeki oyunları bulur.

Bir klasör iki şekilde yorumlanır:
  - İçinde doğrudan oyun .exe'si varsa klasörün kendisi tek bir oyundur.
  - Yoksa her alt klasör ayrı bir oyun sayılır ("D:\\Oyunlar" gibi bir kütüphane).

Bir oyun klasöründe genelde birden fazla .exe bulunur (kaldırıcı, çökme
raporlayıcı, kurulum dosyaları...). Doğru olanı seçmek için basit bir
puanlama kullanıyoruz; kullanıcı gerekirse oyunu tek .exe olarak da ekleyebilir.
"""

from __future__ import annotations

import math
import os
import re
from difflib import SequenceMatcher
from pathlib import Path

from pwrhub.models import SOURCE_MANUAL, Game

# Oyun exe'si aranırken klasörün kaç seviye altına inileceği.
# (Unreal oyunları: Oyun/Binaries/Win64/Oyun-Win64-Shipping.exe)
_MAX_DEPTH = 4

# Adında bunlar geçen .exe dosyaları oyun değildir.
_SKIP_EXE = re.compile(
    r"unins|setup|install|redist|vcredist|vc_redist|dxsetup|directx|dotnet|"
    r"crash|report|helper|updater|prereq|easyanticheat|battleye|beservice|"
    r"cefprocess|subprocess|handler|7z|touchup|activation|cleanup|diagnos",
    re.IGNORECASE,
)

# İçine hiç girilmeyecek klasörler.
_SKIP_DIRS = {
    "_commonredist", "commonredist", "redist", "redistributables", "__installer",
    "directx", "support", "_support", "extras", "thirdparty", "dotnet", "vcredist",
    "easyanticheat", "battleye", "__pycache__",
}


def is_helper_exe(name: str) -> bool:
    """Dosya adı asıl oyun değil de yardımcı program (kaldırıcı, çökme
    raporlayıcı, güncelleyici...) gibi mi görünüyor?"""
    return bool(_SKIP_EXE.search(name))


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _candidate_exes(folder: Path, max_depth: int = _MAX_DEPTH) -> list[tuple[Path, int]]:
    """Klasördeki olası oyun exe'lerini (yol, derinlik) olarak döndürür."""
    found: list[tuple[Path, int]] = []
    base_depth = len(folder.parts)
    for root, dirs, files in os.walk(folder):
        depth = len(Path(root).parts) - base_depth
        if depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.lower().endswith(".exe") and not _SKIP_EXE.search(name):
                found.append((Path(root) / name, depth))
    return found


def exe_names(folder: str | Path) -> set[str]:
    """Klasördeki olası oyun exe'lerinin (küçük harfli) dosya adları."""
    folder = Path(folder)
    if not folder.is_dir():
        return set()
    return {exe.name.lower() for exe, _depth in _candidate_exes(folder)}


def _score(exe: Path, depth: int, game_name: str) -> float:
    """Exe'nin 'asıl oyun dosyası' olma olasılığını puanlar (yüksek = daha iyi)."""
    stem = _normalize(exe.stem)
    target = _normalize(game_name)
    score = SequenceMatcher(None, stem, target).ratio() * 100  # ad benzerliği
    if target and (target in stem or stem in target):
        score += 20
    try:
        size_mb = exe.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0
    score += min(math.log2(size_mb + 1) * 4, 30)  # büyük dosya genelde asıl oyundur
    score -= depth * 6                             # köke yakın olan tercih edilir
    if "launcher" in stem:
        score -= 15
    return score


def best_exe(folder: Path, game_name: str | None = None) -> Path | None:
    """Klasördeki en olası oyun exe'sini döndürür; hiç yoksa None."""
    game_name = game_name or folder.name
    candidates = _candidate_exes(folder)
    if not candidates:
        return None
    return max(candidates, key=lambda c: (_score(c[0], c[1], game_name), str(c[0])))[0]


def _pretty_name(raw: str) -> str:
    """Klasör/dosya adını okunur hale getirir: 'Hollow_Knight' -> 'Hollow Knight'."""
    return re.sub(r"\s+", " ", raw.replace("_", " ")).strip() or raw


def _source_id(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path))).lower()


def _game_from_dir(folder: Path) -> Game | None:
    exe = best_exe(folder)
    if exe is None:
        return None
    return Game(
        source=SOURCE_MANUAL,
        source_id=_source_id(folder),
        name=_pretty_name(folder.name),
        install_dir=str(folder),
        exe_path=str(exe),
    )


def scan_folder(folder: str | Path) -> list[Game]:
    """Elle eklenen bir klasördeki oyunları döndürür."""
    folder = Path(folder)
    if not folder.is_dir():
        return []

    # Klasörün hemen içinde oyun exe'si varsa klasörün kendisi bir oyundur.
    if _candidate_exes(folder, max_depth=0):
        game = _game_from_dir(folder)
        return [game] if game else []

    games: list[Game] = []
    try:
        subdirs = sorted(p for p in folder.iterdir() if p.is_dir())
    except OSError:
        return []
    for sub in subdirs:
        if sub.name.lower() in _SKIP_DIRS or sub.name.startswith("."):
            continue
        game = _game_from_dir(sub)
        if game:
            games.append(game)
    return games


def scan_exe(exe_path: str | Path) -> Game | None:
    """Kullanıcının doğrudan seçtiği tek bir .exe'yi oyun olarak döndürür."""
    exe = Path(exe_path)
    if not exe.is_file():
        return None
    return Game(
        source=SOURCE_MANUAL,
        source_id=_source_id(exe),
        name=_pretty_name(exe.stem),
        install_dir=str(exe.parent),
        exe_path=str(exe),
    )
