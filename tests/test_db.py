import pytest

from pwrhub.db import Database
from pwrhub.library import refresh_library
from pwrhub.models import SOURCE_MANUAL, SOURCE_STEAM, Game
from tests.conftest import make_exe


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def steam(appid, name, **kw):
    return Game(source=SOURCE_STEAM, source_id=appid, name=name, **kw)


def test_sync_adds_updates_and_marks_missing(db):
    db.sync_source(SOURCE_STEAM, [steam("1", "A"), steam("2", "B")])
    assert [g.name for g in db.list_games()] == ["A", "B"]

    db.sync_source(SOURCE_STEAM, [steam("1", "A Yeni Ad")])
    assert [g.name for g in db.list_games()] == ["A Yeni Ad"]  # 2 kaldırıldı -> listelenmez

    db.sync_source(SOURCE_STEAM, [steam("1", "A"), steam("2", "B")])
    assert len(db.list_games()) == 2  # yeniden kurulunca geri gelir


def test_user_choices_survive_rescan(db):
    db.sync_source(SOURCE_STEAM, [steam("1", "A", cover_path="steam.jpg")])
    game = db.list_games()[0]
    db.set_hidden(game.id, True)
    db.set_custom_cover(game.id, "benim.png")
    db.mark_launched(game.id)

    db.sync_source(SOURCE_STEAM, [steam("1", "A", cover_path="steam2.jpg")])
    assert db.list_games() == []
    game = db.list_games(include_hidden=True)[0]
    assert game.hidden and game.effective_cover == "benim.png" and game.last_launched_at
    assert game.cover_path == "steam2.jpg"


def test_manual_games_skip_steam_duplicates(db, tmp_path):
    shared = str(tmp_path / "common" / "Hades")
    db.sync_source(SOURCE_STEAM, [steam("1", "Hades", install_dir=shared)])
    db.sync_manual([
        Game(source=SOURCE_MANUAL, source_id="a", name="Hades", install_dir=shared),
        Game(source=SOURCE_MANUAL, source_id="b", name="Celeste", install_dir=str(tmp_path / "Celeste")),
    ])
    assert sorted((g.source, g.name) for g in db.list_games()) == [
        ("manual", "Celeste"), ("steam", "Hades"),
    ]


def test_refresh_library_end_to_end(db, tmp_path, steam_root, epic_manifests, monkeypatch):
    monkeypatch.setattr("pwrhub.scanners.steam.find_steam_root", lambda: steam_root)
    monkeypatch.setattr("pwrhub.scanners.epic.find_manifests_dir", lambda: epic_manifests)
    make_exe(tmp_path / "Oyunlar" / "Celeste" / "Celeste.exe")
    db.add_manual_path(str(tmp_path / "Oyunlar"), "folder")

    refresh_library(db)
    assert {g.name for g in db.list_games()} == {
        "Counter-Strike 2", "Hades", "Rocket League", "Celeste",
    }

    db.remove_manual_path(str(tmp_path / "Oyunlar"))
    refresh_library(db)
    assert "Celeste" not in {g.name for g in db.list_games()}
