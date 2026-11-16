"""Steam kütüphanesini yerel dosyalardan bulur.

Adımlar:
  1. Steam'in kurulu olduğu klasörü bul (kayıt defteri, sonra bilinen yollar).
  2. `steamapps/libraryfolders.vdf` içinden bütün kütüphane klasörlerini oku.
  3. Her kütüphanedeki `appmanifest_<appid>.acf` dosyalarından oyunları çıkar.
  4. Kapak resmini Steam'in kendi yerel önbelleğinden al (indirme yapılmaz).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from pwrhub import vdf
from pwrhub.models import SOURCE_STEAM, Game

log = logging.getLogger(__name__)

# Oyun olmayan Steam bileşenleri (araçlar, çalışma ortamları).
_TOOL_APPIDS = {"228980"}  # Steamworks Common Redistributables
_TOOL_NAME_PREFIXES = ("proton", "steam linux runtime", "steamworks common", "steamvr")

# StateFlags içindeki "tamamen kurulu" biti.
_STATE_FULLY_INSTALLED = 4

# Kapak resmi adayları, tercih sırasıyla (dikey kapak önce).
_COVER_NAMES = ("library_600x900.jpg", "library_capsule.jpg", "header.jpg", "library_header.jpg")


def find_steam_root() -> Path | None:
    """Steam'in kurulu olduğu klasörü döndürür; bulunamazsa None."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        import winreg

        for hive, key, value in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    candidates.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError:
                pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                candidates.append(Path(os.environ[env]) / "Steam")
    for path in candidates:
        if (path / "steamapps").is_dir():
            return path
    return None


def library_folders(steam_root: Path) -> list[Path]:
    """Steam'in bütün kütüphane klasörlerini (farklı disklerdekiler dahil) döndürür."""
    folders = [steam_root]
    vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        data = vdf.load(vdf_path)
    except (OSError, vdf.VDFError) as exc:
        log.warning("libraryfolders.vdf okunamadı: %s", exc)
        data = {}
    # Kök anahtar yeni sürümlerde "libraryfolders", eskilerde "LibraryFolders".
    for key, value in data.get("libraryfolders", {}).items():
        if not key.isdigit():
            continue
        # Yeni biçim: "1" { "path" "D:\\SteamLibrary" }   Eski biçim: "1" "D:\\SteamLibrary"
        raw = value.get("path") if isinstance(value, dict) else value
        if raw:
            folders.append(Path(raw))

    unique: list[Path] = []
    seen: set[str] = set()
    for folder in folders:
        norm = os.path.normcase(os.path.normpath(str(folder)))
        if norm not in seen and (folder / "steamapps").is_dir():
            seen.add(norm)
            unique.append(folder)
    return unique


def find_cover(steam_root: Path, appid: str) -> str:
    """Steam'in yerel önbelleğinden kapak resmi yolunu döndürür (yoksa "")."""
    # 1) Kullanıcının Steam'de kendi atadığı dikey kapak
    for grid in steam_root.glob("userdata/*/config/grid"):
        for ext in ("png", "jpg", "jpeg"):
            custom = grid / f"{appid}p.{ext}"
            if custom.is_file():
                return str(custom)

    cache = steam_root / "appcache" / "librarycache"
    app_dir = cache / appid
    for name in _COVER_NAMES:
        # 2) Eski düzen: librarycache/<appid>_library_600x900.jpg
        flat = cache / f"{appid}_{name}"
        if flat.is_file():
            return str(flat)
        # 3) Yeni düzen: librarycache/<appid>/[<hash>/]library_600x900.jpg
        if app_dir.is_dir():
            direct = app_dir / name
            if direct.is_file():
                return str(direct)
            nested = sorted(app_dir.glob(f"*/{name}"))
            if nested:
                return str(nested[0])
    return ""


def _is_tool(appid: str, name: str) -> bool:
    return appid in _TOOL_APPIDS or name.lower().startswith(_TOOL_NAME_PREFIXES)


def scan_steam(steam_root: Path | None = None) -> list[Game]:
    """Kurulu Steam oyunlarını döndürür. Steam yoksa boş liste döner."""
    steam_root = steam_root or find_steam_root()
    if steam_root is None:
        log.info("Steam bulunamadı.")
        return []

    games: dict[str, Game] = {}
    for library in library_folders(steam_root):
        steamapps = library / "steamapps"
        for manifest in sorted(steamapps.glob("appmanifest_*.acf")):
            try:
                state = vdf.load(manifest).get("appstate", {})
            except (OSError, vdf.VDFError) as exc:
                log.warning("%s okunamadı: %s", manifest.name, exc)
                continue
            appid = str(state.get("appid", "")).strip()
            name = str(state.get("name", "")).strip()
            installdir = str(state.get("installdir", "")).strip()
            if not appid or not name or _is_tool(appid, name):
                continue

            install_path = steamapps / "common" / installdir
            try:
                flags = int(state.get("stateflags", "0"))
            except ValueError:
                flags = 0
            # İndirmesi hiç başlamamış / silinmiş kayıtları atla.
            if not (flags & _STATE_FULLY_INSTALLED) and not install_path.is_dir():
                continue

            games[appid] = Game(
                source=SOURCE_STEAM,
                source_id=appid,
                name=name,
                install_dir=str(install_path),
                # Steam üzerinden başlatmak; bulut kaydı, DRM ve katmanlar düzgün çalışır.
                launch_uri=f"steam://rungameid/{appid}",
                cover_path=find_cover(steam_root, appid),
            )
    return list(games.values())
