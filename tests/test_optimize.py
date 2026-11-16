"""Tek çekirdek ve ekran kartı ölçümü, Oyun Modu, program kapatma, ayarlar."""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

import psutil
import pytest

from pwrhub import boost, gpu, optimizer, report
from pwrhub.db import Database
from pwrhub.matching import GameMatcher
from pwrhub.models import SOURCE_STEAM, Game, Sample
from pwrhub.monitor import MonitorEngine, build_sample
from pwrhub.procscan import ProcInfo, SystemReader, SystemUsage
from tests.conftest import make_exe
from tests.test_perf import FakeScanner, FakeSystem

T0 = datetime(2026, 11, 16, 21, 0, 0)
GB = 1024 ** 3


def sample(second, cpu=30.0, mem=50.0, disk=5.0, **extra) -> Sample:
    return Sample(ts=T0 + timedelta(seconds=second), cpu=cpu, mem=mem, disk=disk, **extra)


# ------------------------------------------------------------ tek çekirdek

def test_system_reader_reports_busiest_core():
    usage = SystemReader().read()
    assert 0 <= usage.cpu <= usage.cpu_core <= 100


def test_single_core_bottleneck_is_reported():
    # Toplam işlemci %25 ama bir çekirdek sürekli %100: eskiden "rahat" görünürdü.
    samples = [sample(i * 3, cpu=25, cpu_core=100, game_cpu=24, top_cpu_name="discord.exe", top_cpu=1)
               for i in range(100)]
    result = report.analyze(samples, "Hades")
    assert result.worst.resource == "core" and result.worst.culprit_is_game
    assert result.score == 60 and result.label == "Zorlandı"      # çekirdeğin üst sınırı 60
    assert "bir çekirdeği %100" in result.lines[0] and "yalnızca %25" in result.lines[0]
    assert any("tek bir işlemci çekirdeğine yükleniyor" in line for line in result.lines)
    assert round(result.over_threshold["core"]) == 100


def test_full_cpu_outranks_single_core():
    assert report.sample_strain(sample(0, cpu=100, cpu_core=100)) == (100, "cpu")


# ------------------------------------------------------------- ekran kartı

def test_gpu_counter_aggregation():
    items = [
        ("pid_10_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 70.0),
        ("pid_20_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 20.0),
        ("pid_20_luid_0x0_0x1_phys_0_eng_1_engtype_VideoDecode", 35.0),
        ("pid_30_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 0.0),
        ("anlamsız", 50.0),
    ]
    total, per_pid = gpu.aggregate(items)
    assert total == 90.0                       # en meşgul motor: 3D (70 + 20)
    assert per_pid == {10: 70.0, 20: 35.0}
    assert gpu.aggregate([]) == (0.0, {})


def test_gpu_reader_is_silent_when_unavailable():
    reader = gpu.GpuReader()
    if sys.platform != "win32":
        assert not reader.available and reader.read() is None


def test_build_sample_includes_gpu_and_core():
    system = SystemUsage(cpu=40, mem=50, disk=5, mem_total=16 * GB, cpu_core=97,
                         gpu=95, gpu_by_pid={1: 80, 2: 10})
    procs = [ProcInfo(1, "Hades.exe", cpu=30), ProcInfo(2, "obs64.exe", cpu=5)]
    result = build_sample(T0, system, procs, {1}, {})
    assert (result.cpu_core, result.gpu, result.game_gpu) == (97, 95, 80)
    assert (result.top_gpu_name, result.top_gpu) == ("obs64.exe", 10)


def test_gpu_bound_session_report():
    samples = [sample(i * 3, gpu=99, game_gpu=93) for i in range(100)]
    result = report.analyze(samples, "Hades")
    assert result.has_gpu and result.worst.resource == "gpu"
    assert result.score == 45 and result.level == "warning"       # ekran kartının üst sınırı 50
    assert "ekran kartı %99" in result.lines[0]
    assert any("Çözünürlüğü" in line for line in result.lines)
    assert not any("ölçülemedi" in line for line in result.lines)


def test_report_says_when_gpu_was_not_measured():
    result = report.analyze([sample(0), sample(3)], "Hades")
    assert not result.has_gpu and "ekran kartı ölçülemedi" in result.lines[-1]


# -------------------------------------------------------- veritabanı, ayarlar

def test_old_database_is_upgraded_and_samples_roundtrip(tmp_path):
    path = tmp_path / "eski.db"
    old = sqlite3.connect(path)   # 3. aşamadaki, yeni sütunları olmayan tablo
    old.execute("""CREATE TABLE samples (session_id INTEGER, ts TEXT, cpu REAL, mem REAL, disk REAL,
        game_cpu REAL, game_mem REAL, game_disk REAL, top_cpu_name TEXT, top_cpu REAL,
        top_mem_name TEXT, top_mem REAL, top_disk_name TEXT, top_disk REAL)""")
    old.execute("INSERT INTO samples VALUES (1, '2026-11-01T20:00:00', 10, 20, 30, 1, 2, 3, 'a', 4, 'b', 5, 'c', 6)")
    old.commit()
    old.close()

    db = Database(path)
    db.add_sample(1, sample(60, cpu_core=88, gpu=77, game_gpu=60, top_gpu_name="obs64.exe", top_gpu=9))
    first, second = db.list_samples(1)
    assert (first.cpu, first.cpu_core, first.gpu) == (10, 0, None)     # eski kayıt korunur
    assert (second.cpu_core, second.gpu, second.top_gpu_name) == (88, 77, "obs64.exe")

    assert db.get_flag("yok") is False and db.get_flag("yok", True) is True
    db.set_flag("x", True)
    db.set_setting("y", "değer")
    assert db.get_flag("x") and db.get_setting("y") == "değer"
    db.close()


def test_protected_game_matched_by_exe_name(tmp_path):
    install = tmp_path / "Valorant"
    make_exe(install / "live" / "VALORANT-Win64-Shipping.exe")
    game = Game(id=3, source=SOURCE_STEAM, source_id="3", name="Valorant", install_dir=str(install))
    plain = GameMatcher([game])
    assert plain.game_for(ProcInfo(1, "VALORANT-Win64-Shipping.exe", "")) is None
    named = GameMatcher([game], {3: {"valorant-win64-shipping.exe"}})
    assert named.game_for(ProcInfo(1, "VALORANT-Win64-Shipping.exe", "")) == 3


# ------------------------------------------------------------------ Oyun Modu

class FakeBackend(boost.SystemBackend):
    def __init__(self, plan="dengeli-plan", has_high_performance=True):
        self.plan = plan
        self.has_high_performance = has_high_performance
        self.priorities: dict[int, str] = {}
        self.log: list[tuple] = []

    def set_priority(self, pid, level):
        self.log.append(("set", pid, level))
        previous = self.priorities.get(pid, "normal")
        self.priorities[pid] = level
        return previous

    def restore_priority(self, pid, previous):
        self.log.append(("restore", pid, previous))
        self.priorities[pid] = previous

    def get_power_plan(self):
        return self.plan

    def set_power_plan(self, guid):
        if guid == boost.HIGH_PERFORMANCE_PLAN and not self.has_high_performance:
            return False
        self.plan = guid
        return True


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "b.db")
    database.sync_source(SOURCE_STEAM, [
        Game(source=SOURCE_STEAM, source_id="1", name="Hades", install_dir="/lib/Hades"),
    ])
    yield database
    database.close()


GAME = ProcInfo(10, "Hades.exe", "/lib/Hades/Hades.exe")
CHROME = ProcInfo(20, "chrome.exe", "/apps/chrome.exe")
DISCORD = ProcInfo(30, "Discord.exe", "/apps/Discord.exe")


def test_game_mode_is_off_by_default(db):
    backend = FakeBackend()
    booster = boost.Booster(db, backend)
    booster.apply([GAME], [GAME, CHROME])
    assert not booster.active and backend.log == [] and backend.plan == "dengeli-plan"


def test_game_mode_applies_and_restores_everything(db):
    db.set_flag(boost.KEY_ENABLED, True)
    backend = FakeBackend()
    booster = boost.Booster(db, backend)

    booster.apply([GAME], [GAME, CHROME, DISCORD])
    assert backend.priorities == {10: "high", 20: "low"}        # Discord'a dokunulmaz
    assert backend.plan == boost.HIGH_PERFORMANCE_PLAN
    assert db.get_setting(boost.KEY_SAVED_PLAN) == "dengeli-plan"

    late = ProcInfo(11, "Hades-Win64.exe", "/lib/Hades/Hades-Win64.exe")
    booster.apply([GAME, late], [GAME, late, CHROME])           # sonradan açılan süreç
    assert backend.priorities[11] == "high"
    assert [entry for entry in backend.log if entry[:2] == ("set", 10)] == [("set", 10, "high")]

    booster.release()
    assert backend.priorities == {10: "normal", 11: "normal", 20: "normal"}
    assert backend.plan == "dengeli-plan" and db.get_setting(boost.KEY_SAVED_PLAN) == ""
    assert not booster.active


def test_game_mode_respects_individual_options(db):
    db.set_flag(boost.KEY_ENABLED, True)
    db.set_flag(boost.KEY_BACKGROUND, False)
    db.set_flag(boost.KEY_POWER_PLAN, False)
    backend = FakeBackend()
    boost.Booster(db, backend).apply([GAME], [GAME, CHROME])
    assert backend.priorities == {10: "high"} and backend.plan == "dengeli-plan"


def test_power_plan_restored_after_crash_and_missing_plan_tolerated(db):
    db.set_flag(boost.KEY_ENABLED, True)
    backend = FakeBackend()
    boost.Booster(db, backend).apply([GAME], [GAME])            # ...ve uygulama çöktü
    assert backend.plan == boost.HIGH_PERFORMANCE_PLAN

    boost.Booster(db, backend)                                  # yeniden açılış
    assert backend.plan == "dengeli-plan"

    laptop = FakeBackend(has_high_performance=False)
    boost.Booster(db, laptop).apply([GAME], [GAME])
    assert laptop.plan == "dengeli-plan" and db.get_setting(boost.KEY_SAVED_PLAN) == ""


def test_turning_game_mode_off_mid_game_restores_immediately(db):
    db.set_flag(boost.KEY_ENABLED, True)
    backend = FakeBackend()
    booster = boost.Booster(db, backend)
    booster.apply([GAME], [GAME])
    db.set_flag(boost.KEY_ENABLED, False)
    booster.apply([GAME], [GAME])
    assert backend.priorities == {10: "normal"} and backend.plan == "dengeli-plan"


def test_engine_drives_game_mode(db):
    db.set_flag(boost.KEY_ENABLED, True)
    scanner, backend = FakeScanner(), FakeBackend()
    engine = MonitorEngine(db, scanner, FakeSystem(), backend)
    scanner.procs = [GAME, CHROME]
    for second in range(0, 61, 3):
        engine.tick(T0 + timedelta(seconds=second))
    assert backend.priorities == {10: "high", 20: "low"}

    scanner.procs = [CHROME]
    engine.tick(T0 + timedelta(seconds=63))
    assert backend.plan == boost.HIGH_PERFORMANCE_PLAN          # bekleme süresinde hâlâ açık
    engine.tick(T0 + timedelta(seconds=100))
    assert backend.priorities == {10: "normal", 20: "normal"} and backend.plan == "dengeli-plan"


# ------------------------------------------------------- program listesi/kapatma

def test_top_programs_groups_ranks_and_protects():
    procs = [
        ProcInfo(1, "chrome.exe", cpu=5, rss=2 * GB),
        ProcInfo(2, "chrome.exe", cpu=7, rss=2 * GB),
        ProcInfo(3, "svchost.exe", cpu=1, rss=1 * GB),
        ProcInfo(4, "Hades.exe", cpu=60, rss=6 * GB),          # oyun: listede olmaz
        ProcInfo(5, "notepad.exe", cpu=0, rss=1024),           # ihmal edilebilir
        ProcInfo(os.getpid(), "python.exe", cpu=9, rss=GB),    # PwR Hub'ın kendisi
    ]
    programs = optimizer.top_programs(procs, 16 * GB, exclude_pids={4})
    assert [(p.name, p.closable) for p in programs] == [("chrome.exe", True), ("svchost.exe", False)]
    chrome = programs[0]
    assert (chrome.title, chrome.cpu, chrome.mem, chrome.pids) == ("Chrome (tarayıcı)", 12, 25, [1, 2])


def test_close_program_terminates_only_matching_processes():
    # Her işletim sisteminde çalışsın diye "kurban" olarak bekleyen bir Python süreci.
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        name = psutil.Process(victim.pid).name()
    except OSError:
        victim.kill()
        pytest.skip("Bu ortamda süreç adları okunamıyor")
    try:
        system = optimizer.ProgramUsage("svchost.exe", "svchost", pids=[victim.pid], closable=False)
        assert optimizer.close_program(system) == (0, 1) and victim.poll() is None

        renamed = optimizer.ProgramUsage("baska.exe", "Başka", pids=[victim.pid])
        assert optimizer.close_program(renamed) == (0, 0) and victim.poll() is None   # numara başkasına ait

        real = optimizer.ProgramUsage(name, name, pids=[victim.pid, 999999])
        assert optimizer.close_program(real) == (1, 0)
        assert victim.wait(timeout=5) is not None
    finally:
        victim.kill()


# ------------------------------------------ ekran kartı belleği (VRAM), sıcaklık

def test_vram_counter_aggregation():
    adapters = [("luid_0x0_0x1_phys_0", 6.0 * GB), ("luid_0x0_0x2_phys_0", 0.2 * GB)]
    processes = [("pid_10_luid_0x0_0x1_phys_0", 5.0 * GB), ("pid_20_luid_0x0_0x1_phys_0", 0.5 * GB),
                 ("pid_30_luid_0x0_0x1_phys_0", 0.0)]
    used, per_pid = gpu.aggregate_memory(adapters, processes)
    assert used == 6 * GB and per_pid == {10: 5 * GB, 20: GB // 2}
    assert gpu.aggregate_memory([], []) == (None, {})

    usage = gpu.GpuUsage(vram_used=6 * GB, vram_total=8 * GB)
    assert usage.vram_percent == 75
    assert gpu.GpuUsage(vram_used=6 * GB).vram_percent is None      # toplam bilinmiyor


def test_nvidia_smi_output_parsing():
    assert gpu.parse_nvidia_smi("65, 3012, 8192\n") == (65.0, 3012 * 1024 ** 2, 8192 * 1024 ** 2)
    two_cards = "40, 100, 4096\n71, 7000, 12288\n"
    assert gpu.parse_nvidia_smi(two_cards)[0] == 71.0                # belleği dolu olan kart
    assert gpu.parse_nvidia_smi("[N/A], [N/A], [N/A]\n") is None
    assert gpu.parse_nvidia_smi("") is None


def test_implausible_temperatures_are_ignored():
    assert gpu.plausible_temp(0) is None and gpu.plausible_temp(6553.5) is None
    assert gpu.plausible_temp(72.5) == 72.5


def test_build_sample_includes_vram_and_temperature(tmp_path):
    system = SystemUsage(cpu=40, mem=50, disk=5, mem_total=16 * GB, gpu=60, gpu_mem=90,
                         gpu_mem_used=int(7.2 * GB), gpu_mem_total=8 * GB,
                         gpu_mem_by_pid={1: 6 * GB, 2: GB}, gpu_temp=81)
    procs = [ProcInfo(1, "Hades.exe"), ProcInfo(2, "chrome.exe")]
    result = build_sample(T0, system, procs, {1}, {})
    assert (result.gpu_mem, result.game_gpu_mem, result.gpu_temp) == (90, 75, 81)

    db = Database(tmp_path / "v.db")
    db.add_sample(1, result)
    stored = db.list_samples(1)[0]
    assert (stored.gpu_mem, stored.game_gpu_mem, stored.gpu_temp) == (90, 75, 81)
    db.close()


def test_full_vram_is_reported_with_the_game_share():
    samples = [sample(i * 3, gpu=60, gpu_mem=98, game_gpu_mem=85) for i in range(100)]
    result = report.analyze(samples, "Hades")
    assert result.worst.resource == "vram" and result.worst.culprit_is_game
    assert result.score == 64 and result.label == "Zorlandı"        # (98-90)/10 x 80
    assert "ekran kartı belleği (VRAM) %98 doldu" in result.lines[0]
    assert "oyunun kendisi VRAM'in %85" in result.lines[0]
    assert any("Doku kalitesini" in line for line in result.lines)
    assert result.available == {"gpu", "vram"} and result.game_average["vram"] == 85

    others = [sample(i * 3, gpu_mem=97, game_gpu_mem=20) for i in range(100)]
    result = report.analyze(others, "Hades")
    assert not result.worst.culprit_is_game and "diğer programlar VRAM'in %77" in result.lines[0]
    assert any("Tarayıcıyı" in line for line in result.lines)


def test_overheating_gpu_is_reported_in_celsius():
    samples = [sample(i * 3, gpu=95, gpu_temp=70 + i * 0.2) for i in range(100)] + \
              [sample(300 + i * 3, gpu=95, gpu_temp=91) for i in range(100)]
    result = report.analyze(samples, "Hades")
    assert result.worst.resource == "temp" and result.worst.value == 91
    assert "ekran kartı 91°C sıcaklığa ulaştı" in result.lines[0]
    assert any("83°C'nin üzerindeydi" in line for line in result.lines)
    assert any("hava akışını" in line for line in result.lines)
    assert report.format_value("temp", result.peak["temp"]) == "91°C"
    assert report.strain("temp", 83) == 0 and report.strain("temp", 95) == 60
    assert "temp" in result.available and "vram" not in result.available


def test_temperature_average_ignores_unmeasured_samples():
    samples = [sample(0), sample(3, gpu_temp=60), sample(6, gpu_temp=80)]
    assert report.analyze(samples, "Hades").average["temp"] == 70
