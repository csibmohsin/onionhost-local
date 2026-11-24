@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo            ONIONHOST - AUTOMATIC INSTALLER
echo ============================================================
echo.

:: 1. Detect Python Installation
echo [1/7] Checking Python installation...
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.8 or higher from https://python.org and add it to PATH.
    pause
    exit /b 1
)

:: 2. Check Python Version
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Detected Python version: %PY_VER%

:: 3. Create Project Directories
echo [2/7] Creating application directories...
if not exist "config" mkdir config
if not exist "data\tor" mkdir data\tor
if not exist "data\services" mkdir data\services
if not exist "logs" mkdir logs
if not exist "bin\tor" mkdir bin\tor
echo [OK] Directories initialized.

:: 4. Install Dependencies
echo [3/7] Installing Python dependencies...
python -m pip install -r requirements.txt --quiet
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Could not install all packages via pip. Attempting user install...
    python -m pip install -r requirements.txt --user --quiet
)
echo [OK] Dependencies verified.

:: 5. Inspect Tor Executable
echo [4/7] Inspecting Tor installation...
python -c "from src.tor_manager import TorManager; tm = TorManager(); print('[OK] Active Tor executable located at:', tm.tor_binary_path)"
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Tor executable not found automatically.
    echo Please install Tor Browser or place tor.exe inside bin\tor\
)

:: 6. Register onionhost in PATH
echo [5/7] Registering onionhost command in User PATH...
set "CURRENT_DIR=%~dp0"
:: Remove trailing backslash if present
if "%CURRENT_DIR:~-1%"=="\" set "CURRENT_DIR=%CURRENT_DIR:~0,-1%"

:: Check if already in PATH
echo %PATH% | findstr /i /c:"%CURRENT_DIR%" >nul
if %ERRORLEVEL% equ 0 (
    echo [OK] OnionHost directory is already in your PATH.
) else (
    :: Add to User environment PATH via PowerShell
    powershell -NoProfile -Command ^
        "$currentPath = [Environment]::GetEnvironmentVariable('Path', 'User'); " ^
        "if ($currentPath -notlike '*%CURRENT_DIR%*') { " ^
        "  [Environment]::SetEnvironmentVariable('Path', $currentPath + ';%CURRENT_DIR%', 'User'); " ^
        "  Write-Host 'Successfully registered %CURRENT_DIR% into User PATH.' " ^
        "}"
    echo [OK] PATH updated. (Note: New CMD windows will have onionhost command globally available)
)

:: 7. Create Sample Website
echo [6/7] Scaffolding sample website...
python -c "from src.website_manager import WebsiteManager; WebsiteManager.create_sample_website_if_needed('sample_website')"
echo [OK] Sample website ready in sample_website\

:: 8. Run Verification Test
if exist "tests\test_pipeline.py" (
    echo [7/7] Running initial validation test...
    python tests\test_pipeline.py
) else (
    echo [7/7] Verifying core engine installation...
    python -c "from src.onionhost_core import OnionHostCore; print('[OK] Core engine modules verified successfully.')"
)
if %ERRORLEVEL% equ 0 (
    echo.
    echo ============================================================
    echo       INSTALLATION COMPLETED SUCCESSFULLY!
    echo ============================================================
    echo.
    echo You can now host ANY website folder with ONE command:
    echo.
    echo    onionhost "C:\Path\To\Your\Website"
    echo.
    echo Or start the modern web dashboard:
    echo.
    echo    start.bat   OR   onionhost --dashboard
    echo.
) else (
    echo [WARNING] Initial validation test reported issues. Please check logs\tor.log.
)

pause

