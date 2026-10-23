@echo off
rem Rimuove l'avvio automatico creato da install-autostart.bat
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$lnk=Join-Path ([Environment]::GetFolderPath('Startup')) 'find-everywhere.lnk'; if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Output ('Rimosso: ' + $lnk) } else { Write-Output 'Nessun collegamento trovato' }"

echo.
echo Fatto. L'exe copiato resta in %LOCALAPPDATA%\find-everywhere (puoi cancellarlo a mano).
pause
