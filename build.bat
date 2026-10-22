@echo off
setlocal
cd /d "%~dp0"

echo === Build SpotlightPy.exe ===
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name SpotlightPy ^
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
echo Fatto: dist\SpotlightPy.exe
echo Copia il file dove vuoi (es. sul Desktop) e avvialo.
pause
