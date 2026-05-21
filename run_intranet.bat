@echo off
title XiaoZhi Stock-Selection - LAN Server

:: Check for Administrator privileges to add Firewall rule
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [FIREWALL] Adding Windows Firewall rule for Port 5000...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-NetFirewallRule -DisplayName 'XiaoZhi Stock-Selection Port 5000' -ErrorAction SilentlyContinue; New-NetFirewallRule -DisplayName 'XiaoZhi Stock-Selection Port 5000' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5000 -ErrorAction SilentlyContinue" >nul
    echo [FIREWALL] Firewall rule added successfully!
) else (
    echo [TIP] If other devices cannot connect, close this window,
    echo       right-click this .bat file and choose "Run as administrator"
    echo       to automatically configure Windows Firewall.
)
echo.
echo ==========================================================
echo   XiaoZhi Stock-Selection
echo   Intranet / LAN Web Server Startup Script
echo ==========================================================
echo.
echo [1/3] Retrieving your local network IP addresses...
echo ----------------------------------------------------------
echo Open one of these URLs on other devices in the same Wi-Fi:
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { Write-Host ('  => http://' + $_.IPAddress + ':5000') -ForegroundColor Green }"
echo ----------------------------------------------------------
echo.
echo [2/3] Ensure other devices are connected to the SAME Wi-Fi.
echo.
echo [3/3] Starting the Flask server...
echo.
python app.py
pause
