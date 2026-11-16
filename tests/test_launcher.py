import pytest

from pwrhub import launcher
from pwrhub.models import SOURCE_MANUAL, SOURCE_STEAM, Game
from tests.conftest import make_exe


def test_store_games_open_launcher_uri(monkeypatch):
    opened = []
    monkeypatch.setattr(launcher, "_open_uri", opened.append)
    game = Game(source=SOURCE_STEAM, source_id="730", name="CS2", launch_uri="steam://rungameid/730")
    assert launcher.launch(game) is None
    assert opened == ["steam://rungameid/730"]


def test_manual_games_run_exe_in_its_folder(monkeypatch, tmp_path):
    exe = make_exe(tmp_path / "Oyun" / "oyun.exe")
    calls = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, cwd: calls.append((args, cwd)) or "proc")
    game = Game(source=SOURCE_MANUAL, source_id="x", name="Oyun", exe_path=str(exe))
    assert launcher.launch(game) == "proc"
    assert calls == [([str(exe)], str(exe.parent))]


def test_falls_back_to_exe_when_launcher_missing(monkeypatch, tmp_path):
    exe = make_exe(tmp_path / "g.exe")

    def fail(_uri):
        raise OSError("başlatıcı yok")

    monkeypatch.setattr(launcher, "_open_uri", fail)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, cwd: "proc")
    game = Game(source="epic", source_id="x", name="G", launch_uri="com.epicgames.launcher://x", exe_path=str(exe))
    assert launcher.launch(game) == "proc"


def test_missing_exe_gives_readable_error(tmp_path):
    game = Game(source=SOURCE_MANUAL, source_id="x", name="Yok", exe_path=str(tmp_path / "yok.exe"))
    with pytest.raises(launcher.LaunchError, match="bulunamadı"):
        launcher.launch(game)
    with pytest.raises(launcher.LaunchError):
        launcher.launch(Game(source=SOURCE_MANUAL, source_id="y", name="Boş"))
