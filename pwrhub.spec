# PyInstaller tarifi: tek dosyalık PwRHub.exe üretir.
#
#   pyinstaller pwrhub.spec
#
# Çıktı: dist/PwRHub.exe  (kurulum gerektirmez; çift tıklayınca çalışır)

a = Analysis(
    ["pwrhub/__main__.py"],
    pathex=["."],
    # Logo dosyaları paketin içinde `pwrhub/assets` olarak yer alır.
    datas=[("pwrhub/assets", "pwrhub/assets")],
    # Kullanılmayan büyük Qt parçaları pakete girmesin (dosya küçük kalsın).
    excludes=[
        "tkinter", "unittest", "pydoc", "PySide6.QtNetwork", "PySide6.QtQml",
        "PySide6.QtQuick", "PySide6.QtOpenGL", "PySide6.QtPdf", "PySide6.QtSql",
        "PySide6.QtTest", "PySide6.QtDBus", "PySide6.QtDesigner", "PySide6.QtHelp",
        "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtPrintSupport",
    ],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="PwRHub",
    icon="pwrhub/assets/pwrhub.ico",
    console=False,          # siyah konsol penceresi açılmasın
    upx=False,              # sıkıştırma virüs programlarını yanıltabiliyor
)
