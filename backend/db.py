"""Database helpers: one shared SQLite file = the single central database
required by SRS 5.3.2 ("one shared database for all five branches")."""
import os
import sqlite3
from datetime import datetime

from flask import g, session

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CMS_DB", os.path.join(BASE, "..", "data", "cms.db"))

# Prefix used for each generated primary key (e.g. PT0000123 as in the D1 dictionary)
PREFIX = {
    "patient": ("patient_id", "PT"), "patient_coverage": ("coverage_id", "CV"),
    "appointment": ("appointment_id", "AP"), "queue_entry": ("queue_id", "QE"),
    "consultation": ("consultation_id", "CN"), "prescription": ("prescription_id", "RX"),
    "prescription_item": ("item_id", "RI"), "stock_batch": ("batch_id", "SB"),
    "stock_transfer": ("transfer_id", "TR"), "bill": ("bill_id", "BL"),
    "bill_item": ("bill_item_id", "BI"), "payment": ("payment_id", "PY"),
    "claim": ("claim_id", "CL"), "notification": ("notification_id", "NT"),
    "staff_schedule": ("schedule_id", "SS"), "staff": ("staff_id", "ST"),
    "user_account": ("user_id", "US"), "medication": ("medication_id", "MD"),
    "panel_provider": ("provider_id", "PP"), "supplier": ("supplier_id", "SP"),
}


def connect(path=DB_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, detect_types=0, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close(_=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.now().strftime("%Y-%m-%d")


def rows(sql, *args):
    return [dict(r) for r in db().execute(sql, args).fetchall()]


def one(sql, *args):
    r = db().execute(sql, args).fetchone()
    return dict(r) if r else None


def next_id(table, con=None):
    con = con or db()
    col, pre = PREFIX[table]
    r = con.execute(
        f"SELECT MAX(CAST(SUBSTR({col}, 3) AS INTEGER)) FROM {table} WHERE {col} LIKE ?", (pre + "%",)
    ).fetchone()[0]
    return f"{pre}{(r or 0) + 1:07d}"


def audit(action, table=None, record=None):
    """FR-11 / SRS 5.3.4: log every access to or change in a record (D7)."""
    db().execute(
        "INSERT INTO audit_log(user_id, action, table_affected, record_id, logged_at) VALUES (?,?,?,?,?)",
        (session.get("user_id"), action, table, record, now()),
    )


def migrate():
    """Bring an older database up to date without losing data."""
    con = connect(DB_PATH)
    cols = [r[1] for r in con.execute("PRAGMA table_info(user_account)")]
    if "must_change_password" not in cols:
        con.execute("ALTER TABLE user_account ADD COLUMN must_change_password INTEGER DEFAULT 0")
    con.execute("CREATE INDEX IF NOT EXISTS ix_patient_name ON patient(full_name)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_patient_phone ON patient(phone)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_appt_branch_dt ON appointment(branch_id, appointment_datetime)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_consult_patient ON consultation(patient_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_bill_branch_date ON bill(branch_id, bill_date)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_payment_bill ON payment(bill_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_notif_staff ON notification(staff_id, sent_at)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_audit_user ON audit_log(user_id)")
    con.commit()
    con.close()
