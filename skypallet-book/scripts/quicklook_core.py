# quicklook_core.py

import os
import datetime as dt

import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LogNorm
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
import matplotlib.ticker as mticker
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from windrose import WindroseAxes
import yaml


# --------------------------------------------------------------------
# 1. Configuration
# --------------------------------------------------------------------

def load_config(path="skypallet_config.yml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)


# --------------------------------------------------------------------
# 2. Time axis helpers
# --------------------------------------------------------------------

def make_hour_ticks():
    """Major ticks every 4 hours (00,04,08,12,16,20), minor ticks every 1 hour."""
    major_locator = mdates.HourLocator(byhour=[0, 4, 8, 12, 16, 20])
    major_formatter = mdates.DateFormatter("%H:%M\n%d %b")
    minor_locator = mdates.HourLocator(interval=1)
    return major_locator, major_formatter, minor_locator


def setup_time_axis(ax, start, end):
    """Apply common time axis formatting."""
    major_locator, major_formatter, minor_locator = make_hour_ticks()
    ax.set_xlim(start, end)
    ax.xaxis.set_major_locator(major_locator)
    ax.xaxis.set_major_formatter(major_formatter)
    ax.xaxis.set_minor_locator(minor_locator)
    # Vertical grid only at major (every 4 hours), darker
    ax.grid(True, which="major", axis="x", linestyle="-", alpha=0.6)
    ax.tick_params(axis="x", labelsize=0)  # hide default labels


def set_custom_time_date_ticks(ax, start, end):
    """
    Two-line x-axis labels:
      top line: time (HH:MM)
      bottom line: date (DD Mon) only at 00 UTC.
    """
    ticks = ax.get_xticks()
    if len(ticks) == 0:
        return

    tick_datetimes = mdates.num2date(ticks)
    ax.set_xticklabels([])

    trans = ax.get_xaxis_transform()

    for t_num, t_dt in zip(ticks, tick_datetimes):
        if t_dt.tzinfo is not None:
            t_dt = t_dt.replace(tzinfo=None)

        if t_dt < start or t_dt > end:
            continue

        # Time (always)
        ax.text(
            t_num, -0.05,
            t_dt.strftime("%H:%M"),
            transform=trans,
            ha="center", va="top",
            fontsize=8,
            color="black",
            clip_on=False,
        )

        # Date only at 00 UTC
        if t_dt.hour == 0 and t_dt.minute == 0:
            ax.text(
                t_num, -0.15,
                t_dt.strftime("%d %b"),
                transform=trans,
                ha="center", va="top",
                fontsize=7,
                color="dimgray",
                clip_on=False,
            )


def shade_missing(ax, missing_intervals, start, end, color="lightgrey", alpha=0.3):
    """Shade intervals of missing data on time axis."""
    if not missing_intervals:
        return
    for (m_start, m_end) in missing_intervals:
        s = max(start, m_start)
        e = min(end, m_end)
        if s >= e:
            continue
        ax.axvspan(s, e, color=color, alpha=alpha, zorder=0)


# --------------------------------------------------------------------
# 3. Generic daily file opener
# --------------------------------------------------------------------

def _open_daily_file(root, date_str, suffix):
    """
    Try to open a daily file named 'YYYYMMDD_suffix.nc' under `root`.
    Return xarray.Dataset or None.
    """
    fname = f"{date_str}_{suffix}.nc"
    path = os.path.join(root, fname)
    if not os.path.isfile(path):
        return None
    try:
        return xr.open_dataset(path)
    except Exception:
        return None


# --------------------------------------------------------------------
# 4. Instrument data loaders
# --------------------------------------------------------------------

def load_mrr_data(start, end, cfg):
    """Load MRR Ze and VEL for [start, end] UTC from daily files."""
    CAMPAIGN = cfg["campaign"]
    NAS_ROOT = cfg["paths"]["nas_root"]
    MRR_ROOT = os.path.join(NAS_ROOT, CAMPAIGN, "mrr", "processed")

    dates = sorted({start.date(), end.date()})
    ds_list = []
    missing_intervals = []

    for d in dates:
        date_str = d.strftime("%Y%m%d")
        ds = _open_daily_file(MRR_ROOT, date_str, "mrr_daily")
        if ds is not None:
            ds_list.append(ds)
        else:
            day_start = dt.datetime(d.year, d.month, d.day)
            day_end = day_start + dt.timedelta(days=1)
            missing_intervals.append((day_start, day_end))

    if not ds_list:
        return None, None, None, missing_intervals

    ds_all = xr.concat(ds_list, dim="time").sortby("time")
    ds_sel = ds_all.sel(time=slice(start, end))

    time = ds_sel["time"].to_index()
    height = ds_sel["range"].values  # m

    Ze = ds_sel["Ze"].transpose("time", "range")
    VEL = ds_sel["VEL"].transpose("time", "range")

    return time, height, (Ze, VEL), missing_intervals


def load_skyvue_data(start, end, cfg):
    """Load Skyvue backscatter and depolarization for [start, end]."""
    CAMPAIGN = cfg["campaign"]
    NAS_ROOT = cfg["paths"]["nas_root"]
    CEIL_ROOT = os.path.join(NAS_ROOT, CAMPAIGN, "skyvue-ceilometer", "processed")

    dates = sorted({start.date(), end.date()})
    ds_list = []
    missing_intervals = []

    print("[Skyvue] CEIL_ROOT:", CEIL_ROOT)
    print("[Skyvue] Requested dates:", dates)

    for d in dates:
        date_str = d.strftime("%Y%m%d")
        fname = f"{date_str}_skyvue_ceilometer_daily.nc"
        path = os.path.join(CEIL_ROOT, fname)
        print("[Skyvue] Looking for:", path, "exists:", os.path.isfile(path))

        ds = _open_daily_file(CEIL_ROOT, date_str, "skyvue_ceilometer_daily")
        if ds is not None:
            print("[Skyvue] Opened file for", d, "time size:", ds.sizes.get("time", 0))
            ds_list.append(ds)
        else:
            print("[Skyvue] Could not open file for", d)
            day_start = dt.datetime(d.year, d.month, d.day)
            day_end = day_start + dt.timedelta(days=1)
            missing_intervals.append((day_start, day_end))

    if not ds_list:
        print("[Skyvue] No daily files opened for this window.")
        return None, None, None, missing_intervals

    ds_all = xr.concat(ds_list, dim="time").sortby("time")

    ds_sel = ds_all.sel(time=slice(start, end))

    time = ds_sel["time"].to_index()
    height = ds_sel["range"].values  # m

    beta = ds_sel["beta_att_total"].transpose("time", "range")
    depol = ds_sel["ldr"].transpose("time", "range")

    beta_plot = beta.where(beta > 0)
    depol_plot = depol.clip(0, 1)

    cbh = ds_sel["cloud_base_heights"] if "cloud_base_heights" in ds_sel else None

    return time, height, (beta_plot, depol_plot, cbh), missing_intervals



def load_cnr4_data(start, end, cfg):
    """Load CNR4 SW_down and LW_down for [start, end]."""
    CAMPAIGN = cfg["campaign"]
    NAS_ROOT = cfg["paths"]["nas_root"]
    CNR4_ROOT = os.path.join(NAS_ROOT, CAMPAIGN, "cnr4", "processed")

    dates = sorted({start.date(), end.date()})
    ds_list = []
    missing_intervals = []

    for d in dates:
        date_str = d.strftime("%Y%m%d")
        ds = _open_daily_file(CNR4_ROOT, date_str, "cnr4_daily")
        if ds is not None:
            ds_list.append(ds)
        else:
            day_start = dt.datetime(d.year, d.month, d.day)
            day_end = day_start + dt.timedelta(days=1)
            missing_intervals.append((day_start, day_end))

    if not ds_list:
        return None, None, missing_intervals

    ds_all = xr.concat(ds_list, dim="time").sortby("time")
    ds_sel = ds_all.sel(time=slice(start, end))

    time = ds_sel["time"].to_index()
    sw = ds_sel["SW_down"]
    lw = ds_sel["LW_down"]

    return time, (sw, lw), missing_intervals


def load_ship_track_all(cfg):
    """
    Load full cruise ship track (lat, lon, time) from all PosRef daily NetCDF files.
    """
    CAMPAIGN = cfg["campaign"]
    NAS_ROOT = cfg["paths"]["nas_root"]
    SHIP_ROOT = os.path.join(NAS_ROOT, CAMPAIGN, "ship", "PosRef", "processed")

    if not os.path.isdir(SHIP_ROOT):
        return None, None, None

    files = sorted(
        f for f in os.listdir(SHIP_ROOT)
        if f.endswith("_ship_posref_daily.nc") and len(f.split("_")[0]) == 8
    )
    if not files:
        return None, None, None

    ds_list = []
    for fname in files:
        path = os.path.join(SHIP_ROOT, fname)
        try:
            ds = xr.open_dataset(path)
            ds_list.append(ds)
        except Exception:
            continue

    if not ds_list:
        return None, None, None

    ds_all = xr.concat(ds_list, dim="time").sortby("time")
    if ds_all.sizes.get("time", 0) == 0:
        return None, None, None

    time = ds_all["time"].to_index()
    lat = ds_all["lat"].values
    lon = ds_all["lon"].values

    cruise_start = None
    if "ship" in cfg and "cruise_start" in cfg["ship"]:
        try:
            cruise_start = dt.datetime.fromisoformat(cfg["ship"]["cruise_start"])
        except Exception:
            cruise_start = None

    if cruise_start is not None:
        mask = time >= cruise_start
        if not mask.any():
            return None, None, None
        time = time[mask]
        lat = lat[mask]
        lon = lon[mask]

    return time, lat, lon


def load_aws_data(start, end, cfg):
    """
    Load vessel-mounted AWS data for [start, end] UTC from daily files.

    Files:
      NAS_ROOT/CAMPAIGN/ship/Vaisala_AWS/processed/YYYYMMDD_aws_daily.nc
    """
    CAMPAIGN = cfg["campaign"]
    NAS_ROOT = cfg["paths"]["nas_root"]
    AWS_ROOT = os.path.join(NAS_ROOT, CAMPAIGN, "ship", "Vaisala_AWS", "processed")

    dates = sorted({start.date(), end.date()})
    ds_list = []
    missing_intervals = []

    for d in dates:
        date_str = d.strftime("%Y%m%d")
        fname = f"{date_str}_aws_daily.nc"
        path = os.path.join(AWS_ROOT, fname)
        if not os.path.isfile(path):
            day_start = dt.datetime(d.year, d.month, d.day)
            day_end = day_start + dt.timedelta(days=1)
            missing_intervals.append((day_start, day_end))
            continue
        try:
            ds = xr.open_dataset(path)
            ds_list.append(ds)
        except Exception:
            day_start = dt.datetime(d.year, d.month, d.day)
            day_end = day_start + dt.timedelta(days=1)
            missing_intervals.append((day_start, day_end))

    if not ds_list:
        return None, None, missing_intervals

    ds_all = xr.concat(ds_list, dim="time").sortby("time")
    ds_sel = ds_all.sel(time=slice(start, end))

    if "time" not in ds_sel.coords or ds_sel.sizes.get("time", 0) == 0:
        return None, None, missing_intervals

    aws_time = ds_sel["time"].to_index()
    return aws_time, ds_sel, missing_intervals


# --------------------------------------------------------------------
# 5. All-sky image finder
# --------------------------------------------------------------------

def find_latest_allsky_image(now, cfg):
    """
    Find latest ASI-16 all-sky image with *_11 in filename.
    """
    NAS_ROOT = cfg["paths"]["nas_root"]
    CAMPAIGN = cfg["campaign"]
    ASI_ROOT = os.path.join(NAS_ROOT, CAMPAIGN, "asi-16/asi_16662")

    if not os.path.isdir(ASI_ROOT):
        return None, None

    latest_path = None
    latest_time = None

    for date_dir in sorted(os.listdir(ASI_ROOT)):
        full_date_dir = os.path.join(ASI_ROOT, date_dir)
        if not os.path.isdir(full_date_dir):
            continue
        try:
            dt.datetime.strptime(date_dir, "%Y%m%d")
        except ValueError:
            continue

        for fname in sorted(os.listdir(full_date_dir)):
            if not fname.lower().endswith(".jpg"):
                continue
            if "_11" not in fname:
                continue

            base = os.path.splitext(fname)[0]
            stamp = base.split("_")[0]
            try:
                t = dt.datetime.strptime(stamp, "%Y%m%d%H%M%S")
            except ValueError:
                continue

            if t <= now and (latest_time is None or t > latest_time):
                latest_time = t
                latest_path = os.path.join(full_date_dir, fname)

    return latest_path, latest_time


# --------------------------------------------------------------------
# 6. Small helper for AWS dashboard
# --------------------------------------------------------------------

def _get_latest_valid(ds, var_name, now):
    """
    Return latest value of ds[var_name] at or before 'now', ignoring NaNs.
    """
    if ds is None or var_name not in ds:
        return None
    da = ds[var_name]
    if "time" not in da.coords:
        return None

    da_sel = da.sel(time=slice(None, now))
    if da_sel.size == 0:
        return None

    vals = np.asarray(da_sel.values).ravel()
    for v in vals[::-1]:
        try:
            if np.isfinite(v):
                return float(v)
        except Exception:
            continue
    return None


# --------------------------------------------------------------------
# 7. Main figure creation
# --------------------------------------------------------------------

def create_quicklook_figure(cfg, start, end, out_path, now=None):
    """
    Create multi-panel quicklook figure for [start, end] (UTC).
    """
    if now is None:
        now = end

    # Load data
    mrr_time, mrr_height, mrr_vars, mrr_missing = load_mrr_data(start, end, cfg)
    sky_time, sky_height, sky_vars, sky_missing = load_skyvue_data(start, end, cfg)
    cnr_time, cnr_vars, cnr_missing = load_cnr4_data(start, end, cfg)
    ship_time, ship_lat, ship_lon = load_ship_track_all(cfg)
    aws_time, aws_ds, aws_missing = load_aws_data(start, end, cfg)
    asi_path, asi_time = find_latest_allsky_image(now, cfg)

    Ze, VEL = (None, None) if mrr_vars is None else mrr_vars
    beta_plot, depol_plot, cbh = (None, None, None) if sky_vars is None else sky_vars
    sw, lw = (None, None) if cnr_vars is None else cnr_vars

    # Figure layout: 3 rows × 3 columns, equal width top row
    fig = plt.figure(figsize=(12, 8), constrained_layout=True)
    gs_main = fig.add_gridspec(
        3, 3,
        width_ratios=[1.0, 1.0, 1.0],
        height_ratios=[1.4, 1.4, 0.7]
    )
    fig.set_constrained_layout_pads(w_pad=0.02, h_pad=0.02, wspace=0.02, hspace=0.02)

    # Row 0: all-sky (col 0), map (col 1), AWS panel (col 2)
    ax_allsky = fig.add_subplot(gs_main[0, 0])
    ax_map = fig.add_subplot(gs_main[0, 1], projection=ccrs.NorthPolarStereo())

    # One panel axes for met data (same grid cell as map, but separate column)
    ax_aws_panel = fig.add_subplot(gs_main[0, 2])
    ax_aws_panel.set_facecolor("0.96")
    for spine in ax_aws_panel.spines.values():
        spine.set_color("0.6")
        spine.set_linewidth(0.8)
    ax_aws_panel.set_xticks([])
    ax_aws_panel.set_yticks([])
    ax_aws_panel.set_title("")
    ax_aws_panel.set_zorder(0)

    # Panel coordinate system: top part for text, bottom for windrose
    text_height_frac = 0.6

    # Text axes inside panel (normalized to panel)
    ax_aws_text = ax_aws_panel.inset_axes([0.0, 1 - text_height_frac, 1.0, text_height_frac])
    ax_aws_text.set_facecolor("none")
    ax_aws_text.set_frame_on(False)
    ax_aws_text.set_xticks([])
    ax_aws_text.set_yticks([])
    ax_aws_text.set_zorder(1)

    # Compute windrose rectangle in figure coordinates so it aligns with value boxes
    panel_pos = ax_aws_panel.get_position()
    x_box_panel = 0.45  # same as in text axes
    left = panel_pos.x0 + x_box_panel * panel_pos.width
    right = panel_pos.x1 * 0.98  # small margin on the right
    width = max(0.01, right - left)

    # Vertical placement within panel
    bottom_panel_frac = 0.20
    top_panel_frac = 0.42

    bottom = panel_pos.y0 + bottom_panel_frac * panel_pos.height
    top = panel_pos.y0 + top_panel_frac * panel_pos.height
    height = max(0.01, top - bottom)

    # Windrose axes (figure coordinates)
    ax_aws_wind = WindroseAxes(fig, [left, bottom, width, height])
    fig.add_axes(ax_aws_wind)
    ax_aws_wind.set_facecolor("none")
    ax_aws_wind.set_zorder(1)
    # Enforce meteorological convention at creation (0° at N, clockwise)
    ax_aws_wind.set_theta_zero_location("N")
    ax_aws_wind.set_theta_direction(-1)

    ax_allsky.set_aspect("equal", adjustable="box")
    ax_map.set_aspect("equal", adjustable="box")

    # Row 1: MRR (Ze over VEL) and Skyvue (beta over LDR)
    gs_mid = gs_main[1, :].subgridspec(2, 2)
    ax_ze = fig.add_subplot(gs_mid[0, 0])
    ax_vel = fig.add_subplot(gs_mid[1, 0])
    ax_beta = fig.add_subplot(gs_mid[0, 1])
    ax_depol = fig.add_subplot(gs_mid[1, 1])

    # Row 2: CNR4 spanning all 3 columns
    ax_cnr4 = fig.add_subplot(gs_main[2, :])

    # -------------------
    # All-sky image panel
    # -------------------
    ax_allsky.set_title("ASI-16 all-sky (latest)", fontsize=10)
    ax_allsky.set_xticks([])
    ax_allsky.set_yticks([])

    if asi_path is not None:
        img = plt.imread(asi_path)
        ax_allsky.imshow(img)
    else:
        ax_allsky.text(
            0.5, 0.5,
            "No all-sky image found",
            transform=ax_allsky.transAxes,
            ha="center", va="center"
        )

    # -------------------
    # AWS dashboard: text gauges
    # -------------------
    if aws_time is not None and aws_ds is not None:
        idx = np.where(aws_time <= now)[0]
        if len(idx) == 0:
            latest_t = aws_time.max()
        else:
            latest_t = aws_time[idx[-1]]

        # Extract key variables
        T_air = _get_latest_valid(aws_ds, "TAAVG1M", latest_t)   # °C
        T_dew = _get_latest_valid(aws_ds, "DPAVG1M", latest_t)   # °C
        RH = _get_latest_valid(aws_ds, "RHAVG1M", latest_t)      # %
        T_sea = _get_latest_valid(aws_ds, "TWAVG1M", latest_t)   # °C
        WS = _get_latest_valid(aws_ds, "WSAVG10M", latest_t)     # m s^-1
        WD = _get_latest_valid(aws_ds, "WDAVG10M", latest_t)     # deg

        ax_aws_text.text(
            0.03, 0.95,
            f"{latest_t:%Y-%m-%d %H:%M:%S} UTC",
            transform=ax_aws_text.transAxes,
            ha="left", va="top",
            fontsize=7,
            color="dimgray",
            fontweight="bold",
        )

        entries = [
            ("Air temperature",          T_air, "°C"),
            ("Dew point temperature",    T_dew, "°C"),
            ("Relative humidity",        RH,    "%"),
            ("Sea water temperature",    T_sea, "°C"),
            ("Wind speed",               WS,    "m s$^{-1}$"),
            ("Wind direction",           WD,    "°"),
        ]

        # Layout constants in panel text axes
        y0 = 0.80
        dy = 0.14       # vertical space between entries
        x_label = 0.40  # right-aligned label
        x_box = 0.45    # value box start
        x_unit = 0.68   # unit directly after the box

        box_width_chars = 12  # wider boxes

        for i, (label, value, unit) in enumerate(entries):
            y = y0 - i * dy
            if y < 0.05:
                break

            if value is None or not np.isfinite(value):
                val_num = "--"
            elif label in ("Relative humidity", "Wind direction"):
                val_num = f"{value:.0f}"
            else:
                val_num = f"{value:.1f}"

            val_str = f"{val_num:>{box_width_chars}}"

            # Label
            ax_aws_text.text(
                x_label, y,
                label,
                transform=ax_aws_text.transAxes,
                ha="right", va="center",
                fontsize=7.5,
                color="dimgray",
            )

            # Value box
            ax_aws_text.text(
                x_box, y,
                val_str,
                transform=ax_aws_text.transAxes,
                ha="left", va="center",
                fontsize=9,
                color="black",
                bbox=dict(
                    boxstyle="round,pad=0.25",
                    facecolor="white",
                    edgecolor="0.8",
                    linewidth=0.5,
                ),
            )

            # Unit
            ax_aws_text.text(
                x_unit, y,
                unit,
                transform=ax_aws_text.transAxes,
                ha="left", va="center",
                fontsize=8,
                color="dimgray",
            )
    else:
        ax_aws_text.text(
            0.5, 0.5,
            "No AWS data",
            transform=ax_aws_text.transAxes,
            ha="center", va="center",
            fontsize=9,
            color="dimgray",
        )

    # -------------------
    # AWS windrose: last hour
    # -------------------
    ax_aws_wind.set_title("Wind last 24h", fontsize=8)
    ax_aws_wind.tick_params(labelsize=6)

    if aws_time is not None and aws_ds is not None and "WSAVG10M" in aws_ds and "WDAVG10M" in aws_ds:
        t_start = now - dt.timedelta(hours=24)
        ds_last = aws_ds.sel(time=slice(t_start, now))

        if ds_last.sizes.get("time", 0) > 5:
            ws = ds_last["WSAVG10M"].values
            wd = ds_last["WDAVG10M"].values

            mask = np.isfinite(ws) & np.isfinite(wd)
            ws = ws[mask]
            wd = wd[mask]

            if ws.size > 0:
                ax_aws_wind.clear()
                ax_aws_wind.set_facecolor("none")

                ax_aws_wind.bar(
                    wd, ws,
                    normed=True,
                    opening=0.8,
                    edgecolor="white",
                    cmap=plt.cm.Blues,
                )

                # --- Auto range → snap to nice max → 4 equal intervals ---

                # 1) Get the auto-determined max radius
                raw_max = ax_aws_wind.get_ylim()[1]

                # 2) Snap to next higher multiple of 5 % (and avoid 0)
                max_r = max(5.0, np.ceil(raw_max / 5.0) * 5.0)

                # 3) Define 4 equal intervals from 0 to max_r → 5 tick positions
                #    (0, 1/4, 2/4, 3/4, 4/4 * max_r), round each to nearest 5 %
                ticks = np.linspace(0, max_r, 5)
                ticks = np.array([5.0 * round(t / 5.0) for t in ticks])

                # Make sure ticks are unique and within [0, max_r]
                ticks = np.unique(np.clip(ticks, 0, max_r))

                # 4) Apply range and ticks
                ax_aws_wind.set_ylim(0, max_r)
                ax_aws_wind.set_yticks(ticks)
                ax_aws_wind.set_yticklabels([f"{int(t)}%" for t in ticks], fontsize=4)

                # Keep label angle etc.
                ax_aws_wind.set_rlabel_position(290)


                # Legend more to the right but still inside grey panel
                ax_aws_wind.set_legend(
                    fontsize=3,
                    loc="center left",
                    bbox_to_anchor=(1.6, 0.5),
                )

            else:
                ax_aws_wind.text(
                    0.5, 0.5,
                    "No\nvalid\nwind",
                    transform=ax_aws_wind.transAxes,
                    ha="center", va="center",
                    fontsize=7,
                )
        else:
            ax_aws_wind.text(
                0.5, 0.5,
                "Insufficient\ndata",
                transform=ax_aws_wind.transAxes,
                ha="center", va="center",
                fontsize=7,
            )
    else:
        ax_aws_wind.text(
            0.5, 0.5,
            "No AWS data",
            transform=ax_aws_wind.transAxes,
            ha="center", va="center",
            fontsize=7,
        )

    # -----------
    # Map panel with ship track
    # -----------
    ax_map.set_title("Current ship position", fontsize=10)

    if ship_time is not None:
        min_lat = np.nanmin(ship_lat)
        max_lat = np.nanmax(ship_lat)
        min_lon = np.nanmin(ship_lon)
        max_lon = np.nanmax(ship_lon)

        lat_pad = max(1.0, 0.1 * (max_lat - min_lat + 1e-6))
        lon_pad = max(1.0, 0.1 * (max_lon - min_lon + 1e-6))

        ax_map.set_extent(
            [min_lon - lon_pad, max_lon + lon_pad,
             min_lat - lat_pad, max_lat + lat_pad],
            crs=ccrs.PlateCarree()
        )

        ax_map.add_feature(cfeature.OCEAN, facecolor="lightblue")
        ax_map.add_feature(cfeature.LAND, facecolor="0.9")
        ax_map.add_feature(cfeature.COASTLINE, linewidth=0.5)

        gl = ax_map.gridlines(
            crs=ccrs.PlateCarree(),
            draw_labels=True,
            linewidth=0.5,
            color="0.7",
            alpha=0.5,
            linestyle="--",
        )
        gl.top_labels = False
        gl.right_labels = False
        gl.left_labels = True
        gl.bottom_labels = True
        gl.xlabel_style = {"size": 7, "color": "dimgray"}
        gl.ylabel_style = {"size": 7, "color": "dimgray"}
        gl.xlocator = mticker.FixedLocator(np.arange(-180, 181, 10))
        gl.ylocator = mticker.FixedLocator(np.arange(60, 91, 2))
        gl.xformatter = LONGITUDE_FORMATTER
        gl.yformatter = LATITUDE_FORMATTER

        # Full cruise track
        ax_map.scatter(
            ship_lon, ship_lat,
            s=6, c="0.3", alpha=0.6,
            transform=ccrs.PlateCarree(),
            label="Cruise track"
        )

        # Current window (same day as 'start')
        ship_dates = ship_time.date
        mask_window = (ship_dates == start.date())
        if mask_window.any():
            ax_map.scatter(
                ship_lon[mask_window], ship_lat[mask_window],
                s=6, c="tab:blue", alpha=0.8,
                transform=ccrs.PlateCarree(), zorder=10,
                label="Current window"
            )

        # 00 UTC positions: one per day (deduplicated)
        utc00_by_date = {}
        for t, la, lo in zip(ship_time, ship_lat, ship_lon):
            if t.hour == 0 and t.minute == 0:
                d = t.date()
                if d not in utc00_by_date:
                    utc00_by_date[d] = (lo, la)

        if utc00_by_date:
            dates_sorted = sorted(utc00_by_date.keys())
            utc00_lons = [utc00_by_date[d][0] for d in dates_sorted]
            utc00_lats = [utc00_by_date[d][1] for d in dates_sorted]

            # Scatter all 00 UTC positions
            ax_map.scatter(
                utc00_lons, utc00_lats,
                s=3, c="lightgrey", marker="o",
                transform=ccrs.PlateCarree(),
                label="00 UTC"
            )

            # Base for 5‑day interval: first dataset date
            base_date = ship_time[0].date()

            # Label every 5 days starting from base_date, but only at 00 UTC points
            for d in dates_sorted:
                days_since_base = (d - base_date).days
                if days_since_base > 0 and days_since_base % 5 == 0:
                    lo, la = utc00_by_date[d]
                    # Offset label further so it does not cover the track
                    ax_map.text(
                        lo + 0.5, la + 0.5,
                        d.strftime("%d/%m"),
                        transform=ccrs.PlateCarree(),
                        fontsize=6,
                        color="black",
                        ha="left",
                        va="bottom",
                        bbox=dict(
                            facecolor="white",
                            edgecolor="none",
                            alpha=0.6,
                            pad=0.5
                        ),
                    )

        # Force first label at very first dataset point
        if ship_time is not None and ship_time.size > 0:
            first_t = ship_time[0]
            first_d = first_t.date()
            first_lo = ship_lon[0]
            first_la = ship_lat[0]
            ax_map.text(
                first_lo + 0.5, first_la + 0.5,
                first_d.strftime("%d/%m"),
                transform=ccrs.PlateCarree(),
                fontsize=6,
                color="black",
                ha="left",
                va="bottom",
                bbox=dict(
                    facecolor="white",
                    edgecolor="none",
                    alpha=0.6,
                    pad=0.5
                ),
            )

        # Start and "current" positions
        start_lat = ship_lat[0]
        start_lon = ship_lon[0]
        ax_map.scatter(
            start_lon, start_lat,
            s=40, c="teal", marker="^",
            edgecolor="black",
            transform=ccrs.PlateCarree(),
            label="Longyearbyen", zorder=15
        )

        time_deltas = np.abs(ship_time - now)
        idx_closest = int(np.argmin(time_deltas))
        curr_lat = ship_lat[idx_closest]
        curr_lon = ship_lon[idx_closest]

        ax_map.scatter(
            curr_lon, curr_lat,
            s=30, c="red", marker="o",
            edgecolor="black",
            transform=ccrs.PlateCarree(), zorder=15,
            label="Current"
        )

        ax_map.legend(loc="lower left", fontsize=7)
    else:
        ax_map.set_extent([-30, 40, 70, 85], crs=ccrs.PlateCarree())
        ax_map.add_feature(cfeature.OCEAN, facecolor="lightblue")
        ax_map.add_feature(cfeature.LAND, facecolor="0.9")
        ax_map.add_feature(cfeature.COASTLINE, linewidth=0.5)

        gl = ax_map.gridlines(
            crs=ccrs.PlateCarree(),
            draw_labels=True,
            linewidth=0.5,
            color="0.7",
            alpha=0.5,
            linestyle="--",
        )
        gl.top_labels = False
        gl.right_labels = False
        gl.left_labels = True
        gl.bottom_labels = True
        gl.xlabel_style = {"size": 7, "color": "dimgray"}
        gl.ylabel_style = {"size": 7, "color": "dimgray"}
        gl.xlocator = mticker.FixedLocator(np.arange(-180, 181, 10))
        gl.ylocator = mticker.FixedLocator(np.arange(60, 91, 2))
        gl.xformatter = LONGITUDE_FORMATTER
        gl.yformatter = LATITUDE_FORMATTER

        ax_map.text(
            0.5, 0.5,
            "No ship track data",
            transform=ax_map.transAxes,
            ha="center", va="center",
            fontsize=9,
            bbox=dict(facecolor="white", alpha=0.7, edgecolor="none")
        )

    # -----------------
    # MRR Ze and VEL
    # -----------------
    if mrr_time is not None:
        mrr_times_num = mdates.date2num(mrr_time)
        height_m = mrr_height

        ax_ze.set_title("MRR reflectivity Ze (dBZ)", fontsize=10)
        Z_plot = Ze.transpose("range", "time").values
        im_ze = ax_ze.pcolormesh(
            mrr_times_num, height_m, Z_plot,
            cmap="viridis", vmin=-20, vmax=30, shading="auto"
        )
        shade_missing(ax_ze, mrr_missing, start, end)
        setup_time_axis(ax_ze, start, end)
        set_custom_time_date_ticks(ax_ze, start, end)
        # y-axis labels every 1000 m, grid every 1000 m (major only), darker
        ax_ze.set_yticks(np.arange(0, 4001, 1000))
        ax_ze.grid(True, which="major", axis="y", linestyle="--", alpha=0.6)
        ax_ze.set_ylabel("Height (m)")
        ax_ze.set_ylim(0, 4000)
        
        # Subtle grey shading where no MRR data exist (3200–4000 m)
        ax_ze.axhspan(
            3200, 4000,
            facecolor="0.9",   # light grey
            edgecolor="none",
            alpha=0.7,
            zorder=0.5,
        )
        
        cbar_ze = fig.colorbar(im_ze, ax=ax_ze, pad=0.02, fraction=0.046)
        cbar_ze.set_label("Ze (dBZ)")

        ax_vel.set_title("MRR Doppler velocity (m s$^{-1}$)", fontsize=10)
        V_plot = VEL.transpose("range", "time").values
        # RdBu: red = negative, blue = positive
        im_vel = ax_vel.pcolormesh(
            mrr_times_num, height_m, V_plot,
            cmap="RdBu", vmin=-5, vmax=5, shading="auto"
        )
        shade_missing(ax_vel, mrr_missing, start, end)
        setup_time_axis(ax_vel, start, end)
        set_custom_time_date_ticks(ax_vel, start, end)
        ax_vel.set_yticks(np.arange(0, 4001, 1000))
        ax_vel.grid(True, which="major", axis="y", linestyle="--", alpha=0.6)
        ax_vel.set_ylabel("Height (m)")
        ax_vel.set_ylim(0, 4000)
        cbar_vel = fig.colorbar(im_vel, ax=ax_vel, pad=0.02, fraction=0.046)
        cbar_vel.set_label("VEL (m s$^{-1}$)")
    else:
        ax_ze.text(0.5, 0.5, "No MRR data", transform=ax_ze.transAxes,
                   ha="center", va="center")
        ax_vel.text(0.5, 0.5, "No MRR data", transform=ax_vel.transAxes,
                    ha="center", va="center")

    # -------------------------
    # Skyvue backscatter / depol
    # -------------------------
    if sky_time is not None:
        sky_times_num = mdates.date2num(sky_time)
        rng = sky_height

        ax_beta.set_title("Skyvue total attenuated backscatter", fontsize=10)

        BS = beta_plot.values
        vmin_bs, vmax_bs = 1e-8, 1e-4

        im_beta = ax_beta.pcolormesh(
            sky_times_num, rng, BS.T,
            shading="auto",
            norm=LogNorm(vmin=vmin_bs, vmax=vmax_bs),
            cmap="viridis"
        )
        ax_beta.set_ylabel("Height (m)")
        ax_beta.set_ylim(0, 4000)
        shade_missing(ax_beta, sky_missing, start, end)
        setup_time_axis(ax_beta, start, end)
        set_custom_time_date_ticks(ax_beta, start, end)
        ax_beta.set_yticks(np.arange(0, 4001, 1000))
        ax_beta.grid(True, which="major", axis="y", linestyle="--", alpha=0.6)
        cbar_beta = fig.colorbar(im_beta, ax=ax_beta, pad=0.02, fraction=0.046)
        cbar_beta.set_label(r"$\beta_\mathrm{att}$ (sr$^{-1}$ m$^{-1}$)")

        if cbh is not None:
            cbh_times = cbh["time"].to_index()
            cbh_m = cbh.values
            for layer in range(cbh.shape[1]):
                ax_beta.plot(
                    cbh_times,
                    cbh_m[:, layer],
                    "k.",
                    markersize=2,
                    alpha=0.7
                )

        ax_depol.set_title("Skyvue depolarization ratio (LDR)", fontsize=10)

        LDR = depol_plot.values
        vmin_ldr, vmax_ldr = 0.0, 0.7

        im_depol = ax_depol.pcolormesh(
            sky_times_num, rng, LDR.T,
            shading="auto",
            vmin=vmin_ldr, vmax=vmax_ldr,
            cmap="plasma"
        )
        ax_depol.set_ylabel("Height (m)")
        ax_depol.set_ylim(0, 4000)
        shade_missing(ax_depol, sky_missing, start, end)
        setup_time_axis(ax_depol, start, end)
        set_custom_time_date_ticks(ax_depol, start, end)
        ax_depol.set_yticks(np.arange(0, 4001, 1000))
        ax_depol.grid(True, which="major", axis="y", linestyle="--", alpha=0.6)
        cbar_depol = fig.colorbar(im_depol, ax=ax_depol, pad=0.02, fraction=0.046)
        cbar_depol.set_label("LDR")
    else:
        ax_beta.text(0.5, 0.5, "No Skyvue data", transform=ax_beta.transAxes,
                     ha="center", va="center")
        ax_depol.text(0.5, 0.5, "No Skyvue data", transform=ax_depol.transAxes,
                      ha="center", va="center")

    # --------------
    # CNR4 SW / LW
    # --------------
    ax_cnr4.set_title("CNR4 downward irradiance (SW / LW)", fontsize=10)

    if cnr_time is not None:
        # SW_down in saturated vermillion, LW_down in pure sky blue
        ax_cnr4.plot(cnr_time, sw, label="SW_down", color="#D55E00")
        ax_cnr4.plot(cnr_time, lw, label="LW_down", color="#0072B2")
        shade_missing(ax_cnr4, cnr_missing, start, end)
        setup_time_axis(ax_cnr4, start, end)
        set_custom_time_date_ticks(ax_cnr4, start, end)
        # Darker grid both directions; x is every 4 hours (from setup_time_axis)
        ax_cnr4.grid(True, which="major", linestyle="--", alpha=0.6)
        ax_cnr4.set_ylabel("Irradiance (W m$^{-2}$)")
        ax_cnr4.legend(loc="upper right", fontsize=8)
    else:
        ax_cnr4.text(0.5, 0.5, "No CNR4 data", transform=ax_cnr4.transAxes,
                     ha="center", va="center")

    # Mark current time in time-series panels
    for ax in [ax_ze, ax_vel, ax_beta, ax_depol, ax_cnr4]:
        ax.axvline(now, color="red", linestyle="--", linewidth=1, zorder = 15)
        
    for ax in [ax_ze, ax_vel, ax_beta, ax_depol, ax_cnr4]:
        ax.tick_params(axis="y", labelsize=8)  # or 6, etc.
        
    for ax in [ax_ze, ax_vel, ax_beta, ax_depol, ax_cnr4]:
        ax.grid(True, which="major", linestyle="-", alpha=0.6)



    fig.savefig(out_path, dpi=300)
    plt.close(fig)
