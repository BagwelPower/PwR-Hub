from pwrhub.scanners.steam import library_folders, scan_steam
from tests.conftest import write_manifest


def test_finds_games_in_all_libraries(steam_root):
    games = {g.source_id: g for g in scan_steam(steam_root)}
    assert set(games) == {"730", "1145360"}  # araç (228980) listelenmez
    assert games["730"].name == "Counter-Strike 2"
    assert games["730"].launch_uri == "steam://rungameid/730"
    assert games["730"].install_dir.endswith("Counter-Strike Global Offensive")


def test_covers_from_old_and_new_cache_layout(steam_root):
    games = {g.source_id: g for g in scan_steam(steam_root)}
    assert games["730"].cover_path.endswith("730_library_600x900.jpg")
    assert games["1145360"].cover_path.endswith("library_600x900.jpg")
    assert "abc123" in games["1145360"].cover_path


def test_library_folders_deduplicated(steam_root):
    assert len(library_folders(steam_root)) == 2


def test_old_libraryfolders_format(steam_root, tmp_path):
    third = tmp_path / "Eski"
    write_manifest(third / "steamapps", "620", "Portal 2", "Portal 2")
    (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
        '"LibraryFolders"\n{\n\t"TimeNextStatsReport"\t"1"\n\t"1"\t"%s"\n}\n'
        % str(third).replace("\\", "\\\\"),
        encoding="utf-8",
    )
    assert {g.source_id for g in scan_steam(steam_root)} == {"730", "620"}


def test_skips_uninstalled_and_broken_manifests(steam_root):
    steamapps = steam_root / "steamapps"
    write_manifest(steamapps, "10", "Silinmiş Oyun", "Gone", flags=2)
    (steamapps / "common" / "Gone").rmdir()
    (steamapps / "appmanifest_99.acf").write_text('"AppState" {', encoding="utf-8")
    assert {g.source_id for g in scan_steam(steam_root)} == {"730", "1145360"}


def test_missing_steam_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("pwrhub.scanners.steam.find_steam_root", lambda: None)
    assert scan_steam() == []
