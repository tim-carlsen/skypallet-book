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
#     display_name: skypallet
#     language: python
#     name: python3
# ---

# %%
"""
cnr4_aggregate_daily.py

Combine hourly CNR4 .dat files into daily netcdf files, adding metadata.
"""

# %%
import os
import glob
import datetime as dt
import pandas as pd
import xarray as xr
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
CNR4_ROOT      = os.path.join(NAS_ROOT, CAMPAIGN, "cnr4")
PROCESSED_DIR  = os.path.join(CNR4_ROOT, "processed")

ENGINE_WRITE = cfg["general"]["engine_write"]
DAYS_BACK    = cfg["general"]["days_back"]

Path(PROCESSED_DIR).mkdir(parents=True, exist_ok=True)



# %%
# --------------------------------------------------------------------
# 2. Find all hourly files
# --------------------------------------------------------------------
def find_all_cnr4_files():
    """
    Find all hourly CNR4 files.

    Adjust pattern to your actual structure, e.g.:

    ../EBT2026/cnr4/SkyPallet-IP_CNR4_2026_08_04_00.dat

    Here we assume:
        CNR4_ROOT/*.dat
    """
    file_pattern = os.path.join(CNR4_ROOT, "*.dat")
    all_files = sorted(glob.glob(file_pattern))
    return all_files


# %%
# --------------------------------------------------------------------
# 3. Group files by date
# --------------------------------------------------------------------
def extract_date_from_filename(path):
    """
    Extract date (YYYYMMDD) from filename like:
    SkyPallet-IP_CNR4_YYYY_MM_DD_hhmm.dat

    Returns a datetime.date.
    """
    base = os.path.basename(path)
    # Example: 'SkyPallet-IP_CNR4_2025_02_28_2044.dat'
    parts = base.split("_")

    # Expect: ['SkyPallet-IP', 'CNR4', 'YYYY', 'MM', 'DD', 'hhmm.dat']
    if len(parts) < 6:
        raise ValueError(f"Unexpected filename format: {base}")

    year = parts[2]
    month = parts[3]
    day = parts[4]

    date_str = f"{year}{month}{day}"  # 'YYYYMMDD'
    return dt.datetime.strptime(date_str, "%Y%m%d").date()


# %%
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
            continue
        by_day.setdefault(d, []).append(f)
    return by_day


# %%
# --------------------------------------------------------------------
# 4. Read one TOA5 CNR4 file to xarray
# --------------------------------------------------------------------
def read_cnr4_file(path):
    """
    Read one hourly CNR4 TOA5 .dat file into an xarray.Dataset.

    Assumes TOA5 structure:
        line 0: file info
        line 1: field names
        line 2: units
        line 3: field types (TS, RN, etc.)
        line 4+: data
    """
    df = pd.read_csv(
        path,
        sep=",",
        header=1,              # line 1 has field names
        skiprows=[2, 3],       # skip units and type lines so they are not data
        na_values=["NAN", "nan", "NaN"],
    )

    if "TIMESTAMP" not in df.columns:
        raise RuntimeError(f"No TIMESTAMP column in {path}")

    df["time"] = pd.to_datetime(
        df["TIMESTAMP"],
        format="%Y-%m-%d %H:%M:%S",
        errors="coerce",
    )

    # Drop any rows where time could not be parsed (just in case)
    df = df.dropna(subset=["time"])
    df = df.set_index("time")

    # Rename to more descriptive names
    rename_map = {
        "RECORD": "record",
        "Rs_downwell": "SW_down",
        "Rs_upwell":   "SW_up",
        "Rl_downwell": "LW_down",
        "Rl_upwell":   "LW_up",
        "T_nr":        "T_nr",
        "T_K_nr":      "T_K_nr",
        "Rl_down_meas": "LW_down_meas",
        "Rl_up_meas":   "LW_up_meas",
        "RS": "RS",
        "pulse_CNR4": "pulse_CNR4",
        "CRDResult_CNR4": "CRDResult_CNR4",
    }

    keep_cols = [c for c in rename_map if c in df.columns]
    df = df[keep_cols].rename(columns=rename_map)

    df["source_file"] = os.path.basename(path)

    ds = df.to_xarray()

    # add units and metadata (as you already had)
    ds["time"].attrs = {"long_name": "UTC time of measurement"}

    ds["SW_down"].attrs = {
        "long_name": "downwelling solar (shortwave) radiation",
        "units": "W m^-2",
        "instrument": "CNR4 pyranometer",
    }
    ds["SW_up"].attrs = {
        "long_name": "upwelling solar (shortwave) radiation",
        "units": "W m^-2",
        "instrument": "CNR4 pyranometer",
    }
    ds["LW_down"].attrs = {
        "long_name": "downwelling terrestrial (longwave) radiation",
        "units": "W m^-2",
        "instrument": "CNR4 pyrgeometer",
    }
    ds["LW_up"].attrs = {
        "long_name": "upwelling terrestrial (longwave) radiation",
        "units": "W m^-2",
        "instrument": "CNR4 pyrgeometer",
    }

    ds["record"].attrs = {
        "long_name": "CR1000X record number for CNR4 logging",
        "description": "Monotonic integer record counter from the CR1000X datalogger.",
        "units": "",
    }

    ds["T_nr"].attrs = {
        "long_name": "CNR4 body thermistor temperature",
        "description": "CNR4 net radiometer internal body temperature measured by thermistor/Pt100.",
        "units": "°C",
        "instrument": "CNR4 body thermistor/Pt100",
    }

    ds["T_K_nr"].attrs = {
        "long_name": "CNR4 body thermistor temperature (Kelvin)",
        "description": "CNR4 net radiometer internal body temperature measured by thermistor/Pt100.",
        "units": "K",
        "instrument": "CNR4 body thermistor/Pt100",
    }

    ds["LW_down_meas"].attrs = {
        "long_name": "Downwelling terrestrial (longwave) raw signal",
        "description": (
            "Raw downwelling terrestrial (longwave) signal from CNR4 pyrgeometer "
            "before application of calibration and temperature correction."
        ),
        "units": "µV",
        "instrument": "CNR4 pyrgeometer",
    }

    ds["LW_up_meas"].attrs = {
        "long_name": "Upwelling terrestrial (longwave) raw signal",
        "description": (
            "Raw upwelling terrestrial (longwave) signal from CNR4 pyrgeometer "
            "before application of calibration and temperature correction."
        ),
        "units": "µV",
        "instrument": "CNR4 pyrgeometer",
    }

    ds["pulse_CNR4"].attrs = {"long_name": "CNR4 pulse/diagnostic value"}
    ds["CRDResult_CNR4"].attrs = {"long_name": "Diagnostic integer flag"}

    ds["source_file"].attrs = {
        "long_name": "original data file name",
        "description": "Name of the TOA5 .dat file from which this record was read.",
    }

    return ds



# %%
# --------------------------------------------------------------------
# 5. Filter readable files
# --------------------------------------------------------------------
def filter_readable_files(files):
    """
    Try reading each file; keep only those that can be read.
    """
    good, bad = [], []
    for path in files:
        try:
            ds_tmp = read_cnr4_file(path)
            ds_tmp.close()
            good.append(path)
        except Exception as e:
            print(f"[WARN] Skipping unreadable CNR4 file: {path}")
            print(f"       Error: {repr(e)}")
            bad.append(path)
    return good, bad


# %%
# --------------------------------------------------------------------
# 6. Combine hourly files into daily dataset
# --------------------------------------------------------------------
def combine_day(files_for_day):
    """
    Read and concatenate hourly CNR4 files for one day into a single Dataset.
    """
    if not files_for_day:
        raise RuntimeError("No readable CNR4 files provided for this day.")

    ds_list = [read_cnr4_file(f) for f in files_for_day]
    # concat along time; the TOA5 timestamps should be unique and ordered
    ds_day = xr.concat(ds_list, dim="time")
    ds_day = ds_day.sortby("time")

    return ds_day


# %%
# --------------------------------------------------------------------
# 7. Add daily metadata
# --------------------------------------------------------------------
def add_daily_metadata(ds_day, date_obj):
    """
    Add global attributes for the daily CNR4 file.
    """
    creation_time = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str      = date_obj.strftime("%Y-%m-%d")

    ds_day.attrs.update({
        "title": "CNR4 surface radiation measurements from SkyPallet onboard RV Kronprins Haakon during " + CAMPAIGN,
        "institution": "Department of Geoscience, University of Oslo, Norway",
        "file_creator": "Tim Carlsen (University of Oslo)",
        "data_contact": "Tim Carlsen (tim.carlsen@geo.uio.no)",
        "data_contact2": "Robert O. David (r.o.david@geo.uio.no)",
        "instrument": "CNR4 net radiometer, CR1000X datalogger",
        "campaign": CAMPAIGN,
        "date_created": creation_time,
        "date_coverage": date_str,
        "time_coverage_start": str(ds_day["time"].values[0]),
        "time_coverage_end": str(ds_day["time"].values[-1]),
        "history": (
            f"Aggregated from hourly CNR4 TOA5 .dat files on {creation_time} UTC "
            f"using cnr4_aggregate_daily.py"
        ),
        "license": "CC BY-SA 4.0",
        "Conventions": "CF-1.13",
        "Acknowledgement": (
            "The operation of the Skypallet was made possible thanks to the support of "
            "Polhavet 2050, the European Research Council through ERC Consolidator Grant "
            "“STEP-CHANGE” (grant number 101045273), and the University of Oslo’s Cold "
            "Climate Container Facilities."
        ),
    })

    return ds_day


# %%
# --------------------------------------------------------------------
# 8. Daily file path and reprocessing check
# --------------------------------------------------------------------
def daily_file_path(date_obj):
    """
    Path to the daily netcdf file for the given date.
    """
    date_tag = date_obj.strftime("%Y%m%d")
    return os.path.join(PROCESSED_DIR, f"{date_tag}_cnr4_daily.nc")


# %%
def should_reprocess_day(date_obj, hourly_files):
    """
    Same logic as MRR: reprocess if daily file missing or older than any hourly file.
    """
    out_path = daily_file_path(date_obj)

    if not os.path.exists(out_path):
        print(f"[INFO] No daily CNR4 file yet for {date_obj}, will create it.")
        return True

    daily_mtime = os.path.getmtime(out_path)
    hourly_mtimes = [os.path.getmtime(f) for f in hourly_files]
    max_hourly_mtime = max(hourly_mtimes) if hourly_mtimes else 0.0

    if max_hourly_mtime > daily_mtime:
        print(f"[INFO] New hourly CNR4 files detected for {date_obj}, will reprocess.")
        return True
    else:
        print(f"[INFO] Daily CNR4 file for {date_obj} is up-to-date, skipping.")
        return False


# %%
# --------------------------------------------------------------------
# 9. Write daily NetCDF file
# --------------------------------------------------------------------
def write_daily_file(ds_day, date_obj):
    out_path = daily_file_path(date_obj)
    print(f"[INFO] Writing daily CNR4 file: {out_path}")
    ds_day.to_netcdf(
        out_path,
        engine=ENGINE_WRITE,
        format="NETCDF4",
    )


# %%
# --------------------------------------------------------------------
# 10. Main
# --------------------------------------------------------------------
def main():
    all_files = find_all_cnr4_files()
    print(f"[INFO] Found {len(all_files)} hourly CNR4 files.")

    if not all_files:
        print("[ERROR] No CNR4 files found. Check NAS_ROOT and directory structure.")
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
        print(f"\n[INFO] Candidate day {day} with {len(day_files)} hourly CNR4 files.")

        good_files, bad_files = filter_readable_files(day_files)
        print(f"[INFO] Day {day}: {len(good_files)} readable files, {len(bad_files)} unreadable.")

        if not good_files:
            print(f"[WARN] No readable CNR4 files for {day}, skipping.")
            continue

        if not should_reprocess_day(day, good_files):
            continue

        ds_day = combine_day(good_files)
        ds_day = add_daily_metadata(ds_day, day)
        write_daily_file(ds_day, day)
        ds_day.close()

    print("\n[INFO] Done.")


# %%
if __name__ == "__main__":
    main()
