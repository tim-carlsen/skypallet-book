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
ship_posref_aggregate_daily.py

Read raw ship PosRef CSV files and create daily NetCDF files with position
and basic meteorological / navigation parameters.

Directory layout assumed (adjust if needed):

    NAS_ROOT/CAMPAIGN/ship/PosRef/*.csv   (posDD-MM-YYYY.csv)

The script:
    - Uses skypallet_config.yml for paths and engines.
    - Processes only recent days, controlled by DAYS_BACK.
    - Writes daily NetCDF files under:
        NAS_ROOT/CAMPAIGN/ship/PosRef/processed/
"""

# %%
import os
import glob
import re
import datetime as dt
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
cfg_path = os.path.join(HERE, "skypallet_config_mac.yml")
cfg = load_config(cfg_path)

# %%
CAMPAIGN = cfg["campaign"]
NAS_ROOT = cfg["paths"]["nas_root"]

# %%
# Root for ship position reference data
SHIP_ROOT      = os.path.join(NAS_ROOT, CAMPAIGN, "ship", "PosRef")
PROCESSED_DIR  = os.path.join(SHIP_ROOT, "processed")

# %%
ENGINE_WRITE = cfg["general"]["engine_write"]
ENGINE_READ  = cfg["general"]["engine_read"]  # not really needed here, but kept for symmetry
DAYS_BACK    = cfg["general"]["days_back"]

# %%
Path(PROCESSED_DIR).mkdir(parents=True, exist_ok=True)


# %%
# --------------------------------------------------------------------
# 2. Utilities
# --------------------------------------------------------------------
def date_from_filename(path):
    """
    Extract date from filename of the form:
        posDD-MM-YYYY.csv

    Returns: datetime.date
    """
    base = os.path.basename(path)
    m = re.search(r"pos(\d{2})-(\d{2})-(\d{4})\.csv", base)
    if not m:
        raise ValueError(f"Cannot extract date from filename: {base}")
    day, month, year = map(int, m.groups())
    return dt.date(year, month, day)


# %%
def degmin_to_decimal(coord_str):
    """
    Convert a 'DDDMM.mmm H' or 'DDMM.mmm H' style coordinate string
    to decimal degrees. Example:
        '7802.345 N' -> 78 + 2.345/60.
    """
    if isinstance(coord_str, (float, int)):
        # in case value already numeric with hemisphere separate, adapt if needed
        coord_str = str(coord_str)

    parts = str(coord_str).strip().split()
    if len(parts) != 2:
        raise ValueError(f"Unexpected coordinate format: {coord_str}")

    value_str, hemi = parts
    value = float(value_str)
    degrees = int(value // 100)
    minutes = value - 100 * degrees
    decimal = degrees + minutes / 60.0

    if hemi.upper() in ["S", "W"]:
        decimal = -decimal
    return decimal


# %%
def find_all_posref_files():
    """
    Find all raw PosRef CSV files under SHIP_ROOT with pattern:
        pos*.csv
    """
    pattern = os.path.join(SHIP_ROOT, "pos*.csv")
    return sorted(glob.glob(pattern))


# %%
def group_files_by_day(file_list):
    """
    Group PosRef CSV files by date (datetime.date) using date_from_filename.
    Returns: dict[date] = list(files_for_that_date)
    """
    by_day = {}
    for f in file_list:
        try:
            d = date_from_filename(f)
        except Exception:
            # Skip files with unexpected naming
            continue
        by_day.setdefault(d, []).append(f)
    return by_day


# %%
# --------------------------------------------------------------------
# 3. Read and parse a single PosRef CSV file
# --------------------------------------------------------------------
def read_posref_file(path):
    """
    Read a single PosRef CSV file and return a pandas.DataFrame with:

    Columns (standardized):
        datetime, lat, lon, depth, heading, speed,
        water_temp, wind_speed, wind_dir, air_temp, air_pressure, rh
    """
    file_date = date_from_filename(path)

    # Try a common non-UTF8 encoding; adjust if needed
    try:
        raw = pd.read_csv(path, skiprows=2, encoding="latin1")
    except UnicodeDecodeError:
        raw = pd.read_csv(path, skiprows=2, encoding="latin1", encoding_errors="replace")

    # Ensure expected columns are present; raise helpful error if not
    expected_cols = [
        "Time", "Latitude", "Longitude",
        "Depth", "Heading", "Speed", "Water temp",
        "Wind", "Wind dir", "Air temp",
        "Air pressure", "Humidity",
    ]
    missing = [c for c in expected_cols if c not in raw.columns]
    if missing:
        raise KeyError(f"Missing expected columns in {path}: {missing}")

    df = raw[expected_cols].copy()

    # Build datetime (date from filename, time from 'Time' column)
    df["datetime"] = pd.to_datetime(
        file_date.strftime("%Y-%m-%d") + " " + df["Time"].astype(str),
        format="%Y-%m-%d %H:%M:%S",
        errors="coerce",
    )

    # Convert coordinates
    df["lat"] = df["Latitude"].apply(degmin_to_decimal)
    df["lon"] = df["Longitude"].apply(degmin_to_decimal)

    # Simple renaming / copying of other variables (adjust units as needed)
    df["depth"]        = df["Depth"]
    df["heading"]      = df["Heading"]
    df["speed"]        = df["Speed"]
    df["water_temp"]   = df["Water temp"]
    df["wind_speed"]   = df["Wind"]
    df["wind_dir"]     = df["Wind dir"]
    df["air_temp"]     = df["Air temp"]
    df["air_pressure"] = df["Air pressure"]
    df["rh"]           = df["Humidity"]

    # Keep only standardized columns
    df = df[[
        "datetime", "lat", "lon", "depth", "heading", "speed",
        "water_temp", "wind_speed", "wind_dir",
        "air_temp", "air_pressure", "rh",
    ]]

    # Drop rows with missing datetime
    df = df.dropna(subset=["datetime"])

    return df


# %%
# --------------------------------------------------------------------
# 4. Combine files for a day into an xarray.Dataset
# --------------------------------------------------------------------
def combine_day_posref(files_for_day):
    """
    Combine all PosRef CSV files for one day into a single Dataset.
    """
    if not files_for_day:
        raise RuntimeError("No files provided for this day.")

    dfs = []
    for f in files_for_day:
        try:
            df = read_posref_file(f)
            dfs.append(df)
        except Exception as e:
            print(f"[WARN] Skipping file {f} due to error: {e}")

    if not dfs:
        raise RuntimeError("No valid data frames for this day.")

    track_df = pd.concat(dfs, ignore_index=True).sort_values("datetime")

    # Build xarray Dataset
    ds_day = xr.Dataset(
        data_vars={
            "lat":         ("time", track_df["lat"].values),
            "lon":         ("time", track_df["lon"].values),
            "depth":       ("time", track_df["depth"].values),
            "heading":     ("time", track_df["heading"].values),
            "speed":       ("time", track_df["speed"].values),
            "water_temp":  ("time", track_df["water_temp"].values),
            "wind_speed":  ("time", track_df["wind_speed"].values),
            "wind_dir":    ("time", track_df["wind_dir"].values),
            "air_temp":    ("time", track_df["air_temp"].values),
            "air_pressure":("time", track_df["air_pressure"].values),
            "rh":          ("time", track_df["rh"].values),
        },
        coords={
            "time": track_df["datetime"].values,
        },
    )

    # Basic attributes (adjust units if you know them precisely)
    ds_day["lat"].attrs = {"units": "degrees_north", "long_name": "latitude"}
    ds_day["lon"].attrs = {"units": "degrees_east", "long_name": "longitude"}
    ds_day["depth"].attrs = {"units": "m", "long_name": "water depth"}
    ds_day["heading"].attrs = {"units": "deg", "long_name": "ship heading"}
    ds_day["speed"].attrs = {"units": "knots", "long_name": "ship speed"}
    ds_day["water_temp"].attrs = {"units": "degC", "long_name": "water temperature"}
    ds_day["air_temp"].attrs = {"units": "degC", "long_name": "air temperature"}
    ds_day["wind_speed"].attrs = {"units": "m/s", "long_name": "wind speed"}
    ds_day["wind_dir"].attrs = {"units": "deg", "long_name": "wind direction (meteorological)"}
    ds_day["air_pressure"].attrs = {"units": "hPa", "long_name": "air pressure"}
    ds_day["rh"].attrs = {"units": "%", "long_name": "relative humidity"}

    return ds_day


# %%
# --------------------------------------------------------------------
# 5. Metadata and file naming
# --------------------------------------------------------------------
def add_daily_metadata(ds_day, date_obj):
    """
    Add global attributes for the daily ship PosRef file.
    """
    creation_time = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str      = date_obj.strftime("%Y-%m-%d")

    ds_day.attrs["title"] = (
        "Daily ship position and basic meteorology onboard "
        f"RV Kronprins Haakon during cruise {CAMPAIGN}"
    )
    ds_day.attrs["institution"] = "Department of Geoscience, University of Oslo, Norway"
    ds_day.attrs["principal_investigator"] = (
        "Paul Dodd (Norwegian Polar Institute, Tromsø, Norway)"
    )
    ds_day.attrs["file_creator"] = "Tim Carlsen (University of Oslo)"
    ds_day.attrs["data_contact"] = "Tim Carlsen (tim.carlsen@geo.uio.no)"
    ds_day.attrs["data_contact2"] = "Robert O. David (r.o.david@geo.uio.no)"
    ds_day.attrs["instrument"] = "Ship navigation and meteorological reference data (PosRef)"
    ds_day.attrs["campaign"] = CAMPAIGN
    ds_day.attrs["date_created"] = creation_time
    ds_day.attrs["date_coverage"] = date_str

    if ds_day.sizes.get("time", 0) > 0:
        ds_day.attrs["time_coverage_start"] = str(ds_day["time"].values[0])
        ds_day.attrs["time_coverage_end"]   = str(ds_day["time"].values[-1])

    ds_day.attrs["history"] = (
        f"Created from PosRef CSV files on {creation_time} UTC "
        f"using ship_posref_aggregate_daily.py"
    )
    ds_day.attrs["license"] = "CC BY-SA 4.0"
    ds_day.attrs["Conventions"] = "CF-1.13"

    return ds_day


# %%
def daily_file_path(date_obj):
    """
    Path to the daily NetCDF file for the given date.
    """
    date_tag = date_obj.strftime("%Y%m%d")
    return os.path.join(PROCESSED_DIR, f"{date_tag}_ship_posref_daily.nc")


# %%
def should_reprocess_day(date_obj, src_files):
    """
    Decide whether to (re)process the given day based on modification times.
    """
    out_path = daily_file_path(date_obj)

    if not os.path.exists(out_path):
        print(f"[INFO] No daily file yet for {date_obj}, will create it.")
        return True

    daily_mtime = os.path.getmtime(out_path)
    src_mtimes = [os.path.getmtime(f) for f in src_files]
    max_src_mtime = max(src_mtimes) if src_mtimes else 0.0

    if max_src_mtime > daily_mtime:
        print(f"[INFO] PosRef CSVs updated for {date_obj}, will reprocess.")
        return True
    else:
        print(f"[INFO] Daily ship PosRef file for {date_obj} is up-to-date, skipping.")
        return False


# %%
def write_daily_file(ds_day, date_obj):
    """
    Write daily dataset to NetCDF in PROCESSED_DIR.
    """
    out_path = daily_file_path(date_obj)
    print(f"[INFO] Writing daily ship PosRef file: {out_path}")
    ds_day.to_netcdf(
        out_path,
        engine=ENGINE_WRITE,
        format="NETCDF4",
    )


# %%
# --------------------------------------------------------------------
# 6. Main program
# --------------------------------------------------------------------
def main():
    all_files = find_all_posref_files()
    print(f"[INFO] Found {len(all_files)} PosRef CSV files.")

    if not all_files:
        print("[ERROR] No PosRef files found. Check NAS_ROOT/CAMPAIGN/ship/PosRef.")
        return

    grouped = group_files_by_day(all_files)
    all_days = sorted(grouped.keys())
    print(f"[INFO] Found data for {len(all_days)} unique days.")

    today = dt.date.today()
    earliest_day_to_consider = today - dt.timedelta(days=DAYS_BACK)

    days_to_process = [d for d in all_days if d >= earliest_day_to_consider]
    print(f"[INFO] Will consider {len(days_to_process)} day(s) from "
          f"{earliest_day_to_consider} to {today}.")

    for day in days_to_process:
        day_files = grouped[day]
        print(f"\n[INFO] Candidate day {day} with {len(day_files)} PosRef file(s).")

        # Check if we need to (re)process this day
        if not should_reprocess_day(day, day_files):
            continue

        # Combine CSVs into daily Dataset
        try:
            ds_day = combine_day_posref(day_files)
        except Exception as e:
            print(f"[WARN] Could not build dataset for {day}: {e}")
            continue

        # Add metadata
        ds_day = add_daily_metadata(ds_day, day)

        # Write to disk
        write_daily_file(ds_day, day)

        # Close dataset
        ds_day.close()

    print("\n[INFO] Done.")


# %%
if __name__ == "__main__":
    main()
