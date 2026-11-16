"""Ekran kartı (GPU) ölçümleri: kullanım, bellek (VRAM) ve sıcaklık. DENEYSEL.

Yalnızca OKUMA yapılır; ekran kartı ayarlarına (fan, hız aşırtma, sürücü)
dokunulmaz. Ek bir kütüphane gerekmez. Kaynaklar:

  Kullanım %   Windows "GPU Engine" performans sayaçları (Görev Yöneticisi'nin
               kullandığıyla aynı; NVIDIA, AMD, Intel fark etmez).
  VRAM         "GPU Adapter Memory" / "GPU Process Memory" sayaçları; toplam
               VRAM kayıt defterindeki sürücü bilgisinden okunur.
  Sıcaklık     NVIDIA kartlarda sürücüyle gelen `nvidia-smi` aracı; diğer
               kartlarda Görev Yöneticisi'nin kullandığı Windows çağrısı
               (D3DKMT). Bazı kartlar (özellikle işlemciye gömülü olanlar)
               sıcaklık bildirmez.

Bir değer okunamazsa (eski Windows, desteklemeyen sürücü, Windows dışı sistem)
o ölçüm sessizce kapanır; uygulamanın geri kalanı etkilenmez.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_ENGINE = r"\GPU Engine(*)\Utilization Percentage"
_ADAPTER_MEMORY = r"\GPU Adapter Memory(*)\Dedicated Usage"
_PROCESS_MEMORY = r"\GPU Process Memory(*)\Dedicated Usage"

_PDH_FMT_DOUBLE = 0x00000200
_PDH_MORE_DATA = 0x800007D2
# Yeni açılan programların da görünmesi için sayaç listesi bu kadar okumada
# bir yeniden kurulur.
_REBUILD_EVERY = 10
# nvidia-smi her okumada değil, bu kadar okumada bir çalıştırılır (yük olmasın).
_SMI_EVERY = 5

# Sayaç adı örneği: "pid_1234_luid_0x00000000_0x0000C2A8_phys_0_eng_3_engtype_3D"
_INSTANCE = re.compile(r"pid_(\d+)_(.+)")
_MIB = 1024 * 1024


@dataclass
class GpuUsage:
    """Ekran kartının o anki durumu. Ölçülemeyen değerler None'dır."""

    util: float | None = None                 # kullanım, %
    util_by_pid: dict[int, float] = field(default_factory=dict)
    vram_used: int | None = None              # kullanılan ekran kartı belleği, bayt
    vram_total: int | None = None             # toplam ekran kartı belleği, bayt
    vram_by_pid: dict[int, int] = field(default_factory=dict)
    temp: float | None = None                 # sıcaklık, °C

    @property
    def vram_percent(self) -> float | None:
        if self.vram_used is None or not self.vram_total:
            return None
        return min(self.vram_used / self.vram_total * 100, 100.0)


# ------------------------------------------------------------ saf hesaplamalar

def aggregate(items: list[tuple[str, float]]) -> tuple[float, dict[int, float]]:
    """Kullanım sayaçlarından (toplam %, süreç -> %) hesaplar.

    Bir ekran kartının birden fazla "motoru" vardır (3D, video çözme, kopyalama...).
    Görev Yöneticisi gibi, toplam kullanım olarak en meşgul motoru alırız.
    """
    per_engine: dict[str, float] = {}
    per_pid: dict[int, float] = {}
    for name, value in items:
        match = _INSTANCE.search(name)
        if not match or value <= 0:
            continue
        pid, engine = int(match.group(1)), match.group(2)
        per_engine[engine] = per_engine.get(engine, 0.0) + value
        per_pid[pid] = max(per_pid.get(pid, 0.0), value)
    total = min(max(per_engine.values(), default=0.0), 100.0)
    return total, {pid: min(value, 100.0) for pid, value in per_pid.items()}


def aggregate_memory(
    adapters: list[tuple[str, float]], processes: list[tuple[str, float]]
) -> tuple[int | None, dict[int, int]]:
    """Bellek sayaçlarından (kullanılan VRAM, süreç -> VRAM) hesaplar (bayt).

    Birden fazla ekran kartı varsa en çok belleği kullanılan (oyunun çalıştığı)
    kart esas alınır.
    """
    used = max((value for _name, value in adapters), default=None)
    per_pid: dict[int, int] = {}
    for name, value in processes:
        match = _INSTANCE.search(name)
        if match and value > 0:
            pid = int(match.group(1))
            per_pid[pid] = max(per_pid.get(pid, 0), int(value))
    return (int(used) if used is not None else None), per_pid


def parse_nvidia_smi(output: str) -> tuple[float, int, int] | None:
    """`nvidia-smi` çıktısından (sıcaklık °C, kullanılan bayt, toplam bayt) okur.

    Beklenen satır: "65, 3012, 8192" (sıcaklık, kullanılan MiB, toplam MiB).
    Birden fazla kart varsa belleği en çok kullanılan alınır.
    """
    best = None
    for line in output.strip().splitlines():
        parts = [part.strip() for part in line.split(",")]
        try:
            temp, used, total = float(parts[0]), int(float(parts[1])), int(float(parts[2]))
        except (ValueError, IndexError):
            continue
        if best is None or used > best[1]:
            best = (temp, used, total)
    if best is None:
        return None
    return best[0], best[1] * _MIB, best[2] * _MIB


def plausible_temp(celsius: float) -> float | None:
    """Anlamsız değerleri (0, sürücünün doldurmadığı alanlar) eler."""
    return celsius if 1.0 <= celsius <= 150.0 else None


# ------------------------------------------------------------ Windows okuyucuları

class _PdhQuery:
    """Birkaç joker karakterli performans sayacını birlikte okur."""

    def __init__(self, paths: list[str]):
        import ctypes

        self._ct = ctypes
        self._pdh = ctypes.windll.pdh
        self._paths = paths
        self._query = None
        self._counters: dict[str, object] = {}
        self._reads = 0
        self._open()
        if not self._counters:
            raise OSError("GPU sayaçları bulunamadı")

    @property
    def paths(self) -> set[str]:
        return set(self._counters)

    def _open(self) -> None:
        ct = self._ct
        query = ct.c_void_p()
        if self._pdh.PdhOpenQueryW(None, 0, ct.byref(query)) != 0:
            raise OSError("PdhOpenQuery başarısız")
        counters = {}
        for path in self._paths:
            counter = ct.c_void_p()
            # "English" sürümü: Windows dili Türkçe olsa da sayaç adı aynı kalır.
            if self._pdh.PdhAddEnglishCounterW(query, path, 0, ct.byref(counter)) == 0:
                counters[path] = counter
        self._pdh.PdhCollectQueryData(query)   # başlangıç ölçümü
        if self._query is not None:
            self._pdh.PdhCloseQuery(self._query)
        self._query, self._counters = query, counters

    def _values(self, counter) -> list[tuple[str, float]]:
        ct = self._ct

        class _Value(ct.Union):
            _fields_ = [("long", ct.c_long), ("double", ct.c_double), ("large", ct.c_longlong),
                        ("ansi", ct.c_char_p), ("wide", ct.c_wchar_p)]

        class _Counter(ct.Structure):
            _fields_ = [("status", ct.c_ulong), ("value", _Value)]

        class _Item(ct.Structure):
            _fields_ = [("name", ct.c_wchar_p), ("counter", _Counter)]

        size, count = ct.c_ulong(0), ct.c_ulong(0)
        status = self._pdh.PdhGetFormattedCounterArrayW(
            counter, _PDH_FMT_DOUBLE, ct.byref(size), ct.byref(count), None)
        if status & 0xFFFFFFFF != _PDH_MORE_DATA or size.value == 0:
            return []
        buffer = ct.create_string_buffer(size.value)
        status = self._pdh.PdhGetFormattedCounterArrayW(
            counter, _PDH_FMT_DOUBLE, ct.byref(size), ct.byref(count), buffer)
        if status != 0:
            return []
        items = ct.cast(buffer, ct.POINTER(_Item))
        return [(items[i].name or "", items[i].counter.value.double) for i in range(count.value)]

    def read(self) -> dict[str, list[tuple[str, float]]]:
        self._pdh.PdhCollectQueryData(self._query)
        result = {path: self._values(counter) for path, counter in self._counters.items()}
        self._reads += 1
        if self._reads % _REBUILD_EVERY == 0:
            self._open()
        return result


def _registry_vram_total() -> int | None:
    """Sürücünün kayıt defterine yazdığı toplam ekran kartı belleği (bayt)."""
    import winreg

    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    best = 0
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            for index in range(32):
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                try:
                    with winreg.OpenKey(root, name) as adapter:
                        value, _kind = winreg.QueryValueEx(
                            adapter, "HardwareInformation.qwMemorySize")
                except OSError:
                    continue
                if isinstance(value, bytes):
                    value = int.from_bytes(value[:8], "little")
                best = max(best, int(value))
    except OSError:
        return None
    return best or None


class _KmtTemperature:
    """Görev Yöneticisi'nin kullandığı D3DKMT çağrısıyla ekran kartı sıcaklığı."""

    _ADAPTER_PERFDATA = 62   # KMTQAITYPE_ADAPTERPERFDATA

    def __init__(self):
        import ctypes as ct

        self._ct = ct
        self._gdi = ct.windll.gdi32

        class _Luid(ct.Structure):
            _fields_ = [("low", ct.c_ulong), ("high", ct.c_long)]

        class _AdapterInfo(ct.Structure):
            _fields_ = [("handle", ct.c_uint), ("luid", _Luid),
                        ("sources", ct.c_ulong), ("precise", ct.c_int)]

        class _EnumAdapters(ct.Structure):
            _fields_ = [("count", ct.c_ulong), ("adapters", ct.POINTER(_AdapterInfo))]

        # Önce kaç ekran kartı olduğunu sor, sonra listesini al.
        request = _EnumAdapters(0, None)
        if self._gdi.D3DKMTEnumAdapters2(ct.byref(request)) != 0 or request.count == 0:
            raise OSError("Ekran kartı listesi alınamadı")
        array = (_AdapterInfo * request.count)()
        request.adapters = ct.cast(array, ct.POINTER(_AdapterInfo))
        if self._gdi.D3DKMTEnumAdapters2(ct.byref(request)) != 0:
            raise OSError("Ekran kartı listesi alınamadı")
        self._handles = [array[i].handle for i in range(request.count)]
        if self.read() is None:
            raise OSError("Ekran kartı sıcaklık bildirmiyor")

    def read(self) -> float | None:
        ct = self._ct

        class _PerfData(ct.Structure):
            _fields_ = [("index", ct.c_uint32),
                        ("memory_frequency", ct.c_ulonglong),
                        ("max_memory_frequency", ct.c_ulonglong),
                        ("max_memory_frequency_oc", ct.c_ulonglong),
                        ("memory_bandwidth", ct.c_ulonglong),
                        ("pcie_bandwidth", ct.c_ulonglong),
                        ("fan_rpm", ct.c_ulong),
                        ("power", ct.c_ulong),
                        ("temperature", ct.c_ulong),   # onda bir °C
                        ("power_state_override", ct.c_ubyte)]

        class _Query(ct.Structure):
            _fields_ = [("handle", ct.c_uint), ("type", ct.c_int),
                        ("data", ct.c_void_p), ("size", ct.c_uint)]

        hottest = None
        for handle in self._handles:
            data = _PerfData()
            query = _Query(handle, self._ADAPTER_PERFDATA,
                           ct.cast(ct.byref(data), ct.c_void_p), ct.sizeof(data))
            if self._gdi.D3DKMTQueryAdapterInfo(ct.byref(query)) != 0:
                continue
            temp = plausible_temp(data.temperature / 10.0)
            if temp is not None and (hottest is None or temp > hottest):
                hottest = temp
        return hottest


class GpuReader:
    """`read()` her çağrıda bir GpuUsage, hiçbir şey ölçülemiyorsa None döndürür."""

    def __init__(self) -> None:
        self._pdh: _PdhQuery | None = None
        self._kmt: _KmtTemperature | None = None
        self._smi: str | None = None
        self._smi_cache: tuple[float, int, int] | None = None
        self._vram_total: int | None = None
        self._reads = 0
        if sys.platform != "win32":
            return

        try:
            self._pdh = _PdhQuery([_ENGINE, _ADAPTER_MEMORY, _PROCESS_MEMORY])
        except Exception as exc:
            log.info("Ekran kartı sayaçları kullanılamıyor: %s", exc)
        try:
            self._vram_total = _registry_vram_total()
        except Exception as exc:
            log.info("Toplam ekran kartı belleği okunamadı: %s", exc)
        self._smi = shutil.which("nvidia-smi")
        if self._smi is None:
            try:
                self._kmt = _KmtTemperature()
            except Exception as exc:
                log.info("Ekran kartı sıcaklığı okunamıyor: %s", exc)

    @property
    def available(self) -> bool:
        return self._pdh is not None or self._kmt is not None or self._smi is not None

    def _read_smi(self) -> None:
        """nvidia-smi'yi çalıştırıp sonucu saklar; çalışmazsa bir daha denemez."""
        try:
            done = subprocess.run(
                [self._smi, "--query-gpu=temperature.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._smi_cache = parse_nvidia_smi(done.stdout) if done.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            self._smi_cache = None
        if self._smi_cache is None:
            self._smi = None

    def read(self) -> GpuUsage | None:
        if not self.available:
            return None
        usage = GpuUsage(vram_total=self._vram_total)

        if self._pdh is not None:
            try:
                data = self._pdh.read()
                if _ENGINE in data:
                    usage.util, usage.util_by_pid = aggregate(data[_ENGINE])
                if _ADAPTER_MEMORY in data:
                    usage.vram_used, usage.vram_by_pid = aggregate_memory(
                        data[_ADAPTER_MEMORY], data.get(_PROCESS_MEMORY, []))
            except Exception as exc:
                log.info("Ekran kartı sayaçları durduruldu: %s", exc)
                self._pdh = None

        if self._smi is not None:
            if self._reads % _SMI_EVERY == 0:
                self._read_smi()
            if self._smi_cache is not None:
                # NVIDIA'nın kendi aracı en güvenilir kaynak: değerlerini tercih et.
                usage.temp = plausible_temp(self._smi_cache[0])
                usage.vram_used, usage.vram_total = self._smi_cache[1], self._smi_cache[2]
        elif self._kmt is not None:
            try:
                usage.temp = self._kmt.read()
            except Exception as exc:
                log.info("Ekran kartı sıcaklığı durduruldu: %s", exc)
                self._kmt = None

        self._reads += 1
        return usage
