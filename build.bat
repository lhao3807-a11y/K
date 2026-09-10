@echo off
rem Build single-file exe for DynastyKline (run from project root).
rem Usage: build.bat
setlocal
set PY=C:\Users\20578\.workbuddy\binaries\python\envs\default\Scripts\python.exe

"%PY%" -m PyInstaller --noconfirm --onefile --windowed ^
  --name "DynastyKline-V1.4.0" ^
  --add-data "dynasty-exchange.html;." ^
  --add-data "index.html;." ^
  --add-data "figure.html;." ^
  --add-data "figure-exchange.html;." ^
  --add-data "favorites.html;." ^
  --add-data "data.js;." ^
  --add-data "figure_data.js;." ^
  --add-data "kline.js;." ^
  --add-data "echarts.min.js;." ^
  --add-data "database\dynasty.db;database" ^
  app.py

if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)
echo.
echo BUILD OK: dist\DynastyKline-V1.4.0.exe
endlocal
