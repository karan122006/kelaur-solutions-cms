"""Daily database backup (NFR-6: back up daily, lose at most 24 hours of data).
Uses SQLite's online backup, so it is safe while the clinic is working.
Run by hand:  python -m backend.backup"""
import glob
import os
import sqlite3
import threading
from datetime import datetime

from .db import DB_PATH

KEEP = 14
DIR = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")


def backup_now():
    os.makedirs(DIR, exist_ok=True)
    dest = os.path.join(DIR, f"cms-{datetime.now():%Y%m%d-%H%M%S}.db")
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    for old in sorted(glob.glob(os.path.join(DIR, "cms-*.db")))[:-KEEP]:
        os.remove(old)
    return dest


def _latest_age_hours():
    files = sorted(glob.glob(os.path.join(DIR, "cms-*.db")))
    if not files:
        return 1e9
    return (datetime.now().timestamp() - os.path.getmtime(files[-1])) / 3600


def start_daily():
    """Back up now if the newest copy is older than a day, then check again every hour."""
    def tick():
        try:
            if _latest_age_hours() >= 24:
                backup_now()
        except Exception:
            pass
        t = threading.Timer(3600, tick)
        t.daemon = True
        t.start()
    tick()


if __name__ == "__main__":
    print("Backup written to", backup_now())
