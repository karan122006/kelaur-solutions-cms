"""Process 7.0 Generate Reports & Dashboard (DFD L0)
In : Management -> Report Request;  D2 -> Appointment Data;  D4 -> Stock Data;  D5 -> Revenue Data;  D6 -> Claim Data
Out: Management <- Dashboard & Reports  (filter by branch, date, service; export to Excel (CSV) / PDF (print))"""
import csv
import io
from datetime import datetime, timedelta

from flask import Blueprint, Response, jsonify, request

from .auth import current, requires
from .db import audit, db, rows, today
from .validate import Invalid, to_date

bp = Blueprint("p7", __name__, url_prefix="/api/reports")


def _filters():
    a = request.args
    me = current()
    if me["role"] == "head_office":
        branch = a.get("branch_id") or None
        if branch == "ALL":
            branch = None
    else:
        branch = me["branch_id"]       # branch managers only ever see their own branch
    start = to_date(a.get("from") or (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d"), "From date")
    end = to_date(a.get("to") or today(), "To date")
    if start > end:
        raise Invalid("The From date must be on or before the To date.")
    return branch, start, end, a.get("service") or None


def _w(alias_branch, branch, service=None, alias_service=None):
    sql, args = "", []
    if branch:
        sql += f" AND {alias_branch}=?"
        args.append(branch)
    if service and alias_service:
        sql += f" AND {alias_service}=?"
        args.append(service)
    return sql, args


@bp.get("/dashboard")
@requires("7.0")
def dashboard():
    branch, start, end, service = _filters()
    wb, ab = _w("b.branch_id", branch)
    wa, aa = _w("a.branch_id", branch, service, "a.service_type")
    rng = [start, end]
    revenue = rows(f"""SELECT COALESCE(SUM(y.amount),0) cash FROM payment y JOIN bill b USING(bill_id)
                       WHERE DATE(y.payment_date) BETWEEN ? AND ? {wb}""", *rng, *ab)[0]["cash"]
    billed = rows(f"""SELECT COALESCE(SUM(total_amount),0) t, COUNT(*) n, COALESCE(SUM(outstanding_balance),0) o
                      FROM bill b WHERE DATE(bill_date) BETWEEN ? AND ? {wb}""", *rng, *ab)[0]
    appt = rows(f"""SELECT COUNT(*) total, SUM(status='Completed') done, SUM(status='Cancelled') cancelled,
                    SUM(status='No-show') noshow, SUM(booking_type='Walk-in') walkin, COUNT(DISTINCT patient_id) patients
                    FROM appointment a WHERE DATE(appointment_datetime) BETWEEN ? AND ? {wa}""", *rng, *aa)[0]
    slots = rows(f"""SELECT COALESCE(SUM((strftime('%s','2000-01-01 '||end_time)-strftime('%s','2000-01-01 '||start_time))/1200),0) s
                     FROM staff_schedule ss WHERE leave_status='On Duty' AND work_date BETWEEN ? AND ?
                     {_w('ss.branch_id', branch)[0]}""", *rng, *_w('ss.branch_id', branch)[1])[0]["s"]
    used = (appt["total"] or 0) - (appt["cancelled"] or 0)
    by_day = rows(f"""SELECT DATE(y.payment_date) d, ROUND(SUM(y.amount),2) v FROM payment y JOIN bill b USING(bill_id)
                      WHERE DATE(y.payment_date) BETWEEN ? AND ? {wb} GROUP BY d ORDER BY d""", *rng, *ab)
    by_branch = rows("""SELECT br.branch_id, br.branch_name, ROUND(COALESCE(SUM(b.total_amount),0),2) billed,
                        COUNT(b.bill_id) bills FROM branch br LEFT JOIN bill b ON b.branch_id=br.branch_id
                        AND DATE(b.bill_date) BETWEEN ? AND ? GROUP BY br.branch_id ORDER BY br.branch_id""", *rng)
    by_service = rows(f"""SELECT service_type k, COUNT(*) v FROM appointment a WHERE DATE(appointment_datetime) BETWEEN ? AND ?
                          AND status<>'Cancelled' {wa} GROUP BY service_type ORDER BY v DESC""", *rng, *aa)
    workload = rows(f"""SELECT s.full_name k, s.specialisation, COUNT(c.consultation_id) v FROM consultation c
                        JOIN staff s ON s.staff_id=c.staff_id WHERE DATE(c.visit_date) BETWEEN ? AND ? AND c.diagnosis IS NOT NULL
                        {_w('s.branch_id', branch)[0]} GROUP BY s.staff_id ORDER BY v DESC LIMIT 8""",
                    *rng, *_w('s.branch_id', branch)[1])
    claims = rows(f"""SELECT claim_status k, COUNT(*) v, ROUND(SUM(amount_claimed),2) amt FROM claim c JOIN bill b USING(bill_id)
                      WHERE 1=1 {wb} GROUP BY claim_status""", *ab)
    soon = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
    stock = rows(f"""SELECT br.branch_name, m.medication_name, m.reorder_level, COALESCE(SUM(CASE WHEN sb.expiry_date>=? THEN
                     sb.quantity_on_hand END),0) qty, COALESCE(SUM(CASE WHEN sb.expiry_date BETWEEN ? AND ? THEN sb.quantity_on_hand END),0) near
                     FROM medication m CROSS JOIN branch br LEFT JOIN stock_batch sb ON sb.medication_id=m.medication_id
                     AND sb.branch_id=br.branch_id WHERE 1=1 {_w('br.branch_id', branch)[0]}
                     GROUP BY m.medication_id, br.branch_id HAVING qty<=m.reorder_level OR near>0 ORDER BY qty""",
                 today(), today(), soon, *_w('br.branch_id', branch)[1])
    audit("REPORT dashboard", None, f"{branch or 'ALL'} {start}..{end}")
    db().commit()
    return jsonify(
        filters={"branch_id": branch or "ALL", "from": start, "to": end, "service": service},
        kpi={"collected": round(revenue, 2), "billed": round(billed["t"], 2), "bills": billed["n"],
             "outstanding": round(billed["o"], 2), "appointments": appt["total"] or 0, "patients": appt["patients"] or 0,
             "walkins": appt["walkin"] or 0, "cancelled": appt["cancelled"] or 0,
             "utilisation": round(100 * used / slots, 1) if slots else 0,
             "low_stock": sum(1 for s in stock if s["qty"] <= s["reorder_level"]),
             "near_expiry": sum(1 for s in stock if s["near"] > 0),
             "claims_open": sum(c["v"] for c in claims if c["k"] in ("Draft", "Submitted")),
             "claims_rejected": sum(c["v"] for c in claims if c["k"] == "Rejected")},
        by_day=by_day, by_branch=by_branch, by_service=by_service, workload=workload, claims=claims, stock=stock[:12],
        branches=rows("SELECT branch_id, branch_name FROM branch ORDER BY branch_id"))


EXPORTS = {
    "revenue": ("""SELECT b.bill_id, DATE(b.bill_date) bill_date, br.branch_name, p.full_name patient, b.payer_type, b.total_amount,
                   b.amount_paid, b.outstanding_balance, b.bill_status FROM bill b JOIN branch br USING(branch_id)
                   JOIN patient p USING(patient_id) WHERE DATE(b.bill_date) BETWEEN ? AND ? {b} ORDER BY b.bill_date""", "b.branch_id"),
    "appointments": ("""SELECT a.appointment_id, a.appointment_datetime, br.branch_name, a.service_type, s.full_name doctor,
                        p.full_name patient, a.booking_type, a.status FROM appointment a JOIN branch br USING(branch_id)
                        JOIN staff s ON s.staff_id=a.staff_id JOIN patient p ON p.patient_id=a.patient_id
                        WHERE DATE(a.appointment_datetime) BETWEEN ? AND ? {b} ORDER BY a.appointment_datetime""", "a.branch_id"),
    "claims": ("""SELECT c.claim_id, c.bill_id, pp.provider_name, br.branch_name, c.claim_status, c.amount_claimed, c.amount_approved,
                  c.submitted_date FROM claim c JOIN bill b USING(bill_id) JOIN branch br ON br.branch_id=b.branch_id
                  JOIN panel_provider pp ON pp.provider_id=c.provider_id WHERE DATE(b.bill_date) BETWEEN ? AND ? {b}""", "b.branch_id"),
    "stock": ("""SELECT br.branch_name, m.medication_name, sb.batch_no, sb.expiry_date, sb.quantity_on_hand, m.reorder_level
                 FROM stock_batch sb JOIN medication m USING(medication_id) JOIN branch br ON br.branch_id=sb.branch_id
                 WHERE sb.quantity_on_hand>0 AND ? <= ? {b} ORDER BY br.branch_name, m.medication_name""", "sb.branch_id"),
    "patients": ("""SELECT p.patient_id, p.full_name, p.gender, p.date_of_birth, br.branch_name registered_branch, p.registration_date
                    FROM patient p JOIN branch br ON br.branch_id=p.registered_branch_id
                    WHERE DATE(p.registration_date) BETWEEN ? AND ? {b} ORDER BY p.registration_date""", "p.registered_branch_id"),
}


@bp.get("/export/<kind>")
@requires("7.0")
def export(kind):
    if kind not in EXPORTS:
        return jsonify(error="Unknown report."), 404
    branch, start, end, _ = _filters()
    sql, col = EXPORTS[kind]
    sql = sql.format(b=f" AND {col}=?" if branch else "")
    data = rows(sql, start, end, *([branch] if branch else []))
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel opens UTF-8 correctly
    w = csv.writer(buf)
    w.writerow([f"Sunrise Family Clinics - {kind.title()} report", f"Branch: {branch or 'All branches'}", f"{start} to {end}"])
    if data:
        w.writerow(data[0].keys())
        w.writerows([r.values() for r in data])
    audit(f"EXPORT {kind}", None, branch or "ALL")
    db().commit()
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=SFC_{kind}_{start}_{end}.csv"})
