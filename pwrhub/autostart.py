"""PwR Hub'ı Windows açılışında (sistem tepsisinde) başlatma ayarı.

Yalnızca geçerli kullanıcının "Run" kayıt defteri anahtarına tek bir satır
yazılır; yönetici izni gerekmez ve ayar kapatılınca satır silinir.
"""

from __future__ import annotations

import sys
from pathlib import Path

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "PwRHub"

SUPPORTED = sys.platform == "win32"


def launch_command() -> str:
    """Uygulamayı küçültülmüş başlatan komut satırı."""
    if getattr(sys, "frozen", False):
        # Tek dosyalık .exe olarak çalışıyoruz: doğrudan o dosya başlatılır.
        return f'"{sys.executable}" --minimized'
    python = Path(sys.executable)
    # Konsol penceresi açılmasın diye pythonw.exe tercih edilir.
    windowless = python.with_name("pythonw.exe")
    if windowless.is_file():
        python = windowless
    entry = Path(__file__).resolve().parent / "__main__.py"
    return f'"{python}" "{entry}" --minimized'


def is_enabled() -> bool:
    if not SUPPORTED:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
        return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    """Ayarı açar/kapatır; başarılıysa True döner."""
    if not SUPPORTED:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, _VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
