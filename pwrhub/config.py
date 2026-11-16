"""Uygulamanın veri klasörü ve dosya yolları.

Bütün kullanıcı verisi (veritabanı, seçilen kapak resimleri) yalnızca bu
klasörde, kullanıcının kendi bilgisayarında durur. Hiçbir şey internete
gönderilmez.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "PwRHub"


def data_dir() -> Path:
    """Veri klasörünü döndürür, yoksa oluşturur.

    Windows'ta: %APPDATA%\\PwRHub
    Test ve geliştirme için PWRHUB_DATA_DIR ortam değişkeniyle değiştirilebilir.
    """
    override = os.environ.get("PWRHUB_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    else:
        # Windows dışı sistemler yalnızca geliştirme/test içindir.
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    """SQLite veritabanı dosyasının yolu."""
    return data_dir() / "pwrhub.db"


def covers_dir() -> Path:
    """Kullanıcının elle seçtiği kapak resimlerinin kopyalandığı klasör."""
    path = data_dir() / "covers"
    path.mkdir(parents=True, exist_ok=True)
    return path
