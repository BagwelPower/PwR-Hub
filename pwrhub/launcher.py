"""Oyun başlatma.

Steam ve Epic oyunları kendi başlatıcılarının adresiyle (steam://,
com.epicgames.launcher://) açılır; böylece bulut kaydı ve DRM sorunsuz çalışır.
Elle eklenen oyunlar doğrudan .exe dosyasından çalıştırılır.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pwrhub.models import Game


class LaunchError(Exception):
    """Oyun başlatılamadığında, kullanıcıya gösterilecek mesajla fırlatılır."""


def _open_uri(uri: str) -> None:
    """Adresi işletim sisteminin varsayılan uygulamasıyla açar."""
    if sys.platform == "win32":
        os.startfile(uri)  # noqa: S606 - yalnızca yerel başlatıcı adresleri
    else:
        # Windows dışı sistemler yalnızca geliştirme içindir.
        subprocess.Popen(["xdg-open", uri])


def _run_exe(exe: Path) -> subprocess.Popen | None:
    """Exe'yi kendi klasöründe çalıştırır (oyunlar dosyalarını oradan arar)."""
    if not exe.is_file():
        raise LaunchError(f"Oyun dosyası bulunamadı:\n{exe}")
    try:
        return subprocess.Popen([str(exe)], cwd=str(exe.parent))
    except OSError as exc:
        # WinError 740: oyun yönetici izni istiyor. Windows'un kendi izin
        # penceresini (UAC) göstermesi için kabuk üzerinden açıyoruz.
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 740:
            os.startfile(str(exe), cwd=str(exe.parent))  # noqa: S606
            return None
        raise LaunchError(f"Oyun başlatılamadı:\n{exc}") from exc


def launch(game: Game) -> subprocess.Popen | None:
    """Oyunu başlatır.

    Doğrudan çalıştırılan oyunlarda süreç nesnesi döner (2. aşamadaki oturum
    takibi bunu kullanacak); başlatıcı adresiyle açılanlarda None döner.
    """
    if game.launch_uri:
        try:
            _open_uri(game.launch_uri)
            return None
        except OSError as exc:
            # Başlatıcı kurulu değilse exe yolu varsa onu dene.
            if not game.exe_path:
                raise LaunchError(
                    f"{game.source_label} başlatıcısı açılamadı:\n{exc}"
                ) from exc
    if game.exe_path:
        return _run_exe(Path(game.exe_path))
    raise LaunchError("Bu oyun için başlatma bilgisi yok.")


def open_install_dir(game: Game) -> None:
    """Oyunun kurulu olduğu klasörü dosya gezgininde açar."""
    if not game.install_dir or not Path(game.install_dir).is_dir():
        raise LaunchError("Oyun klasörü bulunamadı.")
    _open_uri(game.install_dir)
