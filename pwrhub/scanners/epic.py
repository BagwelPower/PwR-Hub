"""Epic Games Launcher ile kurulan oyunları yerel dosyalardan bulur.

Epic, kurulu her uygulama için şu klasöre bir `.item` (JSON) dosyası yazar:
    %PROGRAMDATA%\\Epic\\EpicGamesLauncher\\Data\\Manifests
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import quote

from pwrhub.models import SOURCE_EPIC, Game

log = logging.getLogger(__name__)


def find_manifests_dir() -> Path | None:
    """Epic manifest klasörünü döndürür; bulunamazsa None."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\Epic Games\EpicGamesLauncher",
            ) as handle:
                app_data = winreg.QueryValueEx(handle, "AppDataPath")[0]
                candidates.append(Path(app_data) / "Manifests")
        except OSError:
            pass
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        candidates.append(Path(program_data) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests")
    for path in candidates:
        if path.is_dir():
            return path
    return None


def _launch_uri(item: dict) -> str:
    """Epic Launcher'a oyunu başlatmasını söyleyen adresi kurar."""
    app_name = item.get("AppName", "")
    namespace = item.get("CatalogNamespace", "")
    catalog_id = item.get("CatalogItemId", "")
    # Yeni launcher sürümleri üçlü kimlik bekliyor; eksikse yalnızca AppName kullanılır.
    app_ref = ":".join((namespace, catalog_id, app_name)) if namespace and catalog_id else app_name
    return f"com.epicgames.launcher://apps/{quote(app_ref, safe='')}?action=launch&silent=true"


def scan_epic(manifests_dir: Path | None = None) -> list[Game]:
    """Kurulu Epic oyunlarını döndürür. Epic yoksa boş liste döner."""
    manifests_dir = manifests_dir or find_manifests_dir()
    if manifests_dir is None:
        log.info("Epic Games Launcher bulunamadı.")
        return []

    games: dict[str, Game] = {}
    for path in sorted(manifests_dir.glob("*.item")):
        try:
            item = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("%s okunamadı: %s", path.name, exc)
            continue
        if not isinstance(item, dict):
            continue

        app_name = str(item.get("AppName", "")).strip()
        name = str(item.get("DisplayName", "")).strip()
        install_dir = str(item.get("InstallLocation", "")).strip()
        if not app_name or not name or not install_dir:
            continue
        if item.get("bIsIncompleteInstall"):
            continue  # indirme bitmemiş
        # Ek paketler (DLC) ana oyunun adını taşır; ayrı kart olarak göstermeyiz.
        main_game = item.get("MainGameAppName") or app_name
        if main_game != app_name:
            continue
        # Unreal Engine gibi oyun olmayan uygulamaları ele.
        categories = item.get("AppCategories")
        if isinstance(categories, list) and categories and "games" not in categories:
            continue

        exe = str(item.get("LaunchExecutable", "")).strip()
        games[app_name] = Game(
            source=SOURCE_EPIC,
            source_id=app_name,
            name=name,
            install_dir=install_dir,
            exe_path=str(Path(install_dir) / exe) if exe else "",
            launch_uri=_launch_uri(item),
        )
    return list(games.values())
