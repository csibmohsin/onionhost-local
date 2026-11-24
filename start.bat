@echo off
setlocal
echo ============================================================
echo               STARTING ONIONHOST DASHBOARD
echo ============================================================
echo.
echo Launching OnionHost Control Center at http://127.0.0.1:5000 ...
start http://127.0.0.1:5000
python main.py --dashboard

