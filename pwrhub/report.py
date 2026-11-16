"""Takılma dedektifi: performans örneklerinden sade dilde rapor üretir.

Ölçülen kaynaklar:
  cpu   toplam işlemci kullanımı (bütün çekirdeklerin ortalaması)
  core  en yoğun tek işlemci çekirdeği
  mem   bellek
  disk  disk meşguliyeti
  gpu   ekran kartı kullanımı (ölçülebildiyse)
  vram  ekran kartı belleği doluluğu (ölçülebildiyse)
  temp  ekran kartı sıcaklığı, °C (ölçülebildiyse)

Zorlanma notu nasıl hesaplanır?
  1. Her ölçümde her kaynak için bir "zorlanma" hesaplanır: kaynak rahat
     eşiğinin altındaysa 0, %100'e dayandıysa o kaynağın üst sınırı.
  2. İşlemci, bellek ve diskin üst sınırı 100'dür: bunlar tıkanınca oyun
     doğrudan takılır. Tek çekirdek (60) ve ekran kartı kullanımının (50) üst
     sınırı daha düşüktür, çünkü FPS sınırı olmayan oyunlarda bunların sınırda
     çalışması olağandır ve tek başına takılma anlamına gelmez. VRAM (80)
     dolunca dokular diske taşar; sıcaklık (60) 83°C'den sonra sayılır, çünkü
     ekran kartları ısınınca kendini korumak için yavaşlar.
  3. O anın zorlanması, kaynaklardan en kötüsüdür.
  4. Oturum notu = 0,6 x (en kötü %5'lik dilimin sınırı) + 0,4 x (ortalama).
     Böylece hem kısa süreli sert tıkanmalar hem de uzun süren hafif
     zorlanmalar nota yansır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pwrhub.models import Sample

RESOURCES = ("cpu", "core", "mem", "disk", "gpu", "vram", "temp")
# Her bilgisayarda ölçülemeyebilen kaynaklar.
OPTIONAL = ("gpu", "vram", "temp")

# Bir kaynağın "zorlanmaya" başladığı eşikler (yüzde; sıcaklıkta °C).
THRESHOLDS = {"cpu": 70.0, "core": 85.0, "mem": 80.0, "disk": 80.0, "gpu": 90.0,
              "vram": 90.0, "temp": 83.0}
# Zorlanmanın en yükseğe ulaştığı değer.
LIMITS = {"cpu": 100.0, "core": 100.0, "mem": 100.0, "disk": 100.0, "gpu": 100.0,
          "vram": 100.0, "temp": 95.0}
# Kaynağın nota en fazla ne kadar katkı yapabileceği.
STRAIN_CAP = {"cpu": 100.0, "core": 60.0, "mem": 100.0, "disk": 100.0, "gpu": 50.0,
              "vram": 80.0, "temp": 60.0}

# Kaynağın ölçümdeki alan adı.
_FIELD = {"cpu": "cpu", "core": "cpu_core", "mem": "mem", "disk": "disk",
          "gpu": "gpu", "vram": "gpu_mem", "temp": "gpu_temp"}

RESOURCE_NAMES = {
    "cpu": "işlemci",
    "core": "tek bir işlemci çekirdeği",
    "mem": "bellek",
    "disk": "disk",
    "gpu": "ekran kartı",
    "vram": "ekran kartı belleği (VRAM)",
    "temp": "ekran kartı sıcaklığı",
}
# "...nin %48 kadarını" kalıbı için
_RESOURCE_OF = {"cpu": "işlemcinin", "core": "işlemcinin", "mem": "belleğin", "gpu": "ekran kartının"}
# Kaynağın oyun / diğer program payının okunduğu alanlar (çekirdek için işlemci payı kullanılır).
_SHARE_FIELD = {"cpu": "cpu", "core": "cpu", "mem": "mem", "disk": "disk", "gpu": "gpu"}

# Sık görülen programların anlaşılır adları.
_FRIENDLY = {
    "chrome.exe": "Chrome (tarayıcı)",
    "msedge.exe": "Edge (tarayıcı)",
    "firefox.exe": "Firefox (tarayıcı)",
    "opera.exe": "Opera (tarayıcı)",
    "brave.exe": "Brave (tarayıcı)",
    "discord.exe": "Discord",
    "spotify.exe": "Spotify",
    "obs64.exe": "OBS (yayın/kayıt)",
    "steam.exe": "Steam",
    "steamwebhelper.exe": "Steam",
    "epicgameslauncher.exe": "Epic Games Launcher",
    "msmpeng.exe": "Windows Defender (virüs taraması)",
    "searchindexer.exe": "Windows Arama dizinleyicisi",
    "tiworker.exe": "Windows Update",
    "onedrive.exe": "OneDrive",
    "teams.exe": "Microsoft Teams",
    "explorer.exe": "Windows Gezgini",
    "dwm.exe": "Windows masaüstü",
}

# Not aralıkları: (üst sınır, etiket, düzey). Düzey arayüzde rengi belirler.
_LEVELS = [
    (25, "Rahat", "good"),
    (50, "Hafif zorlandı", "warning"),
    (75, "Zorlandı", "serious"),
    (101, "Çok zorlandı", "critical"),
]


def friendly_name(process_name: str) -> str:
    """'chrome.exe' -> 'Chrome (tarayıcı)'; bilinmeyenlerde uzantısız ad."""
    if not process_name:
        return ""
    known = _FRIENDLY.get(process_name.lower())
    if known:
        return known
    return process_name[:-4] if process_name.lower().endswith(".exe") else process_name


def value_of(sample: Sample, resource: str) -> float:
    """Ölçümdeki kaynağın değeri (yüzde; sıcaklıkta °C). Ölçülemediyse 0."""
    return getattr(sample, _FIELD[resource]) or 0.0


def measured(sample: Sample, resource: str) -> bool:
    """Bu ölçümde kaynak okunabildi mi?"""
    return getattr(sample, _FIELD[resource]) is not None


def format_value(resource: str, value: float) -> str:
    """Değeri birimiyle yazar: '%95' ya da '87°C'."""
    return f"{round(value)}°C" if resource == "temp" else f"%{round(value)}"


def strain(resource: str, value: float) -> float:
    """Tek bir kaynağın zorlanması (0 ile o kaynağın üst sınırı arasında)."""
    low, high = THRESHOLDS[resource], LIMITS[resource]
    return max(0.0, min((value - low) / (high - low), 1.0)) * STRAIN_CAP[resource]


def sample_strain(sample: Sample) -> tuple[float, str]:
    """Bir ölçümün zorlanması ve buna sebep olan kaynak."""
    worst = max(RESOURCES, key=lambda r: (strain(r, value_of(sample, r)), -RESOURCES.index(r)))
    return strain(worst, value_of(sample, worst)), worst


def score_level(score: int) -> tuple[str, str]:
    """Nota karşılık gelen (etiket, düzey)."""
    for limit, label, level in _LEVELS:
        if score < limit:
            return label, level
    return _LEVELS[-1][1], _LEVELS[-1][2]


@dataclass
class WorstMoment:
    """Bilgisayarın en çok zorlandığı an."""

    ts: datetime
    resource: str            # RESOURCES içinden biri
    value: float             # o kaynağın o andaki kullanımı, %
    culprit: str             # o kaynağı en çok tüketen program (okunur ad)
    culprit_amount: float    # payı: yüzde; diskte MB/sn
    culprit_is_game: bool
    total_cpu: float = 0.0   # o andaki toplam işlemci kullanımı (çekirdek yorumu için)


@dataclass
class Report:
    score: int
    label: str
    level: str                               # good / warning / serious / critical
    average: dict[str, float]
    peak: dict[str, float]
    game_average: dict[str, float]           # oyunun kendi ortalama payı (cpu, mem, gpu)
    over_threshold: dict[str, float]         # oturumun yüzde kaçında eşik aşıldı
    worst: WorstMoment | None
    available: set[str] = field(default_factory=set)   # ölçülebilen isteğe bağlı kaynaklar
    lines: list[str] = field(default_factory=list)     # sade dilde yorumlar

    @property
    def has_gpu(self) -> bool:
        return "gpu" in self.available


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * fraction), len(ordered) - 1)]


def _find_worst(samples: list[Sample], game_name: str) -> WorstMoment | None:
    best, best_key = None, (0.0, 0.0)
    for sample in samples:
        level, resource = sample_strain(sample)
        key = (level, value_of(sample, resource))
        if level > 0 and key > best_key:
            best, best_key = (sample, resource), key
    if best is None:
        return None

    sample, resource = best
    if resource == "temp":
        # Sıcaklığın tek bir "sorumlu programı" yoktur.
        return WorstMoment(sample.ts, resource, sample.gpu_temp or 0.0, game_name, 0.0, True, sample.cpu)
    if resource == "vram":
        # VRAM için yalnızca oyunun payı bilinir.
        value = sample.gpu_mem or 0.0
        if sample.game_gpu_mem >= value / 2:
            return WorstMoment(sample.ts, resource, value, game_name, sample.game_gpu_mem, True, sample.cpu)
        return WorstMoment(sample.ts, resource, value, "diğer programlar",
                           value - sample.game_gpu_mem, False, sample.cpu)
    share = _SHARE_FIELD[resource]
    game_amount = getattr(sample, f"game_{share}")
    other_amount = getattr(sample, f"top_{share}")
    other_name = getattr(sample, f"top_{share}_name")
    if game_amount >= other_amount or not other_name:
        culprit, amount, is_game = game_name, game_amount, True
    else:
        culprit, amount, is_game = friendly_name(other_name), other_amount, False
    return WorstMoment(sample.ts, resource, value_of(sample, resource),
                       culprit, amount, is_game, sample.cpu)


def _pct(value: float) -> str:
    return f"%{round(value)}"


def _headline(worst: WorstMoment) -> str:
    """En zor anı anlatan cümle."""
    who = "oyunun kendisi" if worst.culprit_is_game else worst.culprit
    when = f"Saat {worst.ts:%H:%M} civarında"
    if worst.resource == "core":
        return (
            f"{when} işlemcinin bir çekirdeği {_pct(worst.value)} seviyesine çıktı "
            f"(toplam işlemci kullanımı yalnızca {_pct(worst.total_cpu)} iken). "
            f"Bu, işin tek çekirdeğe yığıldığını gösterir; o sırada işlemciyi en çok {who} kullanıyordu."
        )
    if worst.resource == "temp":
        return (f"{when} ekran kartı {round(worst.value)}°C sıcaklığa ulaştı. Bu sıcaklıkta "
                "ekran kartları kendini korumak için yavaşlar ve oyun takılabilir.")
    if worst.resource == "vram":
        return (f"{when} ekran kartı belleği (VRAM) {_pct(worst.value)} doldu; o sırada {who} "
                f"VRAM'in {_pct(worst.culprit_amount)} kadarını kullanıyordu.")
    name = RESOURCE_NAMES[worst.resource]
    if worst.resource == "disk":
        share = f"saniyede {worst.culprit_amount:.0f} MB okuyup yazıyordu"
    else:
        share = (f"{_RESOURCE_OF[worst.resource]} {_pct(worst.culprit_amount)} "
                 "kadarını tek başına kullanıyordu")
    return f"{when} {name} {_pct(worst.value)} seviyesine çıktı; o sırada {who} {share}."


def _advice(worst: WorstMoment) -> str:
    """En zor ana göre tek cümlelik öneri."""
    if worst.resource == "temp":
        return ("Kasanın hava akışını ve fanlardaki tozu kontrol et. Oyunda FPS sınırı "
                "koymak ekran kartını daha serin tutar.")
    if worst.resource == "vram":
        if worst.culprit_is_game:
            return ("Ekran kartı belleğini en çok oyunun kendisi doldurdu. Doku kalitesini "
                    "ya da çözünürlüğü düşürmek takılmaları azaltır.")
        return ("Ekran kartı belleğinin büyük kısmını oyun dışındaki programlar kullanıyordu. "
                "Tarayıcıyı ve video oynatan programları kapatmak yardımcı olabilir.")
    if not worst.culprit_is_game:
        return f"Oynarken {worst.culprit} programını kapatmak takılmaları azaltabilir."
    if worst.resource == "mem":
        return ("Belleği en çok oyunun kendisi kullanıyordu. Arka plandaki programları "
                "kapatmak ya da oyunun doku kalitesini düşürmek yardımcı olabilir.")
    if worst.resource == "cpu":
        return ("İşlemciyi en çok oyunun kendisi kullanıyordu. Oyunun grafik ayarlarını "
                "(özellikle gölge ve çizim mesafesi) düşürmek yardımcı olabilir.")
    if worst.resource == "core":
        return ("Oyun tek bir işlemci çekirdeğine yükleniyor. Oyunda FPS sınırı koymak ya da "
                "kalabalık sahneleri etkileyen ayarları (çizim mesafesi, nüfus yoğunluğu) "
                "düşürmek yardımcı olabilir.")
    if worst.resource == "gpu":
        return ("Ekran kartı sınırda çalıştı. Çözünürlüğü ya da grafik kalitesini düşürmek "
                "ya da oyunda FPS sınırı koymak daha akıcı bir oyun sağlar.")
    return ("Diski en çok oyunun kendisi kullanıyordu. Bu genelde yükleme ekranlarında "
            "olur; oyun bir SSD'ye kuruluysa daha az hissedilir.")


def analyze(samples: list[Sample], game_name: str = "Oyun") -> Report | None:
    """Bir oturumun örneklerinden rapor üretir. Örnek yoksa None döner."""
    if not samples:
        return None

    count = len(samples)
    available = {r for r in OPTIONAL if any(measured(s, r) for s in samples)}
    has_gpu = "gpu" in available
    strains = [sample_strain(s)[0] for s in samples]
    score = round(0.6 * _percentile(strains, 0.95) + 0.4 * sum(strains) / count)
    label, level = score_level(score)

    def mean(resource: str) -> float:
        # Yalnızca kaynağın okunabildiği ölçümlerin ortalaması.
        values = [value_of(s, resource) for s in samples if measured(s, resource)]
        return sum(values) / len(values) if values else 0.0

    average = {r: mean(r) for r in RESOURCES}
    peak = {r: max(value_of(s, r) for s in samples) for r in RESOURCES}
    game_average = {
        r: sum(getattr(s, f"game_{r}") for s in samples) / count for r in ("cpu", "mem", "gpu")
    }
    game_average["vram"] = sum(s.game_gpu_mem for s in samples) / count
    over = {
        r: sum(1 for s in samples if value_of(s, r) >= THRESHOLDS[r]) / count * 100
        for r in RESOURCES
    }
    worst = _find_worst(samples, game_name)

    lines: list[str] = []
    if worst is None:
        lines.append("Bilgisayarın bu oturumda hiç zorlanmadı; ölçülen bütün kaynaklar hep rahattı.")
    else:
        lines.append(_headline(worst))
        for r in RESOURCES:
            if over[r] < 5:
                continue
            if r == "temp":
                lines.append(f"Oturumun {_pct(over[r])} kadarında ekran kartı "
                             f"{round(THRESHOLDS[r])}°C'nin üzerindeydi.")
            elif r == "vram":
                lines.append(f"Oturumun {_pct(over[r])} kadarında ekran kartı belleği "
                             "neredeyse doluydu.")
            else:
                lines.append(
                    f"Oturumun {_pct(over[r])} kadarında {RESOURCE_NAMES[r]} sınıra yakın çalıştı."
                )
        if score >= 25:
            lines.append(_advice(worst))
        else:
            lines.append("Bu kısa süreli bir yükselmeydi; genel olarak bilgisayarın rahattı.")
    if not has_gpu:
        lines.append("Not: Bu oturumda ekran kartı ölçülemedi; ekran kartından kaynaklanan "
                     "takılmalar bu rapora yansımaz.")

    return Report(score, label, level, average, peak, game_average, over, worst, available, lines)
