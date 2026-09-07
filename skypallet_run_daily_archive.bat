@echo off
REM === Daily archive quicklook for yesterday + git push ===

REM 1) Activate conda environment
call "C:\Users\field_user\miniconda3\Scripts\activate.bat" skypallet-book

REM 2) Go to inner project directory
cd /d C:\Users\field_user\Documents\campaigns\EBT2026\skypallet-book\skypallet-book

REM 3) Compute yesterday's date as YYYY-MM-DD using PowerShell
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddDays(-1).ToString(\"yyyy-MM-dd\")"') do set YDAY=%%i

REM 4) (Optional) re-run aggregation scripts to ensure yesterday is complete
python scripts\cnr4_aggregate_daily.py
python scripts\mrr_aggregate_daily.py
python scripts\skyvue_ceilometer_aggregate_daily.py
python scripts\ship_posref_aggregate_daily.py
python scripts\ship_aws_aggregate_daily.py

REM 5) Daily archive quicklook for yesterday
REM    This produces quicklooks\archive\YYYYMMDD_skypallet_quicklook.png
python scripts\skypallet_plot_daily.py %YDAY%

REM 6) Git: go to repo root
cd /d C:\Users\field_user\Documents\campaigns\EBT2026\skypallet-book

REM 7) Update from remote
git pull --rebase

REM 8) Stage yesterday's archive quicklook
REM    skypallet_plot_daily.py creates: quicklooks\archive\YYYYMMDD_skypallet_quicklook.png
REM    Repo-root path: skypallet-book\quicklooks\archive\YYYYMMDD_skypallet_quicklook.png
for /f %%j in ('powershell -NoProfile -Command "(Get-Date).AddDays(-1).ToString(\"yyyyMMdd\")"') do set YDAY_COMPACT=%%j

git add skypallet-book\quicklooks\archive\%YDAY_COMPACT%_skypallet_quicklook.png

REM 9) Commit (if there is a change); otherwise exit quietly
git commit -m "Add daily archive quicklook for %YDAY% (%DATE% %TIME%)" || goto :eof

REM 10) Push
git push origin main
