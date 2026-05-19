@echo off
title MUSIC DL
cd /d "%~dp0"

echo.
echo ============================================================
echo   MUSIC DL  ^|  Verification des dependances...
echo ============================================================
echo.

REM ── Verifier que Python est accessible ──────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python introuvable dans le PATH.
    echo          Installe Python depuis https://python.org
    echo          et coche "Add Python to PATH" a l'installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [OK] %%v detecte

REM ── Installer / mettre a jour les dependances ────────────────
echo.
echo [1/2] Dependances principales  (requirements.txt)...
pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo [ERREUR] Installation requirements.txt echouee.
    echo          Lance cette fenetre en administrateur ou verifie ta connexion.
    pause
    exit /b 1
)
echo       OK

echo [2/2] Dependances SpotdlRip    (SpotdlRip/requirements.txt)...
pip install -r SpotdlRip\requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo [ERREUR] Installation SpotdlRip/requirements.txt echouee.
    pause
    exit /b 1
)
echo       OK

echo.
echo ============================================================
echo   Tout est pret  ^|  Lancement de MUSIC DL...
echo ============================================================
echo.

REM ── Lancer l'app (python = console visible pour les logs) ────
python gui.py

REM Si l'app se ferme avec une erreur, garder la fenetre ouverte
if errorlevel 1 (
    echo.
    echo [ERREUR] L'application s'est arretee avec une erreur.
    pause
)
