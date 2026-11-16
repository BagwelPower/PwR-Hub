"""2. aşama: süreç eşleştirme, oturum takibi ve istatistik hesapları."""

from datetime import date, datetime, timedelta

import pytest

from pwrhub import stats
from pwrhub.db import Database
from pwrhub.matching import GameMatcher, norm_path
from pwrhub.models import SOURCE_MANUAL, SOURCE_STEAM, Game, Session
from pwrhub.procscan import ProcInfo
from pwrhub.sessions import SessionTracker

T0 = datetime(2026, 11, 16, 20, 0, 0)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "t.db")
    database.sync_source(SOURCE_STEAM, [
        Game(source=SOURCE_STEAM, source_id="1", name="Hades", install_dir="/lib/common/Hades"),
        Game(source=SOURCE_STEAM, source_id="2", name="Celeste", install_dir="/lib/common/Celeste"),
    ])
    yield database
    database.close()


def ids(db):
    return {g.name: g.id for g in db.list_games()}


# ------------------------------------------------------------------ eşleştirme

def test_matches_processes_inside_install_dir(db):
    games = db.list_games()
    matcher = GameMatcher(games)
    procs = [
        ProcInfo(1, "Hades.exe", "/lib/common/Hades/x64/Hades.exe"),
        ProcInfo(2, "chrome.exe", "/apps/chrome.exe"),
        ProcInfo(3, "UnityCrashHandler64.exe", "/lib/common/Celeste/UnityCrashHandler64.exe"),
        ProcInfo(4, "HadesX.exe", "/lib/common/HadesX/HadesX.exe"),  # benzer adlı başka klasör
    ]
    found = matcher.match(procs)
    assert list(found) == [ids(db)["Hades"]]      # yalnızca çökme raporlayıcısı çalışan Celeste sayılmaz
    assert [p.pid for p in found[ids(db)["Hades"]]] == [1]


def test_single_exe_game_matches_only_that_file(tmp_path):
    exe = str(tmp_path / "Downloads" / "oyun.exe")
    game = Game(id=7, source=SOURCE_MANUAL, source_id=norm_path(exe), name="Oyun",
                install_dir=str(tmp_path / "Downloads"), exe_path=exe)
    matcher = GameMatcher([game])
    assert matcher.game_for(ProcInfo(1, "oyun.exe", exe)) == 7
    assert matcher.game_for(ProcInfo(2, "kurulum.exe", str(tmp_path / "Downloads" / "kurulum.exe"))) is None
    # Dosya yolu okunamayan (korumalı) süreç adından tanınır.
    assert matcher.game_for(ProcInfo(3, "OYUN.EXE", "")) == 7


# --------------------------------------------------------------- oturum takibi

def test_session_recorded_from_start_to_close(db):
    hades = ids(db)["Hades"]
    tracker = SessionTracker(db)
    events = tracker.update({hades}, at(0))
    assert [(e.kind, e.game_id) for e in events] == [("started", hades)]
    for second in range(5, 601, 5):
        tracker.update({hades}, at(second))
    assert tracker.update(set(), at(605)) == []            # bekleme süresi içinde
    events = tracker.update(set(), at(640))
    assert [(e.kind, e.session_id is not None) for e in events] == [("ended", True)]

    game = db.get_game(hades)
    assert game.session_count == 1 and game.total_seconds == 600
    assert game.last_played_at == at(600).isoformat()
    assert tracker.active == {}


def test_brief_disappearance_keeps_same_session(db):
    hades = ids(db)["Hades"]
    tracker = SessionTracker(db)
    tracker.update({hades}, at(0))
    tracker.update({hades}, at(60))
    tracker.update(set(), at(70))          # başlatıcıdan oyuna geçiş
    tracker.update({hades}, at(80))
    tracker.update(set(), at(200))
    assert db.get_game(hades).session_count == 1
    assert db.get_game(hades).total_seconds == 80


def test_too_short_sessions_are_dropped(db):
    hades = ids(db)["Hades"]
    tracker = SessionTracker(db)
    tracker.update({hades}, at(0))
    tracker.update({hades}, at(5))
    events = tracker.update(set(), at(60))
    assert events[0].kind == "ended" and events[0].session_id is None
    assert db.get_game(hades).session_count == 0


def test_resumes_after_app_restart_and_survives_crash(db):
    hades = ids(db)["Hades"]
    first = SessionTracker(db)
    first.update({hades}, at(0))
    first.update({hades}, at(300))
    # PwR Hub burada çöktü: oturum yine de 300 saniye olarak kayıtlı.
    assert db.get_game(hades).total_seconds == 300

    second = SessionTracker(db)                # uygulama yeniden açıldı, oyun hâlâ açık
    second.update({hades}, at(330))
    second.update({hades}, at(400))
    second.close_all()
    assert db.get_game(hades).session_count == 1
    assert db.get_game(hades).total_seconds == 400


def test_two_games_tracked_independently(db):
    hades, celeste = ids(db)["Hades"], ids(db)["Celeste"]
    tracker = SessionTracker(db)
    tracker.update({hades}, at(0))
    tracker.update({hades, celeste}, at(100))
    tracker.update({celeste}, at(200))
    tracker.update({celeste}, at(400))
    tracker.close_all()
    assert db.get_game(hades).total_seconds == 100
    assert db.get_game(celeste).total_seconds == 300
    assert [g.name for g in db.top_games()] == ["Celeste", "Hades"]


# ------------------------------------------------------------------ istatistik

def session(start: datetime, minutes: float) -> Session:
    end = start + timedelta(minutes=minutes)
    return Session(1, 1, start, end, int(minutes * 60))


def test_format_duration():
    assert stats.format_duration(0) == "0 dk"
    assert stats.format_duration(30) == "1 dk'dan az"
    assert stats.format_duration(45 * 60) == "45 dk"
    assert stats.format_duration(2 * 3600) == "2 sa"
    assert stats.format_duration(8100) == "2 sa 15 dk"


def test_session_crossing_midnight_is_split_between_days():
    per_day = stats.seconds_per_day([session(datetime(2026, 11, 14, 23, 30), 90)])
    assert per_day == {date(2026, 11, 14): 1800, date(2026, 11, 15): 3600}


def test_daily_and_weekly_bars():
    today = date(2026, 11, 16)  # Pazartesi
    sessions = [
        session(datetime(2026, 11, 16, 20, 0), 60),
        session(datetime(2026, 11, 15, 10, 0), 30),   # geçen haftanın Pazar günü
        session(datetime(2026, 11, 10, 10, 0), 120),
        session(datetime(2026, 9, 1, 10, 0), 500),    # pencerenin dışında
    ]
    daily = stats.daily_bars(sessions, days=7, today=today)
    assert [b.label for b in daily] == ["Sal", "Çar", "Per", "Cum", "Cmt", "Paz", "Pzt"]
    assert [b.seconds for b in daily] == [7200, 0, 0, 0, 0, 1800, 3600]

    weekly = stats.weekly_bars(sessions, weeks=2, today=today)
    assert [b.label for b in weekly] == ["9 Kas", "16 Kas"]
    assert [b.seconds for b in weekly] == [9000, 3600]
    assert stats.total_between(sessions, date(2026, 11, 16), today) == 3600


def test_format_date():
    today = date(2026, 11, 16)
    assert stats.format_date(datetime(2026, 11, 16, 21, 40), today) == "Bugün 21:40"
    assert stats.format_date(datetime(2026, 11, 15, 9, 5), today) == "Dün 09:05"
    assert stats.format_date(datetime(2026, 11, 3, 9, 5), today) == "3 Kas"
    assert stats.format_date(datetime(2025, 1, 3, 9, 5), today) == "3 Oca 2025"
