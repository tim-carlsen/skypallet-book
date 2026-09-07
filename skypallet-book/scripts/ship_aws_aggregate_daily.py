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
ship_aws_aggregate_daily.py

Read raw vessel-mounted AWS text files, process them, and combine
into daily NetCDF files with metadata.

Directory structure assumed:
  NAS_ROOT/CAMPAIGN/ship/Vaisala_AWS/*.txt (or .dat)

Output:
  NAS_ROOT/CAMPAIGN/ship/Vaisala_AWS/processed/YYYYMMDD_aws_daily.nc
"""

# %%
import os
import glob
import datetime as dt
import re
from pathlib import Path

# %%
import numpy as np
import pandas as pd
import xarray as xr

# %%
from skypallet_config import load_config


# %% [markdown]
# --------------------------------------------------------------------
# 1. Load configuration
# --------------------------------------------------------------------

# %%
HERE = os.path.dirname(__file__)
cfg_path = os.path.join(HERE, "skypallet_config.yml")
cfg = load_config(cfg_path)

# %%
CAMPAIGN = cfg["campaign"]
NAS_ROOT = cfg["paths"]["nas_root"]

# %%
AWS_ROOT      = os.path.join(NAS_ROOT, CAMPAIGN, "ship/Vaisala_AWS")
PROCESSED_DIR = os.path.join(AWS_ROOT, "processed")

# %%
ENGINE_WRITE = cfg["general"]["engine_write"]
DAYS_BACK    = cfg["general"]["days_back"]

# %%
Path(PROCESSED_DIR).mkdir(parents=True, exist_ok=True)


# %%
# --------------------------------------------------------------------
# 2. Helpers: find raw files, group by day
# --------------------------------------------------------------------
def find_all_aws_raw_files():
    """
    Find all raw AWS files under AWS_ROOT with pattern:
    *.txt / *.dat (no subdirectories).
    """
    file_pattern_txt = os.path.join(AWS_ROOT, "*.txt")
    file_pattern_dat = os.path.join(AWS_ROOT, "*.dat")

    all_files = sorted(glob.glob(file_pattern_txt) + glob.glob(file_pattern_dat))
    return all_files


# %%
def extract_date_from_filename(path):
    """
    Extract date (YYYYMMDD) from filename like:
    AWS430__SMSAWS__20260828.txt
    """
    base = os.path.basename(path)
    m = re.search(r"(\d{8})", base)
    if not m:
        raise ValueError(f"Could not find YYYYMMDD in filename: {base}")
    date_str = m.group(1)
    return dt.datetime.strptime(date_str, "%Y%m%d").date()


# %%
def group_files_by_day(file_list):
    by_day = {}
    for f in file_list:
        try:
            d = extract_date_from_filename(f)
        except Exception:
            continue
        by_day.setdefault(d, []).append(f)
    return by_day


# %%
# --------------------------------------------------------------------
# 3. Read + process a single raw AWS file
# --------------------------------------------------------------------
def read_single_raw_file(path):
    """
    Read one raw AWS text file and return it as an xarray.Dataset.

    Format (tab-separated, with header):

    TIME   CH   CL   CM   CSW   DPAVG1M  EXTDC  HEADING  ...
    2026-09-03 00:00:10   ///  ///  ///  ///  -4.6  24.1  127  ...
    """

    df = pd.read_csv(
        path,
        sep="\t",
        header=0,  # first line is header with column names
        na_values=["///", "NAN", "NaN", "nan", "INF", "-INF", "---"],
        engine="python",
    )

    if "TIME" not in df.columns:
        raise ValueError(f"No TIME column found in {path} columns: {df.columns}")

    # Parse TIME to datetime and set index
    df["TIME"] = pd.to_datetime(df["TIME"])
    df = df.set_index("TIME").sort_index()
    df.index.name = "time"

    # Convert numeric-like columns to numeric where possible
    df = df.apply(pd.to_numeric, errors="ignore")

    # Keep ALL columns (no subsetting)
    ds = xr.Dataset.from_dataframe(df)
    return ds


# %%
# --------------------------------------------------------------------
# 4. Try reading each file (filter unreadable)
# --------------------------------------------------------------------
def filter_readable_files(files):
    good_ds_list = []
    bad_files = []
    for path in files:
        try:
            ds = read_single_raw_file(path)
            if "time" not in ds.coords:
                raise ValueError("No 'time' coordinate in dataset")
            good_ds_list.append(ds)
        except Exception as e:
            print(f"[WARN] Skipping unreadable AWS raw file: {path}")
            print(f"       Error: {repr(e)}")
            bad_files.append(path)
    return good_ds_list, bad_files


# %%
# --------------------------------------------------------------------
# 5. Combine one day's datasets into a single Dataset
# --------------------------------------------------------------------
def combine_day(ds_list_for_day):
    """
    Combine AWS Datasets for one day into a single xarray.Dataset,
    keeping all variables.
    """
    if not ds_list_for_day:
        raise RuntimeError("No readable datasets provided for this day.")

    ds_day = xr.concat(ds_list_for_day, dim="time")
    ds_day = ds_day.sortby("time")

    # No subsetting: keep all data_vars from the raw files
    return ds_day


# %%
# --------------------------------------------------------------------
# 6. Add extra metadata
# --------------------------------------------------------------------
def add_daily_metadata(ds_day, date_obj):
    creation_time = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str      = date_obj.strftime("%Y-%m-%d")

    if "time" in ds_day.coords and ds_day.time.size > 0:
        ds_day.attrs["time_coverage_start"] = str(ds_day.time.values[0])
        ds_day.attrs["time_coverage_end"]   = str(ds_day.time.values[-1])

    ds_day.attrs["title"] = (
        "Daily vessel-mounted AWS file from SkyPallet onboard RV Kronprins Haakon "
        f"during cruise {CAMPAIGN}"
    )
    ds_day.attrs["institution"] = "Department of Geoscience, University of Oslo, Norway"
    ds_day.attrs["principal_investigator"] = (
        "Paul Dodd (Norwegian Polar Institute, Tromsø, Norway)"
    )
    ds_day.attrs["file_creator"] = "Tim Carlsen (University of Oslo)"
    ds_day.attrs["data_contact"] = "Tim Carlsen (tim.carlsen@geo.uio.no)"
    ds_day.attrs["data_contact2"] = "Robert O. David (r.o.david@geo.uio.no)"
    ds_day.attrs["instrument"] = "Vessel-mounted Automatic Weather Station (AWS)"
    ds_day.attrs["campaign"] = CAMPAIGN
    ds_day.attrs["date_created"] = creation_time
    ds_day.attrs["date_coverage"] = date_str
    ds_day.attrs["history"] = (
        f"Created from raw AWS text files on {creation_time} UTC "
        f"using ship_aws_aggregate_daily.py"
    )
    ds_day.attrs["license"] = "CC BY-SA 4.0"
    ds_day.attrs["Conventions"] = "CF-1.13"

    return ds_day


# %%
# --------------------------------------------------------------------
# 7. Daily file path and reprocessing check
# --------------------------------------------------------------------
def daily_file_path(date_obj):
    date_tag = date_obj.strftime("%Y%m%d")
    return os.path.join(PROCESSED_DIR, f"{date_tag}_aws_daily.nc")


# %%
def should_reprocess_day(date_obj, raw_files):
    out_path = daily_file_path(date_obj)

    if not os.path.exists(out_path):
        print(f"[INFO] No daily AWS file yet for {date_obj}, will create it.")
        return True

    daily_mtime = os.path.getmtime(out_path)
    raw_mtimes = [os.path.getmtime(f) for f in raw_files]
    max_raw_mtime = max(raw_mtimes) if raw_mtimes else 0.0

    if max_raw_mtime > daily_mtime:
        print(f"[INFO] New AWS raw files detected for {date_obj}, will reprocess.")
        return True
    else:
        print(f"[INFO] Daily AWS file for {date_obj} is up-to-date, skipping.")
        return False


# %%
# --------------------------------------------------------------------
# 8. Write daily NetCDF file
# --------------------------------------------------------------------
def write_daily_file(ds_day, date_obj):
    out_path = daily_file_path(date_obj)
    print(f"[INFO] Writing daily AWS file: {out_path}")
    ds_day.to_netcdf(
        out_path,
        engine=ENGINE_WRITE,
        format="NETCDF4",
    )


# %%
# --------------------------------------------------------------------
# 9. Main program
# --------------------------------------------------------------------
def main():
    all_files = find_all_aws_raw_files()
    print(f"[INFO] Found {len(all_files)} raw AWS files.")

    if not all_files:
        print("[ERROR] No raw AWS files found. Check NAS_ROOT and directory structure.")
        return

    grouped = group_files_by_day(all_files)
    all_days = sorted(grouped.keys())
    print(f"[INFO] Found AWS data for {len(all_days)} unique days.")

    today = dt.date.today()
    earliest_day_to_consider = today - dt.timedelta(days=DAYS_BACK)

    days_to_process = [d for d in all_days if d >= earliest_day_to_consider]
    print(
        f"[INFO] Will consider {len(days_to_process)} day(s) from "
        f"{earliest_day_to_consider} to {today}."
    )

    for day in days_to_process:
        day_files = grouped[day]
        print(f"\n[INFO] Candidate day {day} with {len(day_files)} raw AWS files.")

        ds_list, bad_files = filter_readable_files(day_files)
        print(
            f"[INFO] Day {day}: {len(ds_list)} readable AWS datasets, "
            f"{len(bad_files)} unreadable."
        )

        if not ds_list:
            print(f"[WARN] No readable AWS datasets for {day}, skipping.")
            continue

        if not should_reprocess_day(day, day_files):
            continue

        ds_day = combine_day(ds_list)
        ds_day = add_daily_metadata(ds_day, day)
        write_daily_file(ds_day, day)
        ds_day.close()

    print("\n[INFO] ship_aws_aggregate_daily done.")


# %%
if __name__ == "__main__":
    main()
