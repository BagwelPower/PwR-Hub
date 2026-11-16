"""Oyun tarayıcıları: Steam, Epic Games ve elle eklenen klasörler.

Her tarayıcı yalnızca yerel dosyaları okur; internete bağlanmaz.
"""

from pwrhub.scanners.epic import scan_epic
from pwrhub.scanners.folder import scan_exe, scan_folder
from pwrhub.scanners.steam import scan_steam

__all__ = ["scan_steam", "scan_epic", "scan_folder", "scan_exe"]
