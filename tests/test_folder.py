from pathlib import Path

from pwrhub.scanners.folder import best_exe, scan_exe, scan_folder
from tests.conftest import make_exe


def test_library_folder_lists_each_subfolder(tmp_path):
    make_exe(tmp_path / "Hollow_Knight" / "hollow_knight.exe", 500)
    make_exe(tmp_path / "Hollow_Knight" / "UnityCrashHandler64.exe", 900)
    make_exe(tmp_path / "Celeste" / "Celeste.exe")
    (tmp_path / "Belgeler").mkdir()  # exe yok -> oyun değil
    games = scan_folder(tmp_path)
    assert [g.name for g in games] == ["Celeste", "Hollow Knight"]
    assert Path(games[1].exe_path).name == "hollow_knight.exe"


def test_folder_with_exe_is_single_game(tmp_path):
    game_dir = tmp_path / "Stardew Valley"
    make_exe(game_dir / "Stardew Valley.exe")
    make_exe(game_dir / "tools" / "ModdingTool.exe")
    games = scan_folder(game_dir)
    assert len(games) == 1 and games[0].name == "Stardew Valley"


def test_best_exe_ignores_installers_and_redists(tmp_path):
    game = tmp_path / "MyGame"
    make_exe(game / "unins000.exe", 3000)
    make_exe(game / "_CommonRedist" / "vcredist" / "big_thing.exe", 9000)
    make_exe(game / "Binaries" / "Win64" / "MyGame-Win64-Shipping.exe", 4000)
    assert best_exe(game).name == "MyGame-Win64-Shipping.exe"


def test_best_exe_prefers_name_match_over_size(tmp_path):
    game = tmp_path / "Terraria"
    make_exe(game / "Terraria.exe", 100)
    make_exe(game / "dedicated_server_tool.exe", 400)
    assert best_exe(game).name == "Terraria.exe"


def test_scan_exe_and_missing_paths(tmp_path):
    exe = make_exe(tmp_path / "Among_Us.exe")
    game = scan_exe(exe)
    assert game.name == "Among Us" and game.install_dir == str(tmp_path)
    assert scan_exe(tmp_path / "yok.exe") is None
    assert scan_folder(tmp_path / "yok") == []
