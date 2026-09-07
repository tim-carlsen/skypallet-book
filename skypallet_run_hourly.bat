@echo off
REM === Hourly aggregation + latest quicklook + git push ===


REM 0) Git: go to repo root
cd /d C:\Users\field_user\Documents\campaigns\EBT2026\skypallet-book

REM 0.1) Logging
echo [%DATE% %TIME%] Starting hourly run >> skypallet_hourly.log

echo [%DATE% %TIME%] Running as user: %USERNAME% >> skypallet_hourly.log
echo [%DATE% %TIME%] Current directory: %CD% >> skypallet_hourly.log

REM 1) Update from remote before making any changes
echo [%DATE% %TIME%] Before REM1 >> skypallet_hourly.log
git pull --rebase
echo [%DATE% %TIME%] After REM1 >> skypallet_hourly.log


REM 2) Activate conda environment
echo [%DATE% %TIME%] Before REM2 >> skypallet_hourly.log
call "C:\Users\field_user\miniconda3\Scripts\activate.bat" skypallet-book
echo [%DATE% %TIME%] After REM2 >> skypallet_hourly.log


REM 3) Go to inner project directory
echo [%DATE% %TIME%] Before REM3 >> skypallet_hourly.log
cd /d C:\Users\field_user\Documents\campaigns\EBT2026\skypallet-book\skypallet-book
echo [%DATE% %TIME%] After REM3 >> skypallet_hourly.log

REM 4) Aggregation scripts
echo [%DATE% %TIME%] Before REM4 >> skypallet_hourly.log
python scripts\cnr4_aggregate_daily.py
python scripts\mrr_aggregate_daily.py
python scripts\skyvue_ceilometer_aggregate_daily.py
python scripts\ship_posref_aggregate_daily.py
python scripts\ship_aws_aggregate_daily.py
echo [%DATE% %TIME%] After REM4 >> skypallet_hourly.log

REM 5) Latest quicklook (skypallet_quicklook_latest.png)
echo [%DATE% %TIME%] Before REM5 >> skypallet_hourly.log
python scripts\skypallet_make_latest_quicklook.py
echo [%DATE% %TIME%] After REM5 >> skypallet_hourly.log

REM 6) Heartbeat: write timestamp file (visible on Live data page)
echo [%DATE% %TIME%] Before REM6 >> skypallet_hourly.log

for /f %%d in ('powershell -NoProfile -Command "(Get-Date).ToString(\"dd/MM/yyyy\")"') do set SHIPDATE_DMY=%%d
for /f %%t in ('powershell -NoProfile -Command "(Get-Date).ToString(\"HH:mm\")"') do set SHIPTIME=%%t
echo Last successful update from ship: %SHIPDATE_DMY% %SHIPTIME% > quicklooks/heartbeat.txt
echo [%DATE% %TIME%] After REM6 >> skypallet_hourly.log

REM 7) Git: go back to repo root
echo [%DATE% %TIME%] Before go back to repo root >> skypallet_hourly.log
cd /d C:\Users\field_user\Documents\campaigns\EBT2026\skypallet-
echo [%DATE% %TIME%] After go back to repo root >> skypallet_hourly.log


REM 8) Stage latest quicklook
REM    File lives at skypallet-book\quicklooks\skypallet_quicklook_latest.png relative to repo root
echo [%DATE% %TIME%] Before git status >> skypallet_hourly.log

git status >> skypallet_hourly.log 2>&1
echo [%DATE% %TIME%] After git status >> skypallet_hourly.log


echo [%DATE% %TIME%] Before staging quicklook etc. git add >> skypallet_hourly.log

git add skypallet-book\quicklooks\skypallet_quicklook_latest.png
git add skypallet-book\quicklooks.md
git add skypallet-book\quicklooks\heartbeat.txt
echo [%DATE% %TIME%] After staging >> skypallet_hourly.log


REM 9) Commit (if there is a change); otherwise exit quietly
echo [%DATE% %TIME%] Before git commit >> skypallet_hourly.log
git commit -m "Update latest quicklook, quicklooks.md, and heartbeat %SHIPDATE_DMY% %SHIPTIME%" >> skypallet_hourly.log 2>&1
echo [%DATE% %TIME%] After git commit >> skypallet_hourly.log

REM 10) Push
echo [%DATE% %TIME%] Before git push >> skypallet_hourly.log
git push origin main
echo [%DATE% %TIME%] After git push >> skypallet_hourly.log


:done
echo [%DATE% %TIME%] Finished hourly run >> skypallet_hourly.log