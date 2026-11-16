"""Uygulamanın ortak veri modelleri."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Oyun kaynakları
SOURCE_STEAM = "steam"
SOURCE_EPIC = "epic"
SOURCE_MANUAL = "manual"

# Arayüzde gösterilecek kaynak adları
SOURCE_LABELS = {
    SOURCE_STEAM: "Steam",
    SOURCE_EPIC: "Epic Games",
    SOURCE_MANUAL: "Elle eklendi",
}


@dataclass
class Game:
    """Kütüphanedeki tek bir oyun.

    `source` + `source_id` ikilisi oyunu benzersiz tanımlar:
      - Steam  -> appid (ör. "730")
      - Epic   -> AppName
      - Elle   -> oyun klasörünün (ya da exe'nin) küçük harfli tam yolu
    """

    source: str
    source_id: str
    name: str
    install_dir: str = ""
    exe_path: str = ""       # doğrudan çalıştırılacak dosya (elle eklenenler ve yedek yol)
    launch_uri: str = ""     # steam:// ya da com.epicgames.launcher:// adresi
    cover_path: str = ""     # tarayıcının yerelde bulduğu kapak resmi
    custom_cover: str = ""   # kullanıcının seçtiği kapak (varsa bu kullanılır)
    installed: bool = True   # son taramada bulundu mu
    hidden: bool = False     # kullanıcı kütüphaneden gizledi mi
    added_at: str = ""       # ISO tarih (kütüphaneye ilk eklenme)
    last_launched_at: str = ""  # ISO tarih (PwR Hub'dan son başlatma)
    id: int | None = None    # veritabanı kimliği
    # Oynanma özeti (oturum kayıtlarından hesaplanır, veritabanında ayrı sütun değildir)
    total_seconds: int = 0
    session_count: int = 0
    last_played_at: str = ""

    @property
    def effective_cover(self) -> str:
        """Gösterilecek kapak: önce kullanıcının seçtiği, sonra bulunan."""
        return self.custom_cover or self.cover_path

    @property
    def last_activity(self) -> str:
        """Son oynanma (yoksa PwR Hub'dan son başlatma) zamanı; sıralama için."""
        return max(self.last_played_at, self.last_launched_at)

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)


@dataclass
class Session:
    """Bir oyunun açılışından kapanışına kadar geçen tek oturum."""

    id: int
    game_id: int
    started_at: datetime
    ended_at: datetime
    duration_s: int
    strain_score: int | None = None  # 0-100; performans kaydı yoksa None


@dataclass
class Sample:
    """Oturum sırasında alınan tek bir performans ölçümü.

    Yüzdeler 0-100 arasıdır ve bütün bilgisayara göredir (ör. `game_cpu = 40`,
    oyunun toplam işlemci gücünün %40'ını kullandığı anlamına gelir).
    `top_*` alanları oyun DIŞINDAKİ en çok kaynak tüketen programı gösterir.
    """

    ts: datetime
    cpu: float
    mem: float
    disk: float
    game_cpu: float = 0.0
    game_mem: float = 0.0
    game_disk: float = 0.0       # MB/sn
    top_cpu_name: str = ""
    top_cpu: float = 0.0
    top_mem_name: str = ""
    top_mem: float = 0.0
    top_disk_name: str = ""
    top_disk: float = 0.0        # MB/sn
    cpu_core: float = 0.0        # en yoğun işlemci çekirdeğinin kullanımı, %
    gpu: float | None = None     # ekran kartı kullanımı, % (ölçülemiyorsa None)
    game_gpu: float = 0.0        # oyunun ekran kartı payı, %
    top_gpu_name: str = ""
    top_gpu: float = 0.0
    gpu_mem: float | None = None   # ekran kartı belleği (VRAM) doluluğu, %
    game_gpu_mem: float = 0.0      # oyunun VRAM payı, toplam VRAM'in yüzdesi
    gpu_temp: float | None = None  # ekran kartı sıcaklığı, °C
