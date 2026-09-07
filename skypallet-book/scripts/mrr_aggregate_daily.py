# -*- coding: utf-8 -*-
# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -all
#     custom_cell_magics: kql
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.11.2
#   kernelspec:
#     display_name: skypallet-book
#     language: python
#     name: python3
# ---

# %%
"""
mrr_daily_aggregate.py

Combine hourly MRR netcdf files into daily netcdf files adding some metadata

"""
import numpy as np
# Workaround for depecated Numpy aliases used by some libraries (e.g. xarray/dask)
if not hasattr(np, "float"):
    np.float = float
if not hasattr(np, "int"):
    np.int = int
if not hasattr(np, "bool"):
    np.bool = bool

import os
import glob
import datetime as dt
import xarray as xr
import matplotlib.pyplot as plt
from pathlib import Path
from skypallet_config import load_config


# %%

# --------------------------------------------------------------------
# 1. Load configuration
# --------------------------------------------------------------------
HERE = os.path.dirname(__file__)
cfg_path = os.path.join(HERE, "skypallet_config.yml")
cfg = load_config(cfg_path)

CAMPAIGN = cfg["campaign"]
NAS_ROOT = cfg["paths"]["nas_root"]

# Build instrument-specific roots here
MRR_ROOT      = os.path.join(NAS_ROOT, CAMPAIGN, "mrr")
PROCESSED_DIR  = os.path.join(MRR_ROOT, "processed")

ENGINE_WRITE = cfg["general"]["engine_write"]
ENGINE_READ = cfg["general"]["engine_read"]

DAYS_BACK    = cfg["general"]["days_back"]

Path(PROCESSED_DIR).mkdir(parents=True, exist_ok=True)


# Variables and coordinates to keep
VARS_TO_KEEP   = ["Za", "Z", "Zea", "Ze", "RR", "LWC", "PIA", "VEL", "WIDTH", "ML", "SNR", "index_spectra", "spectrum_raw", "N", "D", "transfer_function", "calibration_constant", "doppler_shift_spectrum", "elevation", "azimuth"]      # adjust to your variable names
COORDS_TO_KEEP = ["time", "range"]        # plus any others you need



# --------------------------------------------------------------------
# 2. Find all hourly files
# --------------------------------------------------------------------
def find_all_mrr_files():
    """
    Find all hourly MRR files under MRR_ROOT with pattern:
    YYYYMM/YYYYMMDD/*.nc
    """
    file_pattern = os.path.join(MRR_ROOT, "[0-9]" * 6, "[0-9]" * 8, "*.nc")
    all_files = sorted(glob.glob(file_pattern))
    return all_files


# --------------------------------------------------------------------
# 3. Group files by date
# --------------------------------------------------------------------
def extract_date_from_filename(path):
    """
    Extract date (YYYYMMDD) from filename like:
    .../YYYYMM/YYYYMMDD/YYYYMMDD_hhmmss.nc
    Returns a datetime.date.
    """
    base = os.path.basename(path)
    # Expect something like '20260727_151524.nc'
    date_str = base.split("_")[0]  # '20260727'
    return dt.datetime.strptime(date_str, "%Y%m%d").date()


def group_files_by_day(file_list):
    """
    Group files by date (datetime.date).
    Returns: dict[date] = list of files for that day.
    """
    by_day = {}
    for f in file_list:
        try:
            d = extract_date_from_filename(f)
        except Exception:
            # Skip files with unexpected naming
            continue
        by_day.setdefault(d, []).append(f)
    return by_day


# --------------------------------------------------------------------
# 4. Open files (skip unreadable files)
# --------------------------------------------------------------------
def filter_readable_files(files):
    """
    Try opening each file with xarray; keep only those that can be read.
    """
    good = []
    bad = []
    for path in files:
        try:
            ds_tmp = xr.open_dataset(path, engine=ENGINE_READ)
            ds_tmp.close()
            good.append(path)
        except Exception as e:
            print(f"[WARN] Skipping unreadable file: {path}")
            print(f"       Error: {repr(e)}")
            bad.append(path)
    return good, bad


# --------------------------------------------------------------------
# 5. Combine hourly files into a daily dataset
# --------------------------------------------------------------------
def combine_day(files_for_day):
    """
    Combine hourly files for one day into a single xarray.Dataset.
    """
    if not files_for_day:
        raise RuntimeError("No readable files provided for this day.")

    # Use open_mfdataset with combine by coords
    ds_day = xr.open_mfdataset(
        files_for_day,
        engine=ENGINE_READ,
        combine="by_coords",
        parallel=True,
        data_vars="all",
        coords="all",
        compat="override",
    )
    
    # Determine which requested vars/coords actually exist
    keep_vars   = [v for v in VARS_TO_KEEP   if v in ds_day]
    keep_coords = [c for c in COORDS_TO_KEEP if c in ds_day.coords]

    # Subset dataset (coords are included automatically with vars,
    # but we can explicitly add them to be safe)
    ds_day = ds_day[keep_vars + keep_coords]

    return ds_day


# --------------------------------------------------------------------
# 6. Add extra metadata
# --------------------------------------------------------------------
 
    date_created= datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
    time_coverage_start= str(ds_day.time.values[0]),
    time_coverage_end= str(ds_day.time.values[-1]),
    history= "Aggregated from hourly TOA5 .dat files; processed with Python/xarray.",
    
def add_daily_metadata(ds_day, date_obj):
    """
    Add global attributes and variable attributes for the daily file.
    """
    creation_time = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str      = date_obj.strftime("%Y-%m-%d")

    # Global attributes
    ds_day.attrs["title"] = "Daily MRR radar file from SkyPallet onboard RV Kronprins Haakon during cruise "+CAMPAIGN
    ds_day.attrs["institution"] = "Department of Geoscience, University of Oslo, Norway"
    ds_day.attrs["principal_investigator"] = "Tim Carlsen, Robert O. David, Trude Storelvmo (University of Oslo, Norway)"
    ds_day.attrs["file_creator"] = "Tim Carlsen (University of Oslo)"
    ds_day.attrs["data_contact"] = "Tim Carlsen (tim.carlsen@geo.uio.no)"
    ds_day.attrs["data_contact2"] = "Robert O. David (r.o.david@geo.uio.no)",    
    ds_day.attrs["instrument"] = "Micro Rain Radar (MRR)"
    ds_day.attrs["campaign"] = CAMPAIGN
    ds_day.attrs["date_created"] = creation_time
    ds_day.attrs["date_coverage"] = date_str
    ds_day.attrs["history"] = (
        f"Created from hourly MRR files on {creation_time} UTC "
        f"using mrr_daily_aggregate.py"
    )
    ds_day.attrs["license"] = "CC BY-SA 4.0"
    ds_day.attrs["Conventions"] = "CF-1.13"
    ds_day.attrs["Acknowledgement"] = "The operation of the Skypallet was made possible thanks to the support of Polhavet 2050, the European Research Council through ERC Consolidator Grant “STEP-CHANGE” (grant number 101045273), and the University of Oslo’s Cold Climate Container Facilities."

    return ds_day

# --------------------------------------------------------------------
# 7. Daily file path and reprocessing check
# --------------------------------------------------------------------
def daily_file_path(date_obj):
    """
    Path to the daily NetCDF file for the given date.
    """
    date_tag = date_obj.strftime("%Y%m%d")
    return os.path.join(PROCESSED_DIR, f"{date_tag}_mrr_daily.nc")


def should_reprocess_day(date_obj, hourly_files):
    """
    Decide whether to (re)process the given day based on modification times.

    Logic:
        - If no daily file exists -> return True.
        - If daily file exists:
            * Get its mtime.
            * Get max mtime over hourly_files.
            * If any hourly file is newer than daily file -> True.
            * Else -> False.
    """
    out_path = daily_file_path(date_obj)

    if not os.path.exists(out_path):
        print(f"[INFO] No daily file yet for {date_obj}, will create it.")
        return True

    daily_mtime = os.path.getmtime(out_path)
    hourly_mtimes = [os.path.getmtime(f) for f in hourly_files]
    max_hourly_mtime = max(hourly_mtimes) if hourly_mtimes else 0.0

    if max_hourly_mtime > daily_mtime:
        print(f"[INFO] New hourly files detected for {date_obj}, will reprocess.")
        return True
    else:
        print(f"[INFO] Daily file for {date_obj} is up-to-date, skipping.")
        return False


# --------------------------------------------------------------------
# 8. Write daily NetCDF file
# --------------------------------------------------------------------    
def write_daily_file(ds_day, date_obj):
    """
    Write daily dataset to NetCDF in PROCESSED_DIR.
    """
    out_path = daily_file_path(date_obj)
    print(f"[INFO] Writing daily file: {out_path}")
    ds_day.to_netcdf(
        out_path,
        engine=ENGINE_WRITE,
        format="NETCDF4",
    )



# --------------------------------------------------------------------
# 9. Main program
# --------------------------------------------------------------------
def main():
    # Find all hourly files
    all_files = find_all_mrr_files()
    print(f"[INFO] Found {len(all_files)} hourly MRR files.")

    if not all_files:
        print("[ERROR] No MRR files found. Check NAS_ROOT and directory structure.")
        return

    # Group by day
    grouped = group_files_by_day(all_files)
    all_days = sorted(grouped.keys())
    print(f"[INFO] Found data for {len(all_days)} unique days.")

    # Determine which days to consider (recent days only)
    today = dt.date.today()
    earliest_day_to_consider = today - dt.timedelta(days=DAYS_BACK)

    days_to_process = [d for d in all_days if d >= earliest_day_to_consider]
    print(f"[INFO] Will consider {len(days_to_process)} day(s) from "
          f"{earliest_day_to_consider} to {today}.")

    for day in days_to_process:
        day_files = grouped[day]
        print(f"\n[INFO] Candidate day {day} with {len(day_files)} hourly files.")

        # Filter unreadable files
        good_files, bad_files = filter_readable_files(day_files)
        print(f"[INFO] Day {day}: {len(good_files)} readable files, {len(bad_files)} unreadable.")

        if not good_files:
            print(f"[WARN] No readable files for {day}, skipping.")
            continue

        # Check if we need to (re)process this day
        if not should_reprocess_day(day, good_files):
            continue

        # Combine into a daily dataset
        ds_day = combine_day(good_files)

        # Add metadata
        ds_day = add_daily_metadata(ds_day, day)

        # Write to disk
        write_daily_file(ds_day, day)

        # Close dataset
        ds_day.close()

    print("\n[INFO] Done.")


if __name__ == "__main__":
    main()
