@echo off
echo === Building SCF deployment package ===
pip install requests urllib3 -t package --quiet
copy check.py package\check.py
copy accounts.json package\accounts.json
copy scf_handler.py package\scf_handler.py
cd package
powershell Compress-Archive -Path * -DestinationPath ..\scf_deploy.zip -Force
cd ..
echo === Done: scf_deploy.zip created ===
echo.
echo Upload this zip to Tencent Cloud SCF console:
echo https://console.cloud.tencent.com/scf/list
echo.
echo Configuration:
echo   Runtime: Python 3.9
echo   Handler: scf_handler.main_handler
echo   Trigger: Timer - cron(0 10 9 * * 1-5 *)
echo   Timeout: 60s
echo   Memory: 128MB
pause
