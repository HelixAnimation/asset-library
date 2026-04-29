@echo off
:: Kill any running Prism instance
wmic process where "commandline like '%%PrismCore.py%%'" delete >nul 2>&1
timeout /t 1 /nobreak >nul

:: Signal the plugin to auto-open the Asset Library window on startup
set ASSET_LIBRARY_AUTOOPEN=1

:: Launch Prism
start "" "C:\Program Files\Prism2\Python313\pythonw.exe" "C:\Program Files\Prism2\Scripts\PrismCore.py"
