"""Process 8.0 Send Notifications & Reminders (DFD L0)
In : 2.0 Reminder Request, 4.0 Stock Alert Data, 6.0 Rejected Claim Alert
Out: SMS Gateway <- SMS Messages;  SMS Gateway -> Delivery Status;  staff alerts.
Every message is logged in NOTIFICATION (FR-10 'logs every message sent')."""
from flask import Blueprint, jsonify, request

from .auth import current, requires
from .db import db, next_id, now, one, rows

bp = Blueprint("p8", __name__, url_prefix="/api/notifications")


def sms_gateway(phone, text):
    """Stand-in for the external SMS Gateway entity. Returns the Delivery Status flow."""
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return "Delivered" if 9 <= len(digits) <= 12 else "Failed"


def send_sms(patient_id, kind, text):
    p = one("SELECT phone FROM patient WHERE patient_id=?", patient_id)
    status = sms_gateway(p and p["phone"], text)
    db().execute("INSERT INTO notification VALUES (?,?,?,?,?,?,?)",
                 (next_id("notification"), patient_id, current().get("staff_id"), kind, text, status, now()))
    return status


def alert_staff(branch_id, roles, kind, text):
    roles = (roles,) if isinstance(roles, str) else tuple(roles)
    sql = f"SELECT staff_id FROM staff WHERE status='Active' AND role IN ({','.join('?' * len(roles))})"
    args = list(roles)
    if branch_id:
        sql += " AND (branch_id=? OR role='head_office')"
        args.append(branch_id)
    for s in rows(sql, *args):
        db().execute("INSERT INTO notification VALUES (?,?,?,?,?,?,?)",
                     (next_id("notification"), None, s["staff_id"], kind, text, "Unread", now()))


@bp.get("")
@requires("8.0")
def mine():
    me = current()
    alerts = rows("""SELECT * FROM notification WHERE staff_id=? AND patient_id IS NULL ORDER BY sent_at DESC LIMIT 30""",
                  me["staff_id"])
    return jsonify(alerts=alerts, unread=sum(a["delivery_status"] == "Unread" for a in alerts))


@bp.post("/read")
@requires("8.0")
def mark_read():
    db().execute("UPDATE notification SET delivery_status='Read' WHERE staff_id=? AND patient_id IS NULL AND delivery_status='Unread'",
                 (current()["staff_id"],))
    db().commit()
    return jsonify(ok=True)


@bp.get("/sms")
@requires("8.0")
def sms_log():
    """Message log with SMS gateway delivery status."""
    br = request.args.get("branch_id") or current()["branch_id"]
    return jsonify(log=rows("""SELECT n.*, p.full_name, p.phone FROM notification n JOIN patient p USING(patient_id)
                               LEFT JOIN staff s ON s.staff_id=n.staff_id
                               WHERE (s.branch_id=? OR ?='ALL') ORDER BY n.sent_at DESC LIMIT 60""", br,
                            "ALL" if current()["role"] in ("head_office", "admin") else ""))
