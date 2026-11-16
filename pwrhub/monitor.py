"""İzleme motoru: oturum takibini ve performans kaydını bir araya getirir.

`tick()` düzenli aralıklarla çağrılır (arayüzde bir arka plan iş parçacığı
tarafından). Qt'ye bağlı değildir; testlerde sahte süreç listeleriyle çalışır.
"""

from __future__ import annotations

import logging
from datetime import datetime

from pwrhub import report
from pwrhub.boost import Booster, SystemBackend
from pwrhub.db import Database
from pwrhub.matching import GameMatcher
from pwrhub.models import Sample
from pwrhub.procscan import ProcessScanner, ProcInfo, SystemReader, SystemUsage
from pwrhub.scanners.folder import exe_names
from pwrhub.sessions import SessionEvent, SessionTracker

log = logging.getLogger(__name__)

# Ölçüm aralıkları (saniye): oyun açıkken sık, değilken seyrek.
ACTIVE_INTERVAL = 3.0
IDLE_INTERVAL = 5.0
# Oyun açıkken her turda yalnızca oyunun süreçleri ölçülür; bütün programların
# ölçümü (arka planda en çok kaynak tüketeni bulmak için) bu kadar turda bir
# yapılır. Aradaki turlarda son bilinen değerler kullanılır.
FULL_SCAN_EVERY = 4
# Örnekler bellekte biriktirilip bu kadar turda bir diske yazılır.
FLUSH_EVERY = 5

_MB = 1024 * 1024


def _top(usage: dict[str, float]) -> tuple[str, float]:
    """En çok kullanan programın (adı, miktarı)."""
    if not usage:
        return "", 0.0
    name = max(usage, key=usage.get)
    return name, usage[name]


def build_sample(
    now: datetime,
    system: SystemUsage,
    procs: list[ProcInfo],
    game_pids: set[int],
    io_rates: dict[int, float],
) -> Sample:
    """Tek bir ölçümü, oyunun ve diğer programların payına ayırır.

    `io_rates`: süreç kimliği -> son ölçümden beri disk hızı (MB/sn).
    Aynı adlı süreçler (ör. onlarca chrome.exe) tek program olarak toplanır.
    """
    total = system.mem_total or 1
    game_cpu = game_mem = game_disk = 0.0
    other_cpu: dict[str, float] = {}
    other_mem: dict[str, float] = {}
    other_disk: dict[str, float] = {}
    game_gpu = 0.0
    game_vram = 0   # bayt
    other_gpu: dict[str, float] = {}

    for proc in procs:
        mem = proc.rss / total * 100
        disk = io_rates.get(proc.pid, 0.0)
        gpu = system.gpu_by_pid.get(proc.pid, 0.0)
        if proc.pid in game_pids:
            game_cpu += proc.cpu
            game_mem += mem
            game_disk += disk
            game_gpu += gpu
            game_vram += system.gpu_mem_by_pid.get(proc.pid, 0)
        else:
            other_cpu[proc.name] = other_cpu.get(proc.name, 0.0) + proc.cpu
            other_mem[proc.name] = other_mem.get(proc.name, 0.0) + mem
            other_disk[proc.name] = other_disk.get(proc.name, 0.0) + disk
            if gpu:
                other_gpu[proc.name] = other_gpu.get(proc.name, 0.0) + gpu

    top_cpu, top_mem, top_disk = _top(other_cpu), _top(other_mem), _top(other_disk)
    top_gpu = _top(other_gpu)
    gpu_limit = system.gpu if system.gpu is not None else 0.0
    return Sample(
        ts=now,
        cpu=system.cpu,
        mem=system.mem,
        disk=system.disk,
        # Ölçüm gürültüsü yüzünden parça bütünden büyük çıkmasın.
        game_cpu=min(game_cpu, system.cpu),
        game_mem=min(game_mem, system.mem),
        game_disk=game_disk,
        top_cpu_name=top_cpu[0], top_cpu=min(top_cpu[1], system.cpu),
        top_mem_name=top_mem[0], top_mem=min(top_mem[1], system.mem),
        top_disk_name=top_disk[0], top_disk=top_disk[1],
        cpu_core=system.cpu_core,
        gpu=system.gpu,
        game_gpu=min(game_gpu, gpu_limit),
        top_gpu_name=top_gpu[0], top_gpu=min(top_gpu[1], gpu_limit),
        gpu_mem=system.gpu_mem,
        game_gpu_mem=(min(game_vram / system.gpu_mem_total * 100, system.gpu_mem or 0.0)
                      if system.gpu_mem_total else 0.0),
        gpu_temp=system.gpu_temp,
    )


class MonitorEngine:
    def __init__(
        self,
        db: Database,
        scanner: ProcessScanner | None = None,
        system: SystemReader | None = None,
        backend: SystemBackend | None = None,
    ):
        self._db = db
        self._scanner = scanner or ProcessScanner()
        self._system = system or SystemReader()
        self._tracker = SessionTracker(db)
        self._booster = Booster(db, backend)
        self._exe_names: dict[str, set[str]] = {}   # kurulum klasörü -> exe adları (önbellek)
        self._matcher = GameMatcher([])
        self._names: dict[int, str] = {}
        self._io_prev: dict[int, tuple[int, datetime]] = {}   # süreç -> (bayt, ölçüm anı)
        self._background: dict[int, tuple[float, int, float]] = {}   # süreç -> (cpu, bellek, disk hızı)
        self._recorded = 0     # bu kayıt döneminde yapılan ölçüm turu sayısı
        self._pending: list[tuple[int, Sample]] = []   # diske yazılmayı bekleyen örnekler
        self.reload_games()

    @property
    def active(self) -> dict[int, int]:
        """Süren oturumlar: oyun kimliği -> oturum kimliği."""
        return self._tracker.active

    @property
    def interval(self) -> float:
        return ACTIVE_INTERVAL if self._tracker.active else IDLE_INTERVAL

    def reload_games(self) -> None:
        """Kütüphane değiştiğinde (tarama sonrası) oyun listesini yeniler."""
        games = self._db.list_games(include_hidden=True)
        # Dosya yolu okunamayan süreçleri adından tanımak için her oyunun
        # klasöründeki exe adlarını bir kez çıkarıp saklıyoruz.
        names: dict[int, set[str]] = {}
        for game in games:
            if game.install_dir and not game.exe_path:
                if game.install_dir not in self._exe_names:
                    self._exe_names[game.install_dir] = exe_names(game.install_dir)
                names[game.id] = self._exe_names[game.install_dir]
        self._matcher = GameMatcher(games, names)
        self._names = {g.id: g.name for g in games}

    def tick(self, now: datetime | None = None) -> list[SessionEvent]:
        """Bir ölçüm turu: çalışan oyunları bul, oturumları güncelle, örnek kaydet."""
        now = now or datetime.now()
        recording = bool(self._tracker.active)
        procs = self._scanner.scan()
        running = self._matcher.match(procs)
        events = self._tracker.update(set(running), now)

        if recording:
            self._record(now, procs, running)
        elif self._recorded:
            self._recorded = 0
            self._io_prev.clear()
            self._background.clear()

        # Oyun Modu: oyun açıkken uygula, hepsi kapanınca geri al.
        if running:
            game_procs = [p for items in running.values() for p in items]
            self._booster.apply(game_procs, procs)
        elif not self._tracker.active:
            self._booster.release()

        ended = [e for e in events if e.kind == "ended"]
        if ended or len(self._pending) >= FLUSH_EVERY:
            self._flush()
        for event in ended:
            if event.session_id is not None:
                self._score_session(event.game_id, event.session_id)
        return events

    def _flush(self) -> None:
        """Bekleyen örnekleri tek seferde diske yazar."""
        if self._pending:
            self._db.add_samples(self._pending)
            self._pending = []

    def shutdown(self) -> None:
        """Uygulama kapanırken süren oturumları kapatır ve notlarını yazar."""
        self._booster.release()
        self._flush()
        for event in self._tracker.close_all():
            if event.session_id is not None:
                self._score_session(event.game_id, event.session_id)

    def _record(self, now: datetime, procs: list[ProcInfo], running: dict[int, list[ProcInfo]]) -> None:
        # İlk iki turda ve sonra her FULL_SCAN_EVERY turda bütün programlar,
        # aradaki turlarda yalnızca oyunun süreçleri ölçülür.
        full = self._recorded < 2 or self._recorded % FULL_SCAN_EVERY == 0
        game_procs = [p for items in running.values() for p in items]
        self._scanner.measure(procs if full else game_procs)
        system = self._system.read()

        io_rates: dict[int, float] = {}
        for proc in procs:
            if not proc.measured:
                continue
            previous = self._io_prev.get(proc.pid)
            if previous is not None:
                elapsed = (now - previous[1]).total_seconds()
                if elapsed > 0 and proc.io_bytes >= previous[0]:
                    io_rates[proc.pid] = (proc.io_bytes - previous[0]) / _MB / elapsed
            self._io_prev[proc.pid] = (proc.io_bytes, now)

        if full:
            self._background = {
                p.pid: (p.cpu, p.rss, io_rates.get(p.pid, 0.0)) for p in procs if p.measured
            }
        else:
            # Bu turda ölçülmeyen programlar için son bilinen değerleri kullan.
            for proc in procs:
                known = None if proc.measured else self._background.get(proc.pid)
                if known is not None:
                    proc.cpu, proc.rss = known[0], known[1]
                    io_rates[proc.pid] = known[2]

        self._recorded += 1
        if self._recorded == 1:
            # İlk ölçüm yalnızca başlangıç noktasıdır (işlemci ve disk kullanımı
            # iki ölçüm arasındaki farktan hesaplanır); kaydedilmez.
            return
        for game_id, session_id in self._tracker.active.items():
            mine = running.get(game_id)
            if not mine:
                continue  # oyun kısa süreliğine kayboldu (bekleme süresinde)
            pids = {p.pid for p in mine}
            self._pending.append((session_id, build_sample(now, system, procs, pids, io_rates)))

    def _score_session(self, game_id: int, session_id: int) -> None:
        self._flush()
        result = report.analyze(self._db.list_samples(session_id), self._names.get(game_id, "Oyun"))
        self._db.set_session_score(session_id, result.score if result else None)
