"""Arka plandaki programları listeler ve kullanıcının isteğiyle kapatır.

Hiçbir program kendiliğinden kapatılmaz: kapatma yalnızca kullanıcı
Optimizasyon sayfasında düğmeye basıp onayladığında yapılır. Windows'un
çalışması için gereken sistem programları hiçbir zaman kapatılamaz.
"""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass, field

import psutil

from pwrhub.procscan import ProcInfo
from pwrhub.report import friendly_name

# Kapatılması bilgisayarı kararsız hale getirecek ya da anlamsız olan programlar.
PROTECTED = {
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe",
    "fontdrvhost.exe", "sihost.exe", "ctfmon.exe", "taskhostw.exe", "conhost.exe",
    "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "textinputhost.exe", "audiodg.exe", "spoolsv.exe",
    "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe", "memory compression",
    "wudfhost.exe", "dllhost.exe", "lsaiso.exe", "systemsettings.exe",
    "tiworker.exe", "trustedinstaller.exe", "searchindexer.exe", "wmiprvse.exe",
    "python.exe", "pythonw.exe",   # PwR Hub'ın kendisi bunlardan biri olabilir
}


@dataclass
class ProgramUsage:
    """Aynı adlı süreçlerin (ör. bütün chrome.exe'lerin) toplam kullanımı."""

    name: str                 # süreç adı (chrome.exe)
    title: str                # okunur ad (Chrome (tarayıcı))
    cpu: float = 0.0          # bütün işlemcinin yüzdesi
    mem_bytes: int = 0
    mem: float = 0.0          # bütün belleğin yüzdesi
    pids: list[int] = field(default_factory=list)
    closable: bool = True     # kullanıcı kapatabilir mi (sistem programı değilse)


def top_programs(
    procs: list[ProcInfo],
    mem_total: int,
    exclude_pids: set[int] | None = None,
    limit: int = 8,
) -> list[ProgramUsage]:
    """En çok kaynak kullanan programlar (oyunlar ve PwR Hub hariç)."""
    skip = set(exclude_pids or ()) | {os.getpid()}
    groups: dict[str, ProgramUsage] = {}
    for proc in procs:
        if proc.pid in skip:
            continue
        key = proc.name.lower()
        item = groups.get(key)
        if item is None:
            item = groups[key] = ProgramUsage(
                proc.name, friendly_name(proc.name), closable=key not in PROTECTED
            )
        item.cpu += proc.cpu
        item.mem_bytes += proc.rss
        item.pids.append(proc.pid)
    total = mem_total or 1
    for item in groups.values():
        item.mem = item.mem_bytes / total * 100
    # İşlemci ve bellek payının toplamına göre sırala; ihmal edilebilir olanları at.
    ranked = sorted(groups.values(), key=lambda p: p.cpu + p.mem, reverse=True)
    return [p for p in ranked if p.cpu + p.mem >= 0.5][:limit]


def close_program(program: ProgramUsage, timeout: float = 3.0) -> tuple[int, int]:
    """Programın bütün süreçlerini kapatır; (kapanan, kapanamayan) sayısını döndürür.

    Güvenlik için yalnızca hâlâ aynı adı taşıyan ve bu kullanıcıya ait süreçler
    kapatılır (süreç numaraları yeniden kullanılabildiği için ad yeniden bakılır).
    """
    if not program.closable:
        return 0, len(program.pids)
    me = getpass.getuser().lower()
    targets = []
    failed = 0
    for pid in program.pids:
        try:
            proc = psutil.Process(pid)
            if proc.name().lower() != program.name.lower():
                continue   # bu numara artık başka bir programa ait
            owner = (proc.username() or "").split("\\")[-1].lower()
            if owner != me:
                failed += 1
                continue
            proc.terminate()
            targets.append(proc)
        except psutil.NoSuchProcess:
            continue
        except (psutil.Error, OSError):
            failed += 1
    _gone, alive = psutil.wait_procs(targets, timeout=timeout)
    return len(targets) - len(alive), failed + len(alive)
