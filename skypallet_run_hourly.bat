@echo off
REM === Hourly aggregation + latest quicklook + git push ===


REM 0) Git: go to repo root
cd /d C:\Users\field_user\Documents\campaigns\EBT2026\skypallet-book

REM 0.1) Logging
echo [%DATE% %TIME%] Starting hourly run >> skypallet_hourly.log

REM 1) Update from remote before making any changes
git pull --rebase

REM 2) Activate conda environment
call "C:\Users\field_user\miniconda3\Scripts\activate.bat" skypallet-book

REM 3) Go to inner project directory
cd /d C:\Users\field_user\Documents\campaigns\EBT2026\skypallet-book\skypallet-book

REM 4) Aggregation scripts
python scripts\cnr4_aggregate_daily.py
python scripts\mrr_aggregate_daily.py
python scripts\skyvue_ceilometer_aggregate_daily.py
python scripts\ship_posref_aggregate_daily.py
python scripts\ship_aws_aggregate_daily.py

REM 5) Latest quicklook (skypallet_quicklook_latest.png)
python scripts\skypallet_make_latest_quicklook.py

REM 6) Git: go back to repo root
cd /d C:\Users\field_user\Documents\campaigns\EBT2026\skypallet-book

REM 7) Stage latest quicklook
REM    File lives at skypallet-book\quicklooks\skypallet_quicklook_latest.png relative to repo root
git add skypallet-book\quicklooks\skypallet_quicklook_latest.png

REM 8) Commit (if there is a change); otherwise exit quietly
git commit -m "Update latest quicklook %DATE% %TIME%" || goto :eof

REM 9) Push
git push origin main

:done
echo [%DATE% %TIME%] Finished hourly run >> skypallet_hourly.log