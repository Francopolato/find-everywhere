@echo off
rem Avvio automatico di find-everywhere al login (solo utente corrente, no admin).
rem Copia l'exe in %LOCALAPPDATA%\find-everywhere e crea il collegamento nella
rem cartella Esecuzione automatica, con il parametro --startup:
rem la finestra resta nascosta e si apre solo con la hotkey.
setlocal
cd /d "%~dp0"

set "EXE="
if exist "%~dp0FindEverywhere.exe" set "EXE=%~dp0FindEverywhere.exe"
if not defined EXE if exist "%~dp0dist\FindEverywhere.exe" set "EXE=%~dp0dist\FindEverywhere.exe"
if not defined EXE if exist "%~dp0dist\SpotlightPy.exe" set "EXE=%~dp0dist\SpotlightPy.exe"

if not defined EXE (
  echo ERRORE: non trovo l'exe. Compila prima con:  build.bat FindEverywhere
  pause
  exit /b 1
)

set "DESTDIR=%LOCALAPPDATA%\find-everywhere"
if not exist "%DESTDIR%" mkdir "%DESTDIR%"
copy /y "%EXE%" "%DESTDIR%\FindEverywhere.exe" >nul
if errorlevel 1 (
  echo ERRORE: impossibile copiare l'exe in "%DESTDIR%"
  pause
  exit /b 1
)

echo Exe installato in: %DESTDIR%\FindEverywhere.exe

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$dir=[Environment]::GetFolderPath('Startup'); $lnk=Join-Path $dir 'find-everywhere.lnk'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($lnk); $s.TargetPath=Join-Path $env:LOCALAPPDATA 'find-everywhere\FindEverywhere.exe'; $s.Arguments='--startup'; $s.WorkingDirectory=Join-Path $env:LOCALAPPDATA 'find-everywhere'; $s.IconLocation=$s.TargetPath + ',0'; $s.Description='find-everywhere (Spotlight per Windows)'; $s.Save(); Write-Output ('Collegamento creato: ' + $lnk)"

if errorlevel 1 (
  echo ERRORE nella creazione del collegamento
  pause
  exit /b 1
)

echo.
echo Fatto. Al prossimo accesso l'app parte nascosta e risponde alla hotkey.
echo NOTA: la hotkey globale deve essere attiva (Impostazioni -^> Hotkey principale).
echo Per annullare: uninstall-autostart.bat
pause
