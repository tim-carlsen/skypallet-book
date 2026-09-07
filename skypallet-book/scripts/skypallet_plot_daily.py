# skypallet_plot_daily.py

import os
import sys
import datetime as dt

from quicklook_core import load_config, create_quicklook_figure

HERE = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
ARCHIVE_DIR = os.path.join(REPO_ROOT, "quicklooks", "archive")
os.makedirs(ARCHIVE_DIR, exist_ok=True)

def parse_date_arg():
    """
    Parse optional date argument from sys.argv[1].
    Format: YYYY-MM-DD (UTC).
    Default: yesterday (UTC).
    """
    if len(sys.argv) < 2:
        today = dt.datetime.utcnow().date()
        return today - dt.timedelta(days=1)
    arg = sys.argv[1]
    try:
        return dt.datetime.strptime(arg, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit(
            f"Could not parse date from '{arg}'. "
            "Expected YYYY-MM-DD, e.g. 2026-08-17"
        )


def main():
    cfg_path = os.path.join(HERE, "skypallet_config_mac.yml")
    cfg = load_config(cfg_path)

    # Use the CLI argument or default to yesterday
    target_date = parse_date_arg()

    start = dt.datetime(target_date.year, target_date.month, target_date.day, 0, 0)
    end = start + dt.timedelta(days=1)

    date_str = target_date.strftime("%Y%m%d")
    out_path = os.path.join(ARCHIVE_DIR, f"{date_str}_skypallet_quicklook.png")

    create_quicklook_figure(cfg, start, end, out_path, now=end)
    print("Saved daily quicklook to", out_path)



if __name__ == "__main__":
    main()
