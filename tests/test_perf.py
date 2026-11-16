"""3. aşama: performans örnekleri, zorlanma notu ve rapor."""

from datetime import datetime, timedelta

import pytest

from pwrhub import report
from pwrhub.db import Database
from pwrhub.models import SOURCE_STEAM, Game, Sample
from pwrhub.monitor import MonitorEngine, build_sample
from pwrhub.procscan import ProcInfo, SystemUsage

T0 = datetime(2026, 11, 16, 21, 0, 0)
GB = 1024 ** 3


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def sample(second, cpu=30.0, mem=50.0, disk=5.0, **extra) -> Sample:
    return Sample(ts=at(second), cpu=cpu, mem=mem, disk=disk, **extra)


# ------------------------------------------------------------------ tek ölçüm

def test_build_sample_splits_game_and_background():
    system = SystemUsage(cpu=80, mem=90, disk=40, mem_total=16 * GB)
    procs = [
        ProcInfo(1, "Hades.exe", cpu=35, rss=4 * GB),
        ProcInfo(2, "chrome.exe", cpu=10, rss=3 * GB),
        ProcInfo(3, "chrome.exe", cpu=15, rss=5 * GB),   # aynı program, toplanır
        ProcInfo(4, "discord.exe", cpu=5, rss=1 * GB),
    ]
    result = build_sample(T0, system, procs, game_pids={1}, io_rates={1: 2.0, 4: 30.0})
    assert (result.game_cpu, result.game_mem, result.game_disk) == (35, 25, 2.0)
    assert (result.top_cpu_name, result.top_cpu) == ("chrome.exe", 25)
    assert (result.top_mem_name, result.top_mem) == ("chrome.exe", 50)
    assert (result.top_disk_name, result.top_disk) == ("discord.exe", 30.0)


# ----------------------------------------------------------------- not ve rapor

def test_relaxed_session_scores_zero():
    result = report.analyze([sample(i * 3) for i in range(100)], "Hades")
    assert result.score == 0 and result.level == "good" and result.worst is None
    assert "hiç zorlanmadı" in result.lines[0]


def test_strain_thresholds():
    assert report.strain("cpu", 70) == 0
    assert report.strain("cpu", 85) == 50
    assert report.strain("mem", 100) == 100
    assert report.sample_strain(sample(0, cpu=50, mem=95, disk=10)) == (75, "mem")


def test_report_names_the_browser_at_the_worst_moment():
    samples = [sample(i * 3) for i in range(100)]
    # 21:40 civarında bellek %95; Chrome belleğin yarısını kullanıyor.
    for i in range(20):
        samples.append(sample(2400 + i * 3, mem=95, game_mem=30,
                              top_mem_name="chrome.exe", top_mem=48))
    result = report.analyze(samples, "Hades")

    assert result.worst.resource == "mem" and not result.worst.culprit_is_game
    assert result.worst.culprit == "Chrome (tarayıcı)"
    assert result.lines[0] == (
        "Saat 21:40 civarında bellek %95 seviyesine çıktı; o sırada Chrome (tarayıcı) "
        "belleğin %48 kadarını tek başına kullanıyordu."
    )
    assert any("Chrome (tarayıcı) programını kapatmak" in line for line in result.lines)
    assert 25 <= result.score < 75
    assert round(result.over_threshold["mem"]) == 17
    assert result.peak["mem"] == 95 and round(result.average["mem"], 1) == 57.5


def test_game_itself_blamed_when_it_uses_the_most():
    samples = [sample(i * 3, cpu=98, game_cpu=85, top_cpu_name="discord.exe", top_cpu=4)
               for i in range(50)]
    result = report.analyze(samples, "Hades")
    assert result.worst.culprit_is_game and result.worst.culprit == "Hades"
    assert result.score >= 75 and result.label == "Çok zorlandı"
    assert "oyunun kendisi" in result.lines[0]
    assert any("grafik ayarlarını" in line for line in result.lines)


def test_no_samples_no_report():
    assert report.analyze([], "Hades") is None


def test_friendly_names():
    assert report.friendly_name("MsMpEng.exe") == "Windows Defender (virüs taraması)"
    assert report.friendly_name("BilinmeyenProgram.exe") == "BilinmeyenProgram"


# ------------------------------------------------------------- uçtan uca motor

class FakeScanner:
    """Sıradaki süreç listesini döndüren sahte tarayıcı."""

    def __init__(self):
        self.procs: list[ProcInfo] = []
        self.calls: list[bool] = []

    def scan(self, detailed=False):
        self.calls.append("scan")
        # Gerçek tarayıcı gibi her turda yeni, ölçülmemiş kayıtlar döndürür.
        return [ProcInfo(p.pid, p.name, p.exe) for p in self.procs]

    def measure(self, procs):
        """Ölçüm istenen süreçlerin değerlerini doldurur ve kaçını ölçtüğünü not eder."""
        self.calls.append(len(procs))
        source = {p.pid: p for p in self.procs}
        for item in procs:
            real = source[item.pid]
            item.cpu, item.rss, item.io_bytes, item.measured = real.cpu, real.rss, real.io_bytes, True


class FakeSystem:
    def __init__(self):
        self.usage = SystemUsage(cpu=40, mem=60, disk=10, mem_total=16 * GB)

    def read(self):
        return self.usage


@pytest.fixture
def engine(tmp_path):
    db = Database(tmp_path / "m.db")
    db.sync_source(SOURCE_STEAM, [
        Game(source=SOURCE_STEAM, source_id="1", name="Hades", install_dir="/lib/Hades"),
    ])
    scanner, system = FakeScanner(), FakeSystem()
    yield MonitorEngine(db, scanner, system), db, scanner, system
    db.close()


def test_engine_records_session_samples_and_score(engine):
    eng, db, scanner, system = engine
    game = ProcInfo(10, "Hades.exe", "/lib/Hades/Hades.exe", cpu=30, rss=4 * GB, io_bytes=0)
    chrome = ProcInfo(20, "chrome.exe", "/apps/chrome.exe", cpu=5, rss=8 * GB, io_bytes=0)

    eng.tick(at(0))                                   # oyun yok: hafif tarama
    assert scanner.calls == ["scan"] and eng.interval == 5.0      # oyun yokken ölçüm yapılmaz

    scanner.procs = [game, chrome]
    events = eng.tick(at(5))
    assert [e.kind for e in events] == ["started"] and eng.interval == 3.0

    system.usage = SystemUsage(cpu=45, mem=96, disk=10, mem_total=16 * GB)
    for step in range(1, 41):
        game.io_bytes += 3 * 1024 * 1024              # 3 sn'de 3 MB -> 1 MB/sn
        eng.tick(at(5 + step * 3))
    measured = [c for c in scanner.calls if c != "scan"]
    # İlk iki turda ve sonra dört turda bir herkes (2), aralarda yalnızca oyun (1) ölçülür.
    assert measured[:9] == [2, 2, 1, 1, 2, 1, 1, 1, 2] and len(measured) == 40

    scanner.procs = [chrome]
    eng.tick(at(130))
    events = eng.tick(at(170))
    assert [e.kind for e in events] == ["ended"]

    session = db.list_sessions()[0]
    samples = db.list_samples(session.id)
    assert len(samples) == 39                         # ilk ayrıntılı ölçüm başlangıç noktasıdır
    assert samples[0].game_mem == 25 and samples[0].top_mem_name == "chrome.exe"
    assert samples[0].game_disk == pytest.approx(1.0)
    assert session.duration_s == 120
    assert session.strain_score == 80                 # bellek %96 -> zorlanma 80
    assert db.get_game(session.game_id).total_seconds == 120


def test_engine_shutdown_closes_running_session(engine):
    eng, db, scanner, _system = engine
    scanner.procs = [ProcInfo(10, "Hades.exe", "/lib/Hades/Hades.exe")]
    for second in range(0, 61, 3):
        eng.tick(at(second))
    eng.shutdown()
    assert eng.active == {}
    assert db.list_sessions()[0].duration_s == 60
