"""Çalışan programları ve bilgisayarın genel kaynak kullanımını okur (psutil).

Bu modül yalnızca ölçüm yapar; hiçbir programa müdahale etmez ve hiçbir
veriyi dışarı göndermez.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import psutil

from pwrhub.gpu import GpuReader


@dataclass
class ProcInfo:
    """Çalışan tek bir programın o anki durumu."""

    pid: int
    name: str
    exe: str = ""        # tam dosya yolu (okunamadıysa boş)
    cpu: float = 0.0     # bütün işlemci gücünün yüzdesi (0-100)
    rss: int = 0         # kullandığı bellek (bayt)
    io_bytes: int = 0    # açılışından beri okuduğu + yazdığı toplam bayt
    measured: bool = False   # cpu/rss/io bu turda gerçekten ölçüldü mü


class ProcessScanner:
    """Çalışan programların listesini çıkarır.

    İki adım vardır:
      - `scan()`: yalnızca ad ve dosya yolu. Oyun açık değilken "bir oyun
        başladı mı?" diye bakmak için kullanılır; çok az kaynak harcar.
      - `measure()`: seçilen süreçlerin işlemci, bellek ve disk kullanımı.
        Yalnızca bir oyun açıkken ve yalnızca gereken süreçler için çağrılır.
    """

    # Yeni açılan bir sürecin dosya yolu ilk anda okunamayabilir; birkaç kez denenir.
    _EXE_ATTEMPTS = 3
    _VERIFY_EVERY = 12   # süreç numarası yeniden kullanılmış mı: kaç turda bir bakılır

    def __init__(self) -> None:
        self._cpu_count = psutil.cpu_count() or 1
        # Her tarayıcı kendi süreç nesnelerini saklar. psutil işlemci yüzdesini
        # "bu nesnenin bir önceki çağrısından bu yana" hesapladığı için, izleme
        # ile Optimizasyon sayfası aynı nesneleri paylaşsaydı birbirlerinin
        # ölçümünü bozardı.
        self._procs: dict[int, psutil.Process] = {}
        self._names: dict[int, str] = {}
        self._exes: dict[int, str] = {}
        self._exe_tries: dict[int, int] = {}
        self._scans = 0

    def _forget(self, pid: int) -> None:
        for cache in (self._procs, self._names, self._exes, self._exe_tries):
            cache.pop(pid, None)

    def scan(self, detailed: bool = False) -> list[ProcInfo]:
        """Çalışan süreçlerin listesi (ad ve dosya yolu).

        Bilinen süreçler için hiçbir sistem çağrısı yapılmaz; yalnızca yeni
        açılanların adı ve yolu okunur. Bu yüzden oyun kapalıyken yapılan
        düzenli kontrol neredeyse bedavadır. `detailed=True` verilirse bütün
        süreçler için `measure()` da çağrılır.
        """
        result: list[ProcInfo] = []
        try:
            pids = set(psutil.pids())
        except (psutil.Error, OSError):
            return result
        for pid in list(self._procs):
            if pid not in pids:
                self._forget(pid)   # kapanan süreçler

        # Süreç numarasının başka bir programa verilmiş olması nadirdir; bunu
        # her turda değil, arada bir kontrol ederiz.
        self._scans += 1
        verify = self._scans % self._VERIFY_EVERY == 0

        for pid in pids:
            if pid == 0:
                continue  # "System Idle Process" gerçek bir program değildir
            proc = self._procs.get(pid)
            try:
                if proc is not None and verify and not proc.is_running():
                    self._forget(pid)
                    proc = None
                if proc is None:
                    proc = psutil.Process(pid)
                    self._names[pid] = proc.name() or ""
                    self._procs[pid] = proc
                name = self._names[pid]
                if not name:
                    continue

                exe = self._exes.get(pid, "")
                if not exe and self._exe_tries.get(pid, 0) < self._EXE_ATTEMPTS:
                    self._exe_tries[pid] = self._exe_tries.get(pid, 0) + 1
                    try:
                        exe = proc.exe() or ""
                    except psutil.NoSuchProcess:
                        raise
                    except (psutil.Error, OSError):
                        exe = ""  # korumalı süreçler okunamaz; adıyla yetiniriz
                    self._exes[pid] = exe
            except psutil.NoSuchProcess:
                self._forget(pid)   # süreç bu arada kapanmış
                continue
            except (psutil.Error, OSError):
                continue            # okunamayan süreç bu turda atlanır
            result.append(ProcInfo(pid=pid, name=name, exe=exe))

        if detailed:
            self.measure(result)
        return result

    def measure(self, procs: list[ProcInfo]) -> None:
        """Verilen süreçlerin işlemci, bellek ve disk kullanımını okuyup doldurur.

        Pahalı olan kısım budur (süreç başına birkaç sistem çağrısı); bu yüzden
        yalnızca gerektiği kadar süreç için çağrılır.
        """
        for item in procs:
            proc = self._procs.get(item.pid)
            if proc is None:
                continue
            try:
                with proc.oneshot():
                    # psutil çekirdek başına yüzde verir; bütün makineye çeviriyoruz.
                    item.cpu = proc.cpu_percent(None) / self._cpu_count
                    item.rss = proc.memory_info().rss
                    try:
                        io = proc.io_counters()
                        item.io_bytes = io.read_bytes + io.write_bytes
                    except psutil.NoSuchProcess:
                        raise
                    except (psutil.Error, OSError, AttributeError, NotImplementedError):
                        pass  # disk sayacı okunamıyorsa 0 kalır
                item.measured = True
            except (psutil.Error, OSError):
                continue


@dataclass
class SystemUsage:
    cpu: float        # toplam işlemci kullanımı (bütün çekirdeklerin ortalaması), %
    mem: float        # toplam bellek kullanımı, %
    disk: float       # en meşgul diskin meşguliyeti, %
    mem_total: int    # toplam bellek, bayt
    cpu_core: float = 0.0          # en yoğun çekirdeğin kullanımı, %
    gpu: float | None = None       # ekran kartı kullanımı, % (ölçülemiyorsa None)
    gpu_by_pid: dict[int, float] = field(default_factory=dict)   # süreç -> ekran kartı payı
    gpu_mem: float | None = None   # ekran kartı belleği (VRAM) doluluğu, %
    gpu_mem_used: int = 0          # kullanılan VRAM, bayt
    gpu_mem_total: int = 0         # toplam VRAM, bayt
    gpu_mem_by_pid: dict[int, int] = field(default_factory=dict)  # süreç -> VRAM, bayt
    gpu_temp: float | None = None  # ekran kartı sıcaklığı, °C


class SystemReader:
    """Bilgisayarın genel işlemci, bellek ve disk kullanımını okur."""

    def __init__(self) -> None:
        self._disk_prev: dict[str, float] = {}
        self._disk_time = 0.0
        self._gpu = GpuReader()
        psutil.cpu_percent(None, percpu=True)  # ilk çağrı yalnızca başlangıç noktası oluşturur

    def read(self) -> SystemUsage:
        memory = psutil.virtual_memory()
        # Çekirdek başına okuyoruz: toplam %25 görünürken tek bir çekirdek %100
        # olabilir ve oyun yine de takılır. Bunu yakalamak için en yoğun
        # çekirdeği ayrıca saklıyoruz.
        cores = psutil.cpu_percent(None, percpu=True) or [0.0]
        gpu = self._gpu.read()
        return SystemUsage(
            cpu=sum(cores) / len(cores),
            mem=memory.percent,
            disk=self._disk_busy(),
            mem_total=memory.total,
            cpu_core=max(cores),
            gpu=gpu.util if gpu else None,
            gpu_by_pid=gpu.util_by_pid if gpu else {},
            gpu_mem=gpu.vram_percent if gpu else None,
            gpu_mem_used=(gpu.vram_used or 0) if gpu else 0,
            gpu_mem_total=(gpu.vram_total or 0) if gpu else 0,
            gpu_mem_by_pid=gpu.vram_by_pid if gpu else {},
            gpu_temp=gpu.temp if gpu else None,
        )

    def _disk_busy(self) -> float:
        """Disklerin son ölçümden beri yüzde kaç meşgul olduğunu döndürür.

        Görev Yöneticisi'ndeki "Disk %" değerine karşılık gelir: diskin dolu
        olması değil, okuma/yazma ile ne kadar uğraştığıdır. Takılmalarla ilgili
        olan budur. Birden fazla disk varsa en meşgul olanı alınır.
        """
        try:
            counters = psutil.disk_io_counters(perdisk=True) or {}
        except (OSError, RuntimeError):
            return 0.0
        now = time.monotonic()
        elapsed_ms = (now - self._disk_time) * 1000
        busiest = 0.0
        current: dict[str, float] = {}
        for name, io in counters.items():
            # Linux'ta doğrudan meşgul süre var; Windows'ta okuma+yazma süresi kullanılır.
            busy = getattr(io, "busy_time", None)
            if busy is None:
                busy = io.read_time + io.write_time
            current[name] = busy
            if name in self._disk_prev and self._disk_time and elapsed_ms > 0:
                percent = (busy - self._disk_prev[name]) / elapsed_ms * 100
                busiest = max(busiest, percent)
        self._disk_prev, self._disk_time = current, now
        return max(0.0, min(busiest, 100.0))
