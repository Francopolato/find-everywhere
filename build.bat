@echo off
rem Uso:  build.bat                 -> dist\SpotlightPy.exe
rem       build.bat FindEverywhere -> dist\FindEverywhere.exe
setlocal
cd /d "%~dp0"

set "APPNAME=%~1"
if "%APPNAME%"=="" set "APPNAME=SpotlightPy"

echo === Build %APPNAME%.exe ===
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "%APPNAME%" ^
  --hidden-import win32com.client ^
  --hidden-import pythoncom ^
  --hidden-import pywintypes ^
  --hidden-import win32timezone ^
  --collect-submodules win32com ^
  app.py

if errorlevel 1 (
  echo.
  echo BUILD FALLITA
  pause
  exit /b 1
)

echo.
echo Fatto: dist\%APPNAME%.exe
echo Copia il file dove vuoi (es. sul Desktop) e avvialo.
pause
