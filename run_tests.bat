@echo off
title Inventario VDI - Suite de Tests (Backend + Frontend)
color 0B

echo ==================================================
echo   Corriendo tests de Inventario VDI
echo   Backend: pytest  /  Frontend: vitest
echo ==================================================
echo.

pushd "%~dp0"

echo --- Backend (pytest) ---
IF EXIST ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pytest tests\ -p no:warnings
) ELSE (
    python -m pytest tests\ -p no:warnings
)
set BACKEND_RESULT=%ERRORLEVEL%

echo.
echo --- Frontend (vitest) ---
pushd web\frontend
call npm test
set FRONTEND_RESULT=%ERRORLEVEL%
popd

echo.
echo ==================================================
if %BACKEND_RESULT%==0 (echo Backend: OK) else (echo Backend: FALLO)
if %FRONTEND_RESULT%==0 (echo Frontend: OK) else (echo Frontend: FALLO)
echo ==================================================

popd
pause
