@echo off
rem ============================================================================
rem  install-autostart.bat - avvio automatico di find-everywhere al login
rem
rem  Sceglie da solo come avviare l'app:
rem    * con l'eseguibile compilato (se presente e non bloccato)
rem    * altrimenti con il Python installato (pythonw + app.py)
rem
rem  Uso:
rem    install-autostart.bat                auto: exe se c'e', altrimenti Python
rem    install-autostart.bat exe            forza l'exe
rem    install-autostart.bat source         forza il sorgente (pythonw)
rem    install-autostart.bat --dry-run      mostra cosa farebbe, senza scrivere
rem
rem  Solo utente corrente, nessun admin, nessuna modifica al registro.
rem  Per annullare: uninstall-autostart.bat
rem ============================================================================
setlocal
cd /d "%~dp0"

set "MODE=auto"
set "DRY="

:parse
if "%~1"=="" goto after_parse
if /i "%~1"=="exe"        set "MODE=exe"
if /i "%~1"=="source"     set "MODE=source"
if /i "%~1"=="py"         set "MODE=source"
if /i "%~1"=="python"     set "MODE=source"
if /i "%~1"=="--dry-run"  set "DRY=1"
if /i "%~1"=="dry"        set "DRY=1"
shift
goto parse
:after_parse

rem --------------------------------------------------- pythonw (per il sorgente)
rem NB: rilevamento a livello top, fuori da blocchi if(): dentro le parentesi
rem gli escape di "for /f ... | findstr" non sopravvivono.
set "PYW="
for /f "delims=" %%I in ('where pythonw 2^>nul ^| findstr /v /i "\\WindowsApps\\"') do if not defined PYW set "PYW=%%I"
if not defined PYW for /f "delims=" %%I in ('where python 2^>nul ^| findstr /v /i "\\WindowsApps\\"') do if not defined PYW set "PYW=%%~dpIpythonw.exe"

rem ---------------------------------------------------------------- eseguibile
set "EXE="
if /i "%MODE%"=="source" goto skip_exe

if exist "%~dp0FindEverywhere.exe" set "EXE=%~dp0FindEverywhere.exe"
if not defined EXE if exist "%~dp0dist\FindEverywhere.exe" set "EXE=%~dp0dist\FindEverywhere.exe"
if not defined EXE if exist "%~dp0dist\SpotlightPy.exe" set "EXE=%~dp0dist\SpotlightPy.exe"
if not defined EXE if exist "%LOCALAPPDATA%\find-everywhere\FindEverywhere.exe" set "EXE=%LOCALAPPDATA%\find-everywhere\FindEverywhere.exe"

rem un exe troppo piccolo e' quasi sempre un file in quarantena o uno stub
if defined EXE set "EXE_SIZE=0"
if defined EXE for %%F in ("%EXE%") do set "EXE_SIZE=%%~zF"
if not "%EXE_SIZE%"=="0" if %EXE_SIZE% LSS 10485760 set "EXE="
if defined EXE if "%EXE_SIZE%"=="0" set "EXE="
:skip_exe

if not defined EXE if /i "%MODE%"=="exe" (
  echo ERRORE: modalita' "exe" richiesta ma nessun eseguibile valido trovato.
  echo Ho cercato in:
  echo   %~dp0FindEverywhere.exe
  echo   %~dp0dist\FindEverywhere.exe
  echo   %~dp0dist\SpotlightPy.exe
  echo   %LOCALAPPDATA%\find-everywhere\FindEverywhere.exe
  echo Compila con:  build.bat FindEverywhere
  pause
  exit /b 1
)

rem ------------------------------------------------------------ scelta modalita'
set "FE_TARGET="

if defined EXE goto mode_exe

rem ------------------------------------------------ modalita' sorgente (Python)
if not exist "%~dp0app.py" (
  echo ERRORE: ne' eseguibile ne' app.py trovati in "%~dp0"
  pause
  exit /b 1
)
if not defined PYW (
  echo ERRORE: pythonw.exe non e' nel PATH. Installa Python o aggiungilo al PATH.
  pause
  exit /b 1
)
if not exist "%PYW%" (
  echo ERRORE: "%PYW%" non esiste.
  pause
  exit /b 1
)

echo Modalita': SORGENTE ^(Python, nessun exe^)
echo   pythonw: %PYW%
echo   script : %~dp0app.py
set "FE_TARGET=%PYW%"
set FE_ARGS="%~dp0app.py" --startup
set "FE_DIR=%~dp0"
set "FE_DESC=find-everywhere (sorgente Python)"
goto install

:mode_exe
echo Modalita': ESEGUIBILE
echo   exe trovato: %EXE%
set "FE_TARGET=%LOCALAPPDATA%\find-everywhere\FindEverywhere.exe"
set "FE_ARGS=--startup"
set "FE_DIR=%LOCALAPPDATA%\find-everywhere"
set "FE_DESC=find-everywhere (eseguibile)"
if defined DRY goto dry
if not exist "%LOCALAPPDATA%\find-everywhere" mkdir "%LOCALAPPDATA%\find-everywhere"
copy /y "%EXE%" "%FE_TARGET%" >nul
if errorlevel 1 (
  echo ERRORE: impossibile copiare l'exe in "%LOCALAPPDATA%\find-everywhere"
  pause
  exit /b 1
)
echo   exe installato in: %FE_TARGET%
goto install

rem ---------------------------------------------------------------- installazione
:install
if defined DRY goto dry

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$q=[char]34; $lnk=Join-Path ([Environment]::GetFolderPath('Startup')) 'find-everywhere.lnk'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($lnk); $s.TargetPath=$env:FE_TARGET; $s.Arguments=$env:FE_ARGS; $s.WorkingDirectory=$env:FE_DIR; $s.IconLocation=($env:FE_TARGET + ',0'); $s.Description=$env:FE_DESC; $s.Save(); Write-Output ('Collegamento creato: ' + $lnk); Write-Output ('  target: ' + $s.TargetPath); Write-Output ('  args  : ' + $s.Arguments)"

if errorlevel 1 (
  echo ERRORE nella creazione del collegamento
  pause
  exit /b 1
)
echo.
echo Fatto: al prossimo accesso l'app parte nascosta e risponde alla hotkey.
echo NOTA: la hotkey globale deve essere attiva ^(Impostazioni -^> Hotkey principale^).
goto footer

:dry
echo.
echo -- DRY RUN: nessun file scritto. Avrei creato il collegamento in
echo    "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\find-everywhere.lnk"
echo    target : %FE_TARGET%
echo    args   : %FE_ARGS%
echo    workdir: %FE_DIR%

:footer
echo Per annullare: uninstall-autostart.bat
pause
