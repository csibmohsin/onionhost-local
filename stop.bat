@echo off
setlocal
echo ============================================================
echo               STOPPING ONIONHOST SERVICES
echo ============================================================
echo.
python onionhost.py --stop
echo.
pause

