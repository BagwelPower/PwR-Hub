"""Testler için ortak yardımcılar: geçici klasörde sahte Steam/Epic kurulumları."""

import json
import os
from pathlib import Path

import pytest

# Arayüz testleri ekran olmadan çalışabilsin.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def write_manifest(steamapps: Path, appid: str, name: str, installdir: str, flags: int = 4) -> None:
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / f"appmanifest_{appid}.acf").write_text(
        f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n'
        f'\t"StateFlags"\t\t"{flags}"\n\t"installdir"\t\t"{installdir}"\n}}\n',
        encoding="utf-8",
    )
    (steamapps / "common" / installdir).mkdir(parents=True, exist_ok=True)


def make_exe(path: Path, size_kb: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * (size_kb * 1024))
    return path


@pytest.fixture
def steam_root(tmp_path: Path) -> Path:
    """İki kütüphane klasörlü sahte bir Steam kurulumu."""
    root = tmp_path / "Steam"
    second = tmp_path / "SteamLibrary"
    write_manifest(root / "steamapps", "730", "Counter-Strike 2", "Counter-Strike Global Offensive")
    write_manifest(root / "steamapps", "228980", "Steamworks Common Redistributables", "Steamworks Shared")
    write_manifest(second / "steamapps", "1145360", "Hades", "Hades")
    escaped = str(second).replace("\\", "\\\\")
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n'
        '\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t\t"apps"\n\t\t{\n\t\t\t"1145360"\t\t"123"\n\t\t}\n\t}\n}\n'
        % (str(root).replace("\\", "\\\\"), escaped),
        encoding="utf-8",
    )
    cache = root / "appcache" / "librarycache"
    cache.mkdir(parents=True)
    (cache / "730_library_600x900.jpg").write_bytes(b"jpg")
    (cache / "1145360" / "abc123").mkdir(parents=True)
    (cache / "1145360" / "abc123" / "library_600x900.jpg").write_bytes(b"jpg")
    return root


@pytest.fixture
def epic_manifests(tmp_path: Path) -> Path:
    """Bir oyun, bir DLC, bir yarım kurulum ve bir motor içeren Epic manifestleri."""
    folder = tmp_path / "Manifests"
    folder.mkdir()
    base = {
        "CatalogNamespace": "ns", "CatalogItemId": "item",
        "InstallLocation": str(tmp_path / "Epic" / "Game"),
        "LaunchExecutable": "Game.exe", "AppCategories": ["public", "games", "applications"],
    }
    items = {
        "game": {**base, "AppName": "Sugar", "DisplayName": "Rocket League", "MainGameAppName": "Sugar"},
        "dlc": {**base, "AppName": "SugarDLC", "DisplayName": "RL Paketi", "MainGameAppName": "Sugar"},
        "partial": {**base, "AppName": "Half", "DisplayName": "Yarım Oyun", "bIsIncompleteInstall": True},
        "engine": {**base, "AppName": "UE_5.3", "DisplayName": "Unreal Engine", "AppCategories": ["engines"]},
    }
    for name, item in items.items():
        (folder / f"{name}.item").write_text(json.dumps(item), encoding="utf-8")
    (folder / "broken.item").write_text("{bozuk json", encoding="utf-8")
    return folder
