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
skyvue_ceilometer_aggregate_daily.py

Combine hourly SkyVue PRO ceilometer TOA5 .dat files into daily netcdf files
+ adding some metadata.
"""

# %%
import os
import glob
import datetime as dt
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import NullFormatter, FuncFormatter

# %%
from skyvue_processing import build_dataset_from_file
from skypallet_config import load_config  # or wherever you put it
from pathlib import Path



# %%
# --------------------------------------------------------------------
# 1. Load configuration
# --------------------------------------------------------------------
HERE = os.path.dirname(__file__)
cfg_path = os.path.join(HERE, "skypallet_config_mac.yml")
cfg = load_config(cfg_path)

CAMPAIGN = cfg["campaign"]
NAS_ROOT = cfg["paths"]["nas_root"]

# Build instrument-specific roots here
CEIL_ROOT      = os.path.join(NAS_ROOT, CAMPAIGN, "skyvue-ceilometer")
PROCESSED_DIR  = os.path.join(CEIL_ROOT, "processed")

ENGINE_WRITE = cfg["general"]["engine_write"]
DAYS_BACK    = cfg["general"]["days_back"]

Path(PROCESSED_DIR).mkdir(parents=True, exist_ok=True)


# %%
# Variables and coordinates to keep (adjust to your actual dataset variables)
VARS_TO_KEEP = [
    "beta_att_total",
    "beta_att_par",
    "beta_att_cross",
    "ldr",
    "laser_energy_pct",
    "laser_temp_C",
    "window_trans_pct",
    "detection_status",
    "wa_flag",
    "cloud_base_1_m",
    "cloud_base_2_m",
    "cloud_base_3_m",
    "cloud_base_4_m",
    "vertical_visibility_m",
    "mlh1_m",
    "mlh1_quality",
    "mlh2_m",
    "mlh2_quality",
    "mlh3_m",
    "mlh3_quality",
    "cloud_ldr_1",
    "cloud_ldr_2",
    "cloud_ldr_3",
    "cloud_ldr_4",
    "ground_temp_C",
    "cloud_depth_1",
    "cloud_depth_2",
    "cloud_depth_3",
    "cloud_depth_4",
    # Alarm flags (all bits)
    "units_meters_and_precip",
    "units_meters",
    "precipitation_detected",
    "dsp_clock_out_of_spec",
    "laser_shutdown_temp_out_of_range",
    "lead_acid_battery_low",
    "mains_supply_failed",
    "ext_heater_blower_temp_out_of_bounds",
    "ext_heater_blower_failure",
    "internal_humidity_high",
    "comms_dsp_th_failed",
    "dsp_input_voltage_low",
    "self_test_active",
    "watchdog_counter_updated",
    "user_settings_flash_bad",
    "factory_cal_flash_bad",
    "dsp_flash_general_fault",
    "comms_top_dsp_failed",
    "photodiode_background_out_of_range",
    "photodiode_temp_out_of_range",
    "photodiode_saturated",
    "photodiode_cal_temp_out_of_range",
    "photodiode_cal_failed",
    "laser_off",
]
COORDS_TO_KEEP = ["time", "range"]


# %%
# --------------------------------------------------------------------
# 2. Find all hourly files
# --------------------------------------------------------------------
def find_all_ceilometer_files():
    """
    Find all hourly SkyVue ceilometer files under CEIL_ROOT
    """
    file_pattern = os.path.join(CEIL_ROOT, "*.dat")
    all_files = sorted(glob.glob(file_pattern))
    return all_files


# %%
# --------------------------------------------------------------------
# 3. Group files by date
# --------------------------------------------------------------------
def extract_date_from_filename(path):
    """
    Extract date (YYYYMMDD) from filename like:
    SkyPallet-IP_SkyVueProRaw_YYYY_MM_DD_hhmm.dat

    Returns a datetime.date.
    """
    base = os.path.basename(path)
    # Example: 'SkyPallet-IP_SkyVueProRaw_2025_02_28_2044.dat'
    parts = base.split("_")

    # Expect: ['SkyPallet-IP', 'SkyVueProRaw', 'YYYY', 'MM', 'DD', 'hhmm.dat']
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
            # Skip files with unexpected naming
            continue
        by_day.setdefault(d, []).append(f)
    return by_day


# %%
# --------------------------------------------------------------------
# 4. Open files (skip unreadable files)
# --------------------------------------------------------------------
def filter_readable_files(files):
    """
    Try building a dataset from each hourly .dat file; keep only those that work.
    """
    good = []
    bad = []
    for path in files:
        try:
            ds_tmp = build_dataset_from_file(path)
            ds_tmp.close()
            good.append(path)
        except Exception as e:
            print(f"[WARN] Skipping unreadable file: {path}")
            print(f"       Error: {repr(e)}")
            bad.append(path)
    return good, bad


# %%
# --------------------------------------------------------------------
# 5. Combine hourly files into a daily dataset
# --------------------------------------------------------------------
def combine_day(files_for_day):
    """
    Combine hourly ceilometer .dat files for one day into a single xarray.Dataset.
    """
    if not files_for_day:
        raise RuntimeError("No readable files provided for this day.")

    ds_list = []
    for path in sorted(files_for_day):
        ds_hour = build_dataset_from_file(path)
        ds_list.append(ds_hour)

    # Concatenate along time
    ds_day = xr.concat(ds_list, dim="time")

    # Close hourly datasets
    for ds_hour in ds_list:
        ds_hour.close()

    # Determine which requested vars/coords actually exist
    keep_vars   = [v for v in VARS_TO_KEEP   if v in ds_day]
    keep_coords = [c for c in COORDS_TO_KEEP if c in ds_day.coords]

    # Subset dataset
    ds_day = ds_day[keep_vars + keep_coords]

    return ds_day


# %%
# --------------------------------------------------------------------
# 6. Add extra metadata
# --------------------------------------------------------------------
def add_daily_metadata(ds_day, date_obj):
    """
    Add global attributes and variable attributes for the daily file.
    """
    creation_time = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str      = date_obj.strftime("%Y-%m-%d")

    # Global attributes
    ds_day.attrs["title"] = (
        "Daily SkyVue PRO ceilometer file from SkyPallet onboard RV Kronprins Haakon "
        f"during cruise {CAMPAIGN}"
    )
    ds_day.attrs["institution"] = "Department of Geoscience, University of Oslo, Norway"
    ds_day.attrs["principal_investigator"] = (
        "Tim Carlsen, Robert O. David, Trude Storelvmo (University of Oslo, Norway)"
    )
    ds_day.attrs["file_creator"] = "Tim Carlsen (University of Oslo)"
    ds_day.attrs["data_contact"] = "Tim Carlsen (tim.carlsen@geo.uio.no)"
    ds_day.attrs["data_contact2"] = "Robert O. David (r.o.david@geo.uio.no)"
    ds_day.attrs["instrument"] = "SkyVue PRO (CS135) LIDAR ceilometer"
    ds_day.attrs["campaign"] = CAMPAIGN
    ds_day.attrs["date_created"] = creation_time
    ds_day.attrs["date_coverage"] = date_str
    ds_day.attrs["history"] = (
        f"Created from hourly SkyVue PRO TOA5 .dat files on {creation_time} UTC "
        f"using skyvue_ceilometer_aggregate_daily.py"
    )
    ds_day.attrs["license"] = "CC BY-SA 4.0"
    ds_day.attrs["Conventions"] = "CF-1.13"
    ds_day.attrs["Acknowledgement"] = (
        "The operation of the Skypallet was made possible thanks to the support of "
        "Polhavet 2050, the European Research Council through ERC Consolidator Grant "
        "“STEP-CHANGE” (grant number 101045273), and the University of Oslo’s Cold "
        "Climate Container Facilities."
    )

    return ds_day


# %%
# --------------------------------------------------------------------
# 7. Daily file path and reprocessing check
# --------------------------------------------------------------------
def daily_file_path(date_obj):
    """
    Path to the daily NetCDF file for the given date.
    """
    date_tag = date_obj.strftime("%Y%m%d")
    return os.path.join(PROCESSED_DIR, f"{date_tag}_skyvue_ceilometer_daily.nc")


# %%
def should_reprocess_day(date_obj, hourly_files):
    """
    Decide whether to (re)process the given day based on modification times.
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


# %%
# --------------------------------------------------------------------
# 8. Write daily NetCDF file
# --------------------------------------------------------------------
def write_daily_file(ds_day, date_obj):
    """
    Write daily dataset to netcdf in PROCESSED_DIR.
    """
    out_path = daily_file_path(date_obj)
    print(f"[INFO] Writing daily file: {out_path}")
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
    # Find all hourly files
    all_files = find_all_ceilometer_files()
    print(f"[INFO] Found {len(all_files)} hourly SkyVue PRO files.")

    if not all_files:
        print("[ERROR] No ceilometer files found. Check NAS_ROOT and directory structure.")
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


# %%
if __name__ == "__main__":
    main()


