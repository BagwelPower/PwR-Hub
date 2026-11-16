@echo off
rem Tek dosyalik PwRHub.exe uretir. Windows'ta proje klasorunde calistirin:
rem     build.bat
rem Cikti: dist\PwRHub.exe

python -m pip install -r requirements.txt pyinstaller || goto :hata
python -m PyInstaller --noconfirm --clean pwrhub.spec || goto :hata
echo.
echo Hazir: dist\PwRHub.exe
goto :eof

:hata
echo.
echo Derleme basarisiz oldu. Yukaridaki hata mesajina bakin.
exit /b 1
