@echo off
REM Genera dist\AlbionMarket.exe (pide permisos de administrador al abrirse).
REM Requisitos: py -m pip install -r requirements.txt pyinstaller
cd /d "%~dp0"

REM Catálogo de ítems (datos públicos del juego, ao-data/ao-bin-dumps): se descarga si falta
if not exist data mkdir data
if not exist data\items.json curl -sSL -o data\items.json https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.json || exit /b 1
if not exist data\items.xml curl -sSL -o data\items.xml https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/items.xml || exit /b 1
py -c "from albion_market.catalog import Catalogo; Catalogo()" || exit /b 1

py -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin ^
  --name AlbionMarket --icon assets\icono.ico ^
  --add-data "data\catalogo.json;data" --add-data "assets\icono.ico;assets" ^
  --collect-data customtkinter ^
  gui.py
echo.
echo Listo: dist\AlbionMarket.exe
