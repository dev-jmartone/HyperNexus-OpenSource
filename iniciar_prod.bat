@echo off
title HyperNexus - Servidor Produccion (Waitress WSGI)
color 0A

echo ==============================================================================
echo   HYPERNEXUS - MODO PRODUCCION
echo   Servidor WSGI: Waitress (Multi-thread 0.0.0.0:5000)
echo ==============================================================================
echo.

pushd "%~dp0"

REM 1. Verificar archivo .env
IF NOT EXIST ".env" (
    echo [*] Generando archivo .env a partir de .env.example...
    copy .env.example .env >nul
)

REM 2. Resolver ejecutable de Python
SET PYTHON_BIN=python
IF EXIST ".venv\Scripts\python.exe" (
    SET PYTHON_BIN=.venv\Scripts\python.exe
)

REM 3. Sembrar base de datos si no existe
IF NOT EXIST "data\inventario.db" (
    echo [*] Inicializando base de datos con datos simulados...
    "%PYTHON_BIN%" seed_db.py
)

REM 4. Abrir navegador automáticamente tras el inicio
start /B cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:5000"

REM 5. Iniciar servidor de producción
echo [*] Iniciando servicio en http://localhost:5000 ...
echo [i] Presiona Ctrl+C para detener el servidor.
echo.
"%PYTHON_BIN%" server_prod.py

popd
pause
