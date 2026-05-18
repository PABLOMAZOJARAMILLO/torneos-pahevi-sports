@echo off
setlocal

REM Backup semanal de Torneos IMCRED
REM Guarda una copia JSON en C:\TorneosIMCRED\backups

cd /d C:\TorneosIMCRED

if not exist backups mkdir backups

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm"') do set FECHA=%%i
set ARCHIVO=backups\backup_torneos_%FECHA%.json

echo ===============================================
echo Creando backup: %ARCHIVO%
echo ===============================================

venv\Scripts\python.exe manage.py dumpdata --exclude auth.permission --exclude contenttypes --indent 2 > "%ARCHIVO%"

if errorlevel 1 (
    echo.
    echo ERROR: No se pudo crear el backup.
    echo Revisa que la base de datos este conectada y que el proyecto funcione.
    pause
    exit /b 1
)

echo.
echo Backup creado correctamente:
echo C:\TorneosIMCRED\%ARCHIVO%
echo.
pause
