@echo off
REM === Daily archive quicklook for yesterday + git push ===

REM 0) Git: go to repo root
cd /d C:\Users\field_user\Documents\campaigns\EBT2026\skypallet-book

REM 0.1) Logging
echo [%DATE% %TIME%] Starting daily archive run >> skypallet_daily.log

REM 1) Update from remote before making any changes
git pull --rebase

REM 2) Activate conda environment
call "C:\Users\field_user\miniconda3\Scripts\activate.bat" skypallet-book

REM 3) Go to inner project directory
cd /d C:\Users\field_user\Documents\campaigns\EBT2026\skypallet-book\skypallet-book

REM 4) Compute yesterday's date as YYYY-MM-DD using PowerShell
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddDays(-1).ToString(\"yyyy-MM-dd\")"') do set YDAY=%%i

REM 5) (Optional) re-run aggregation scripts to ensure yesterday is complete
python scripts\cnr4_aggregate_daily.py
python scripts\mrr_aggregate_daily.py
python scripts\skyvue_ceilometer_aggregate_daily.py
python scripts\ship_posref_aggregate_daily.py
python scripts\ship_aws_aggregate_daily.py

REM 6) Daily archive quicklook for yesterday
REM    This produces quicklooks\archive\YYYYMMDD_skypallet_quicklook.png
python scripts\skypallet_plot_daily.py %YDAY%

REM 7) Regenerate archive.md based on quicklooks/archive/ files
python scripts\update_archive_md.py


REM 8) Git: go to repo root
cd /d C:\Users\field_user\Documents\campaigns\EBT2026\skypallet-book

REM 9) Stage yesterday's archive quicklook
REM    skypallet_plot_daily.py creates: quicklooks\archive\YYYYMMDD_skypallet_quicklook.png
REM    Repo-root path: skypallet-book\quicklooks\archive\YYYYMMDD_skypallet_quicklook.png
for /f %%j in ('powershell -NoProfile -Command "(Get-Date).AddDays(-1).ToString(\"yyyyMMdd\")"') do set YDAY_COMPACT=%%j

git add skypallet-book\quicklooks\archive\%YDAY_COMPACT%_skypallet_quicklook.png
git add skypallet-book\archive.md

REM 10) Commit (if there is a change); otherwise exit quietly
git commit -m "Add daily archive quicklook and update archive.md for %YDAY% (%DATE% %TIME%)" || goto :done

REM 11) Push
git push origin main

:done
echo [%DATE% %TIME%] Finished daily archive run >> skypallet_daily.log