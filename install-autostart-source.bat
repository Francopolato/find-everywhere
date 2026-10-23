@echo off
rem Avvio automatico SENZA exe (per sistemi dove l'antivirus elimina l'eseguibile
rem compilato con PyInstaller).
rem Crea un collegamento in Esecuzione automatica che lancia:
rem   pythonw.exe "C:\...\app.py" --startup
rem Nessun file eseguibile nuovo, nessuna modifica al registro.
setlocal
cd /d "%~dp0"

if not exist "%~dp0app.py" (
  echo ERRORE: app.py non trovato in "%~dp0"
  pause
  exit /b 1
)

set "PYW="
for /f "delims=" %%I in ('where pythonw 2^>nul ^| findstr /v /i "\\WindowsApps\\"') do if not defined PYW set "PYW=%%I"
if not defined PYW (
  for /f "delims=" %%I in ('where python 2^>nul ^| findstr /v /i "\\WindowsApps\\"') do if not defined PYW set "PYW=%%~dpIpythonw.exe"
)
if not defined PYW (
  echo ERRORE: pythonw.exe non e' nel PATH. Installa Python o aggiungilo al PATH.
  pause
  exit /b 1
)
if not exist "%PYW%" (
  echo ERRORE: trovato "%PYW%" ma il file non esiste.
  pause
  exit /b 1
)

set "FE_PYW=%PYW%"
set "FE_APP=%~dp0app.py"
set "FE_DIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$q=[char]34; $lnk=Join-Path ([Environment]::GetFolderPath('Startup')) 'find-everywhere.lnk'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($lnk); $s.TargetPath=$env:FE_PYW; $s.Arguments=$q + $env:FE_APP + $q + ' --startup'; $s.WorkingDirectory=$env:FE_DIR; $s.IconLocation=($env:FE_PYW + ',0'); $s.Description='find-everywhere (da sorgente Python)'; $s.Save(); Write-Output ('Collegamento creato: ' + $lnk); Write-Output ('  target: ' + $s.TargetPath); Write-Output ('  args  : ' + $s.Arguments)"

if errorlevel 1 (
  echo ERRORE nella creazione del collegamento
  pause
  exit /b 1
)

echo.
echo Fatto: al prossimo accesso l'app parte da sorgente, nascosta, e risponde
echo alla hotkey (che deve essere attiva nelle impostazioni).
echo Per annullare: uninstall-autostart.bat
pause
