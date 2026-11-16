"""Oyun Modu: oyun açıkken bilgisayarın kaynaklarını oyuna yönlendirir.

Yapılanların hepsi GERİ ALINABİLİR ve oyun kapanınca geri alınır:
  1. Oyunun işlemci önceliği yükseltilir.
  2. Tarayıcı ve dosya eşitleme programlarının önceliği düşürülür
     (kapatılmazlar, yalnızca oyuna yol verirler).
  3. Windows güç planı "Yüksek performans" yapılır.

Oyun dosyalarına, oyun ayarlarına ve ekran kartı ayarlarına dokunulmaz.
Her adım ayrı ayrı açılıp kapatılabilir; Oyun Modu varsayılan olarak kapalıdır.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys

import psutil

from pwrhub.db import Database
from pwrhub.procscan import ProcInfo

log = logging.getLogger(__name__)

# Ayar anahtarları (veritabanındaki settings tablosu)
KEY_ENABLED = "boost_enabled"
KEY_GAME_PRIORITY = "boost_game_priority"
KEY_BACKGROUND = "boost_background"
KEY_POWER_PLAN = "boost_power_plan"
KEY_SAVED_PLAN = "boost_saved_plan"   # oyun öncesi güç planı (çökme sonrası geri yüklemek için)

# Alt seçeneklerin varsayılanları (Oyun Modu açıldığında).
DEFAULTS = {KEY_GAME_PRIORITY: True, KEY_BACKGROUND: True, KEY_POWER_PLAN: True}

# Windows'un yerleşik "Yüksek performans" güç planı.
HIGH_PERFORMANCE_PLAN = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"

# Oyun sırasında önceliği düşürülen programlar: çok kaynak kullanabilen ama
# bir süre yavaşlaması sorun olmayanlar. Sesli sohbet (Discord vb.) ve sistem
# programları bilerek listede yok.
BACKGROUND_NAMES = {
    "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe",
    "onedrive.exe", "dropbox.exe", "googledrivefs.exe",
    "searchindexer.exe", "msedgewebview2.exe",
}

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


class SystemBackend:
    """İşletim sistemine yapılan gerçek çağrılar. Testlerde sahtesiyle değiştirilir."""

    HIGH = "high"
    LOW = "low"

    def set_priority(self, pid: int, level: str):
        """Sürecin önceliğini değiştirir; eski önceliği (geri almak için) döndürür.
        Değiştirilemezse None döner."""
        try:
            proc = psutil.Process(pid)
            previous = proc.nice()
            if sys.platform == "win32":
                target = (psutil.HIGH_PRIORITY_CLASS if level == self.HIGH
                          else psutil.BELOW_NORMAL_PRIORITY_CLASS)
            else:
                # Windows dışı sistemler yalnızca geliştirme içindir.
                target = previous if level == self.HIGH else min(previous + 5, 19)
            if target != previous:
                proc.nice(target)
            return previous
        except (psutil.Error, OSError):
            return None   # yetki yok ya da süreç kapanmış: sorun değil

    def restore_priority(self, pid: int, previous) -> None:
        try:
            psutil.Process(pid).nice(previous)
        except (psutil.Error, OSError):
            pass

    def _powercfg(self, *args: str) -> str:
        if sys.platform != "win32":
            return ""
        try:
            done = subprocess.run(
                ["powercfg", *args], capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return done.stdout if done.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    def get_power_plan(self) -> str:
        """Etkin güç planının kimliği (okunamazsa boş)."""
        match = _GUID.search(self._powercfg("/getactivescheme"))
        return match.group(0).lower() if match else ""

    def set_power_plan(self, guid: str) -> bool:
        self._powercfg("/setactive", guid)
        return self.get_power_plan() == guid.lower()


class Booster:
    """Oyun Modu'nu uygular ve geri alır. İzleme motoru tarafından çağrılır."""

    def __init__(self, db: Database, backend: SystemBackend | None = None):
        self._db = db
        self._backend = backend or SystemBackend()
        self._active = False
        self._options: dict[str, bool] = {}
        self._priorities: dict[int, object] = {}   # süreç -> eski öncelik
        self.recover()

    @property
    def active(self) -> bool:
        return self._active

    def recover(self) -> None:
        """Önceki çalışmada (çökme vb.) geri alınamamış güç planını geri yükler."""
        saved = self._db.get_setting(KEY_SAVED_PLAN)
        if saved:
            self._backend.set_power_plan(saved)
            self._db.set_setting(KEY_SAVED_PLAN, "")

    def apply(self, game_procs: list[ProcInfo], all_procs: list[ProcInfo]) -> None:
        """Oyun açıkken her ölçüm turunda çağrılır.

        Güç planı bir kez değiştirilir; öncelikler ise sonradan açılan süreçleri
        de (ör. oyunun başlatıcıdan sonra açılan asıl dosyası) kapsasın diye her
        turda yeni süreçler için uygulanır.
        """
        if not self._db.get_flag(KEY_ENABLED):
            self.release()   # kullanıcı oyun sırasında kapattıysa hemen geri al
            return
        if not self._active:
            self._options = {key: self._db.get_flag(key, default) for key, default in DEFAULTS.items()}
            self._active = True
            if self._options[KEY_POWER_PLAN]:
                self._switch_power_plan()

        if self._options[KEY_GAME_PRIORITY]:
            self._set_priorities(game_procs, SystemBackend.HIGH)
        if self._options[KEY_BACKGROUND]:
            background = [p for p in all_procs if p.name.lower() in BACKGROUND_NAMES]
            self._set_priorities(background, SystemBackend.LOW)

    def release(self) -> None:
        """Oyun kapandı: yapılan her değişikliği geri alır."""
        if not self._active:
            return
        for pid, previous in self._priorities.items():
            self._backend.restore_priority(pid, previous)
        self._priorities.clear()
        self.recover()   # güç planını eski haline döndürür
        self._active = False

    def _set_priorities(self, procs: list[ProcInfo], level: str) -> None:
        for proc in procs:
            if proc.pid in self._priorities:
                continue
            previous = self._backend.set_priority(proc.pid, level)
            if previous is not None:
                self._priorities[proc.pid] = previous

    def _switch_power_plan(self) -> None:
        current = self._backend.get_power_plan()
        if not current or current == HIGH_PERFORMANCE_PLAN:
            return
        # Önce eski planı kaydet: uygulama beklenmedik kapansa bile geri yüklenebilsin.
        self._db.set_setting(KEY_SAVED_PLAN, current)
        if not self._backend.set_power_plan(HIGH_PERFORMANCE_PLAN):
            # Bazı dizüstülerde "Yüksek performans" planı yoktur; olduğu gibi bırak.
            self._db.set_setting(KEY_SAVED_PLAN, "")
