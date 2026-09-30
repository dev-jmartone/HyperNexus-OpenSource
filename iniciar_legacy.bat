@echo off
title Inventario VDI - Interfaz Anterior Jinja (Puerto 3001)
color 0B

echo ==================================================
echo   Iniciando Inventario VDI (Modelo Anterior Jinja)
echo   Servidor WSGI: Waitress (Puerto 3001)
echo ==================================================
echo.

pushd "%~dp0"

set LEGACY_UI=1
set PORT=3001

IF EXIST ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" server_legacy.py
) ELSE (
    python server_legacy.py
)

popd
pause
