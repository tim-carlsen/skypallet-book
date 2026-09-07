# skypallet_make_latest_quicklook.py

import os
import datetime as dt

from quicklook_core import load_config, create_quicklook_figure

HERE = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
QUICKLOOK_DIR = os.path.join(REPO_ROOT, "quicklooks")
os.makedirs(QUICKLOOK_DIR, exist_ok=True)

def main():
    cfg_path = os.path.join(HERE, "skypallet_config.yml")
    cfg = load_config(cfg_path)

    now = dt.datetime.utcnow()
    start = now - dt.timedelta(hours=24)
    end = now

    out_dir = "live_data"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(QUICKLOOK_DIR, "skypallet_quicklook_latest.png")
    create_quicklook_figure(cfg, start, end, out_path, now=now)

    print("Saved latest quicklook to", out_path)


if __name__ == "__main__":
    main()
