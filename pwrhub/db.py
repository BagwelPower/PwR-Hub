"""Yerel SQLite veritabanı.

Kütüphanedeki oyunlar ve kullanıcının eklediği klasörler burada saklanır.
Dosya yalnızca kullanıcının bilgisayarında durur.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from pwrhub.models import SOURCE_MANUAL, Game, Sample, Session

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT NOT NULL,
    source_id        TEXT NOT NULL,
    name             TEXT NOT NULL,
    install_dir      TEXT NOT NULL DEFAULT '',
    exe_path         TEXT NOT NULL DEFAULT '',
    launch_uri       TEXT NOT NULL DEFAULT '',
    cover_path       TEXT NOT NULL DEFAULT '',
    custom_cover     TEXT NOT NULL DEFAULT '',
    installed        INTEGER NOT NULL DEFAULT 1,
    hidden           INTEGER NOT NULL DEFAULT 0,
    added_at         TEXT NOT NULL,
    last_launched_at TEXT NOT NULL DEFAULT '',
    UNIQUE (source, source_id)
);

-- Kullanıcının elle eklediği klasörler ve tek tek seçtiği .exe dosyaları.
CREATE TABLE IF NOT EXISTS manual_paths (
    path TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('folder', 'exe'))
);

-- Oyun oturumları. Oturum başlar başlamaz yazılır ve oyun açıkken `ended_at`
-- düzenli güncellenir; PwR Hub beklenmedik kapansa bile kayıt kaybolmaz.
CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id      INTEGER NOT NULL REFERENCES games (id),
    started_at   TEXT NOT NULL,
    ended_at     TEXT NOT NULL,
    duration_s   INTEGER NOT NULL DEFAULT 0,
    strain_score INTEGER              -- 0-100 zorlanma notu (performans kaydı yoksa NULL)
);
CREATE INDEX IF NOT EXISTS idx_sessions_game ON sessions (game_id, started_at);

-- Oturum sırasında birkaç saniyede bir alınan performans örnekleri.
-- Yüzdeler 0-100 arasıdır ve bütün bilgisayara göredir.
CREATE TABLE IF NOT EXISTS samples (
    session_id    INTEGER NOT NULL REFERENCES sessions (id),
    ts            TEXT NOT NULL,
    cpu           REAL NOT NULL,   -- toplam işlemci kullanımı
    mem           REAL NOT NULL,   -- toplam bellek kullanımı
    disk          REAL NOT NULL,   -- disk meşguliyeti
    game_cpu      REAL NOT NULL,   -- oyunun işlemci payı
    game_mem      REAL NOT NULL,   -- oyunun bellek payı
    game_disk     REAL NOT NULL,   -- oyunun disk okuma+yazma hızı (MB/sn)
    top_cpu_name  TEXT NOT NULL DEFAULT '',  -- oyun dışında en çok işlemci kullanan program
    top_cpu       REAL NOT NULL DEFAULT 0,
    top_mem_name  TEXT NOT NULL DEFAULT '',
    top_mem       REAL NOT NULL DEFAULT 0,
    top_disk_name TEXT NOT NULL DEFAULT '',
    top_disk      REAL NOT NULL DEFAULT 0    -- MB/sn
);
CREATE INDEX IF NOT EXISTS idx_samples_session ON samples (session_id, ts);

-- Kullanıcı ayarları (anahtar -> değer).
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Sonradan eklenen sütunlar. Eski sürümle oluşturulmuş veritabanlarına açılışta
# eklenir; böylece güncelleme sırasında kullanıcının verisi korunur.
_MIGRATIONS = [
    ("samples", "cpu_core", "REAL NOT NULL DEFAULT 0"),
    ("samples", "gpu", "REAL"),
    ("samples", "game_gpu", "REAL NOT NULL DEFAULT 0"),
    ("samples", "top_gpu_name", "TEXT NOT NULL DEFAULT ''"),
    ("samples", "top_gpu", "REAL NOT NULL DEFAULT 0"),
    ("samples", "gpu_mem", "REAL"),
    ("samples", "game_gpu_mem", "REAL NOT NULL DEFAULT 0"),
    ("samples", "gpu_temp", "REAL"),
]

_GAME_COLUMNS = (
    "g.id, g.source, g.source_id, g.name, g.install_dir, g.exe_path, g.launch_uri, "
    "g.cover_path, g.custom_cover, g.installed, g.hidden, g.added_at, g.last_launched_at, "
    "COALESCE(st.total_seconds, 0) AS total_seconds, "
    "COALESCE(st.session_count, 0) AS session_count, "
    "COALESCE(st.last_played_at, '') AS last_played_at"
)

# Her oyunun oynanma özetini oyun satırına ekleyen sorgu parçası.
_GAME_FROM = """
    FROM games g
    LEFT JOIN (
        SELECT game_id,
               SUM(duration_s) AS total_seconds,
               COUNT(*)        AS session_count,
               MAX(ended_at)   AS last_played_at
        FROM sessions GROUP BY game_id
    ) st ON st.game_id = g.id
"""

_SAMPLE_COLUMNS = (
    "ts", "cpu", "mem", "disk", "game_cpu", "game_mem", "game_disk",
    "top_cpu_name", "top_cpu", "top_mem_name", "top_mem", "top_disk_name", "top_disk",
    "cpu_core", "gpu", "game_gpu", "top_gpu_name", "top_gpu",
    "gpu_mem", "game_gpu_mem", "gpu_temp",
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm(path: str) -> str:
    """Yolları karşılaştırmak için ortak biçim."""
    return os.path.normcase(os.path.normpath(path)).lower() if path else ""


class Database:
    """Veritabanı erişimini tek yerde toplayan küçük sarmalayıcı."""

    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        # Arayüz, tarama ve izleme ayrı bağlantılardan aynı anda eriştiği için
        # okuma ile yazmanın birbirini bekletmediği WAL kipini kullanıyoruz.
        self.conn.execute("PRAGMA journal_mode = WAL")
        # Her yazmada diski zorla beklememek için. Uygulama çökse de veri
        # bozulmaz; yalnızca elektrik kesilirse son birkaç saniye kaybolabilir.
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.executescript(_SCHEMA)
        for table, column, definition in _MIGRATIONS:
            existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ oyunlar

    @staticmethod
    def _row_to_game(row: sqlite3.Row) -> Game:
        return Game(
            id=row["id"],
            source=row["source"],
            source_id=row["source_id"],
            name=row["name"],
            install_dir=row["install_dir"],
            exe_path=row["exe_path"],
            launch_uri=row["launch_uri"],
            cover_path=row["cover_path"],
            custom_cover=row["custom_cover"],
            installed=bool(row["installed"]),
            hidden=bool(row["hidden"]),
            added_at=row["added_at"],
            last_launched_at=row["last_launched_at"],
            total_seconds=row["total_seconds"],
            session_count=row["session_count"],
            last_played_at=row["last_played_at"],
        )

    def list_games(self, include_hidden: bool = False) -> list[Game]:
        """Kurulu oyunları döndürür (varsayılan olarak gizlenenler hariç)."""
        sql = f"SELECT {_GAME_COLUMNS} {_GAME_FROM} WHERE g.installed = 1"
        if not include_hidden:
            sql += " AND g.hidden = 0"
        sql += " ORDER BY g.name COLLATE NOCASE"
        return [self._row_to_game(r) for r in self.conn.execute(sql)]

    def get_game(self, game_id: int) -> Game | None:
        row = self.conn.execute(
            f"SELECT {_GAME_COLUMNS} {_GAME_FROM} WHERE g.id = ?", (game_id,)
        ).fetchone()
        return self._row_to_game(row) if row else None

    def sync_source(self, source: str, games: list[Game]) -> None:
        """Bir kaynağın (steam/epic/manual) tarama sonucunu veritabanına işler.

        - Yeni oyunlar eklenir, var olanların bilgileri güncellenir.
        - Artık bulunmayan oyunlar silinmez, `installed = 0` yapılır; böylece
          oyun yeniden kurulursa geçmiş verisi (ileride istatistikler) korunur.
        - Kullanıcı tercihleri (gizleme, özel kapak, ad) taramayla ezilmez.
        """
        now = _now()
        with self.conn:
            self.conn.execute("UPDATE games SET installed = 0 WHERE source = ?", (source,))
            for g in games:
                self.conn.execute(
                    """
                    INSERT INTO games (source, source_id, name, install_dir, exe_path,
                                       launch_uri, cover_path, installed, added_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT (source, source_id) DO UPDATE SET
                        name        = excluded.name,
                        install_dir = excluded.install_dir,
                        exe_path    = excluded.exe_path,
                        launch_uri  = excluded.launch_uri,
                        cover_path  = excluded.cover_path,
                        installed   = 1
                    """,
                    (g.source, g.source_id, g.name, g.install_dir, g.exe_path,
                     g.launch_uri, g.cover_path, now),
                )

    def sync_manual(self, games: list[Game]) -> None:
        """Elle eklenen oyunları işler; Steam/Epic'te zaten olanları atlar.

        Kullanıcı Steam kütüphane klasörünü elle de eklerse aynı oyun iki kez
        görünmesin diye kurulum klasörü çakışanlar elenir.
        """
        known = {
            _norm(row["install_dir"])
            for row in self.conn.execute(
                "SELECT install_dir FROM games WHERE source != ? AND installed = 1",
                (SOURCE_MANUAL,),
            )
        }
        known.discard("")
        unique: dict[str, Game] = {}
        for g in games:
            if _norm(g.install_dir) not in known:
                unique.setdefault(g.source_id, g)
        self.sync_source(SOURCE_MANUAL, list(unique.values()))

    def set_hidden(self, game_id: int, hidden: bool) -> None:
        with self.conn:
            self.conn.execute("UPDATE games SET hidden = ? WHERE id = ?", (int(hidden), game_id))

    def set_custom_cover(self, game_id: int, path: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE games SET custom_cover = ? WHERE id = ?", (path, game_id))

    def mark_launched(self, game_id: int) -> str:
        """Oyunun son başlatılma zamanını şimdi olarak kaydeder."""
        now = _now()
        with self.conn:
            self.conn.execute(
                "UPDATE games SET last_launched_at = ? WHERE id = ?", (now, game_id)
            )
        return now

    # ------------------------------------------------- elle eklenen yollar

    def add_manual_path(self, path: str, kind: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO manual_paths (path, kind) VALUES (?, ?)", (path, kind)
            )

    def remove_manual_path(self, path: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM manual_paths WHERE path = ?", (path,))

    def list_manual_paths(self) -> list[tuple[str, str]]:
        """(yol, tür) listesi; tür 'folder' ya da 'exe'."""
        rows = self.conn.execute("SELECT path, kind FROM manual_paths ORDER BY path")
        return [(r["path"], r["kind"]) for r in rows]

    # ------------------------------------------------------------- oturumlar

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            game_id=row["game_id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]),
            duration_s=row["duration_s"],
            strain_score=row["strain_score"],
        )

    def start_session(self, game_id: int, now: datetime) -> int:
        stamp = now.isoformat(timespec="seconds")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO sessions (game_id, started_at, ended_at) VALUES (?, ?, ?)",
                (game_id, stamp, stamp),
            )
        return cur.lastrowid

    def touch_session(self, session_id: int, now: datetime) -> None:
        """Oturumun bitiş zamanını 'şu an'a çeker (oyun hâlâ açık)."""
        row = self.conn.execute(
            "SELECT started_at FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return
        duration = int((now - datetime.fromisoformat(row["started_at"])).total_seconds())
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET ended_at = ?, duration_s = ? WHERE id = ?",
                (now.isoformat(timespec="seconds"), max(duration, 0), session_id),
            )

    def set_session_score(self, session_id: int, score: int | None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET strain_score = ? WHERE id = ?", (score, session_id)
            )

    def delete_session(self, session_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM samples WHERE session_id = ?", (session_id,))
            self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def get_session(self, session_id: int) -> Session | None:
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row_to_session(row) if row else None

    def last_session(self, game_id: int) -> Session | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE game_id = ? ORDER BY ended_at DESC LIMIT 1", (game_id,)
        ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(self, game_id: int | None = None, since: datetime | None = None) -> list[Session]:
        """Oturumları yeniden eskiye döndürür; oyuna ve tarihe göre süzülebilir."""
        sql, args = "SELECT * FROM sessions WHERE 1 = 1", []
        if game_id is not None:
            sql += " AND game_id = ?"
            args.append(game_id)
        if since is not None:
            sql += " AND ended_at >= ?"
            args.append(since.isoformat(timespec="seconds"))
        sql += " ORDER BY started_at DESC"
        return [self._row_to_session(r) for r in self.conn.execute(sql, args)]

    def top_games(self, limit: int = 10) -> list[Game]:
        """En çok oynanan oyunlar (kaldırılmış olanlar dahil, gizlenenler hariç)."""
        sql = (
            f"SELECT {_GAME_COLUMNS} {_GAME_FROM} "
            "WHERE st.total_seconds > 0 AND g.hidden = 0 "
            "ORDER BY st.total_seconds DESC LIMIT ?"
        )
        return [self._row_to_game(r) for r in self.conn.execute(sql, (limit,))]

    # ------------------------------------------------------ performans örnekleri

    def add_sample(self, session_id: int, sample: Sample) -> None:
        self.add_samples([(session_id, sample)])

    def add_samples(self, items: list[tuple[int, Sample]]) -> None:
        """Birden fazla örneği tek bir disk yazmasıyla kaydeder."""
        if not items:
            return
        rows = []
        for session_id, sample in items:
            values = [session_id] + [getattr(sample, c) for c in _SAMPLE_COLUMNS]
            values[1] = sample.ts.isoformat(timespec="seconds")
            rows.append(values)
        marks = ", ".join("?" * (len(_SAMPLE_COLUMNS) + 1))
        with self.conn:
            self.conn.executemany(
                f"INSERT INTO samples (session_id, {', '.join(_SAMPLE_COLUMNS)}) VALUES ({marks})",
                rows,
            )

    def list_samples(self, session_id: int) -> list[Sample]:
        rows = self.conn.execute(
            f"SELECT {', '.join(_SAMPLE_COLUMNS)} FROM samples WHERE session_id = ? ORDER BY ts",
            (session_id,),
        )
        samples = []
        for row in rows:
            data = dict(row)
            data["ts"] = datetime.fromisoformat(data["ts"])
            samples.append(Sample(**data))
        return samples

    # ------------------------------------------------------------------ ayarlar

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_flag(self, key: str, default: bool = False) -> bool:
        """Açık/kapalı türündeki ayarı okur."""
        return self.get_setting(key, "1" if default else "0") == "1"

    def set_flag(self, key: str, value: bool) -> None:
        self.set_setting(key, "1" if value else "0")
