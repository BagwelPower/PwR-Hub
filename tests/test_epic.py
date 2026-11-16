from pathlib import Path

from pwrhub.scanners.epic import scan_epic


def test_only_real_installed_games(epic_manifests):
    games = scan_epic(epic_manifests)
    assert [g.name for g in games] == ["Rocket League"]  # DLC, yarım kurulum, motor, bozuk dosya elenir
    game = games[0]
    assert game.source_id == "Sugar"
    assert game.launch_uri == (
        "com.epicgames.launcher://apps/ns%3Aitem%3ASugar?action=launch&silent=true"
    )
    assert Path(game.exe_path).name == "Game.exe"


def test_missing_epic_returns_empty(monkeypatch):
    monkeypatch.setattr("pwrhub.scanners.epic.find_manifests_dir", lambda: None)
    assert scan_epic() == []
