"""Process 2.0 Manage Appointments  (DFD L0 + Level-1 Fig 7.1.1, Rukba Yaseen)
External entities: Receptionist, Patient, Management (branch manager), Doctor/Dentist, Nurse.
Data store: D2 Appointment & Schedule.  Sends Reminder Request to 8.0.
  2.1 Manage Doctor Availability   2.2 Check Slot Availability   2.3 Manage Appointment
  2.4 Send Appointment Notification (via 8.0)   2.5 View Daily Appointment List
  + check-in / queue (L0 flow 'Booking / Check-in Request -> Slot Availability & Queue List')"""
from datetime import datetime, timedelta
import sqlite3

from flask import Blueprint, jsonify, request

from .auth import body, current, requires
from .db import audit, db, next_id, now, one, rows, today
from .p8_notify import send_sms
from .validate import Invalid, must_exist, text, to_date, to_time

bp = Blueprint("p2", __name__, url_prefix="/api")
SLOT_MIN = 20
SERVICE_ROLE = {"General Practice": "General Practice", "Paediatrics": "Paediatrics", "Dental": "Dental"}


# ---------- 2.1 Manage Doctor Availability (Branch Manager -> D2) ----------
@bp.get("/schedules")
@requires("2.0")
def schedules():
    branch = request.args.get("branch_id") or current()["branch_id"]
    start = to_date(request.args.get("from", today()), "Week start")
    end = (datetime.fromisoformat(start) + timedelta(days=6)).strftime("%Y-%m-%d")
    return jsonify(
        staff=rows("""SELECT staff_id, full_name, specialisation FROM staff WHERE branch_id=? AND role IN ('doctor','dentist')
                      AND status='Active' ORDER BY full_name""", branch),
        schedule=rows("""SELECT * FROM staff_schedule WHERE branch_id=? AND work_date BETWEEN ? AND ?""", branch, start, end))


@bp.post("/schedules")
@requires("2.1")
def save_schedule():
    d = body()
    if not text(d.get("staff_id")) or not text(d.get("work_date")):
        return jsonify(error="Choose a doctor and a date."), 422
    d["work_date"] = to_date(d["work_date"], "Work date")
    doc = must_exist("staff", "staff_id", d["staff_id"], "Doctor", 422)
    if doc["role"] not in ("doctor", "dentist"):
        return jsonify(error="Only doctors and dentists have consultation schedules."), 422
    if current()["branch_id"] != doc["branch_id"]:
        return jsonify(error="You can only change schedules for your own branch."), 403
    if d.get("leave_status", "On Duty") not in ("On Duty", "On Leave"):
        return jsonify(error="Status must be On Duty or On Leave."), 422
    if d.get("leave_status", "On Duty") == "On Duty":
        d["start_time"], d["end_time"] = to_time(d.get("start_time"), "Start time"), to_time(d.get("end_time"), "End time")
        if d["start_time"] >= d["end_time"]:
            return jsonify(error="End time must be after start time."), 422
    branch = doc["branch_id"]
    ex = one("SELECT schedule_id FROM staff_schedule WHERE staff_id=? AND work_date=?", d["staff_id"], d["work_date"])
    sid = ex["schedule_id"] if ex else next_id("staff_schedule")
    db().execute("INSERT OR REPLACE INTO staff_schedule VALUES (?,?,?,?,?,?,?)",
                 (sid, d["staff_id"], branch, d["work_date"], d.get("start_time"), d.get("end_time"),
                  d.get("leave_status", "On Duty")))
    clashes = rows("""SELECT appointment_id FROM appointment WHERE staff_id=? AND DATE(appointment_datetime)=?
                      AND status IN ('Booked')""", d["staff_id"], d["work_date"]) if d.get("leave_status") == "On Leave" else []
    audit("SCHEDULE", "staff_schedule", sid)
    db().commit()
    msg = "Schedule saved."
    if clashes:
        msg += f" Note: {len(clashes)} booked appointment(s) on this day need to be rescheduled."
    return jsonify(ok=True, message=msg, schedule_id=sid)


# ---------- 2.2 Check Slot Availability (reads D2) ----------
def free_slots(branch_id, service, day, staff_id=None):
    docs = rows("""SELECT s.staff_id, s.full_name, ss.start_time, ss.end_time FROM staff s
                   JOIN staff_schedule ss ON ss.staff_id=s.staff_id AND ss.work_date=? AND ss.leave_status='On Duty'
                   WHERE s.branch_id=? AND s.specialisation=? AND s.status='Active'""", day, branch_id, service)
    if staff_id:
        docs = [x for x in docs if x["staff_id"] == staff_id]
    booked = {(r["staff_id"], r["appointment_datetime"]) for r in rows(
        """SELECT staff_id, appointment_datetime FROM appointment WHERE branch_id=? AND DATE(appointment_datetime)=?
           AND status NOT IN ('Cancelled','Rescheduled')""", branch_id, day)}
    nowdt = datetime.now()
    out = []
    for d in docs:
        t = datetime.fromisoformat(f"{day}T{d['start_time']}")
        end = datetime.fromisoformat(f"{day}T{d['end_time']}")
        slots = []
        while t + timedelta(minutes=SLOT_MIN) <= end:
            key = t.strftime("%Y-%m-%d %H:%M")
            slots.append({"time": t.strftime("%H:%M"), "datetime": key,
                          "free": (d["staff_id"], key) not in booked and t > nowdt})
            t += timedelta(minutes=SLOT_MIN)
        out.append({"staff_id": d["staff_id"], "doctor": d["full_name"], "slots": slots})
    return out


@bp.get("/slots")
@requires("2.0")
def slots():
    a = request.args
    return jsonify(doctors=free_slots(a.get("branch_id") or current()["branch_id"], a.get("service", "General Practice"),
                                      to_date(a.get("date", today())), a.get("staff_id")))


# ---------- 2.3 Manage Appointment (book / reschedule / cancel / walk-in) ----------
def _insert_appt(d, booking_type):
    aid = next_id("appointment")
    db().execute("INSERT INTO appointment VALUES (?,?,?,?,?,?,?,?)",
                 (aid, d["patient_id"], d["staff_id"], d["branch_id"], d["service_type"],
                  d["appointment_datetime"], booking_type, "Booked"))
    return aid


def _notify(aid, kind):
    """2.4 Send Appointment Notification -> Reminder Request to 8.0 / SMS Gateway"""
    a = one("""SELECT a.*, p.full_name, s.full_name AS doctor, b.branch_name FROM appointment a JOIN patient p USING(patient_id)
               JOIN staff s ON s.staff_id=a.staff_id JOIN branch b ON b.branch_id=a.branch_id WHERE appointment_id=?""", aid)
    when = datetime.fromisoformat(a["appointment_datetime"]).strftime("%a %d %b, %I:%M %p")
    text = {"Appointment Confirmation": f"SFC: {a['full_name']}, your {a['service_type']} appointment with {a['doctor']} at "
                                        f"{a['branch_name']} is confirmed for {when}. Ref {aid}.",
            "Cancellation": f"SFC: your appointment {aid} on {when} has been cancelled. Call us to rebook.",
            "Reminder": f"SFC reminder: {a['service_type']} with {a['doctor']} tomorrow, {when}, {a['branch_name']}."}[kind]
    send_sms(a["patient_id"], kind, text)


@bp.post("/appointments")
@requires("2.0w")
def book():
    d = body()
    me = current()
    d["branch_id"] = text(d.get("branch_id")) or me["branch_id"]
    for f in ("patient_id", "staff_id", "service_type", "appointment_datetime"):
        if not text(d.get(f)):
            return jsonify(error="Choose a patient, a service and a free time slot."), 422
    must_exist("patient", "patient_id", d["patient_id"], "Patient", 422)
    if d.get("reschedule_of"):
        old = must_exist("appointment", "appointment_id", text(d["reschedule_of"]), "Appointment to reschedule", 422)
        if old["status"] != "Booked" or old["patient_id"] != d["patient_id"]:
            return jsonify(error="Only a booked appointment of the same patient can be rescheduled."), 409
    day = to_date(d["appointment_datetime"][:10], "Appointment date")
    ok = any(s["datetime"] == d["appointment_datetime"] and s["free"]
             for doc in free_slots(d["branch_id"], d["service_type"], day, d["staff_id"]) for s in doc["slots"])
    if not ok:
        return jsonify(error="That slot has just been taken or the doctor is not available. Please pick another."), 409
    try:
        if d.get("reschedule_of"):
            db().execute("UPDATE appointment SET status='Rescheduled' WHERE appointment_id=?", (d["reschedule_of"],))
        aid = _insert_appt(d, d.get("booking_type", "Phone"))
    except sqlite3.IntegrityError:
        return jsonify(error="Double booking blocked: this doctor already has a patient in that slot."), 409
    audit("RESCHEDULE" if d.get("reschedule_of") else "BOOK", "appointment", aid)
    _notify(aid, "Appointment Confirmation")
    db().commit()
    return jsonify(ok=True, appointment_id=aid, message="Appointment confirmed. SMS sent to patient.")


@bp.post("/appointments/<aid>/cancel")
@requires("2.0w")
def cancel(aid):
    a = must_exist("appointment", "appointment_id", aid, "Appointment")
    if a["status"] != "Booked":
        return jsonify(error=f"Only booked appointments can be cancelled (this one is {a['status']})."), 409
    db().execute("UPDATE appointment SET status='Cancelled' WHERE appointment_id=? AND status='Booked'", (aid,))
    audit("CANCEL", "appointment", aid)
    _notify(aid, "Cancellation")
    db().commit()
    return jsonify(ok=True, message="Appointment cancelled and patient notified.")


@bp.post("/walkin")
@requires("2.0w")
def walk_in():
    """Registers a walk-in into today's schedule at the first free slot, then checks the patient in."""
    d = body()
    me = current()
    branch = me["branch_id"]
    nowdt = datetime.now()
    if not text(d.get("patient_id")):
        return jsonify(error="Find the patient first."), 422
    must_exist("patient", "patient_id", d["patient_id"], "Patient", 422)
    if d.get("service_type", "General Practice") not in SERVICE_ROLE:
        return jsonify(error="Unknown service."), 422
    if one("""SELECT 1 FROM queue_entry q JOIN appointment a USING(appointment_id) WHERE a.patient_id=? AND a.branch_id=?
              AND DATE(q.check_in_time)=? AND q.queue_status<>'Done'""", d["patient_id"], branch, today()):
        return jsonify(error="This patient is already in today's queue."), 409
    best = None
    for doc in free_slots(branch, d.get("service_type", "General Practice"), today(), d.get("staff_id")):
        for s in doc["slots"]:
            if s["free"] and (best is None or s["datetime"] < best[1]):
                best = (doc["staff_id"], s["datetime"])
                break
    if not best:
        # past clinic hours / fully booked: queue against the earliest on-duty doctor at the current time
        doc = one("""SELECT s.staff_id FROM staff s JOIN staff_schedule ss ON ss.staff_id=s.staff_id AND ss.work_date=?
                     WHERE s.branch_id=? AND s.specialisation=? AND ss.leave_status='On Duty' LIMIT 1""",
                  today(), branch, d.get("service_type", "General Practice"))
        if not doc:
            return jsonify(error="No doctor for this service is on duty today."), 409
        t = nowdt
        while one("SELECT 1 FROM appointment WHERE staff_id=? AND appointment_datetime=?", doc["staff_id"],
                  t.strftime("%Y-%m-%d %H:%M:%S")):
            t += timedelta(seconds=1)   # two walk-ins in the same second must not clash
        best = (doc["staff_id"], t.strftime("%Y-%m-%d %H:%M:%S"))
    aid = _insert_appt({"patient_id": d["patient_id"], "staff_id": best[0], "branch_id": branch,
                        "service_type": d.get("service_type", "General Practice"), "appointment_datetime": best[1]}, "Walk-in")
    q = _check_in(aid)
    audit("WALK-IN", "appointment", aid)
    db().commit()
    return jsonify(ok=True, appointment_id=aid, queue=q, message=f"Walk-in registered. Queue number {q['queue_no']}.")


# ---------- Check-in & queue ----------
def _check_in(aid):
    a = one("SELECT * FROM appointment WHERE appointment_id=?", aid)
    prefix = "W" if a["booking_type"] == "Walk-in" else "A"
    n = one("""SELECT COUNT(*) n FROM queue_entry q JOIN appointment a USING(appointment_id)
               WHERE a.branch_id=? AND DATE(q.check_in_time)=?""", a["branch_id"], today())["n"] + 1
    qid = next_id("queue_entry")
    qno = f"{prefix}{n:03d}"
    db().execute("INSERT INTO queue_entry VALUES (?,?,?,?,?)", (qid, aid, qno, now(), "Waiting"))
    db().execute("UPDATE appointment SET status='Checked-in' WHERE appointment_id=?", (aid,))
    return {"queue_id": qid, "queue_no": qno}


@bp.post("/appointments/<aid>/checkin")
@requires("2.0w")
def check_in(aid):
    a = must_exist("appointment", "appointment_id", aid, "Appointment")
    if one("SELECT 1 FROM queue_entry WHERE appointment_id=?", aid):
        return jsonify(error="Patient is already checked in."), 409
    if a["status"] != "Booked":
        return jsonify(error=f"This appointment is {a['status']} and cannot be checked in."), 409
    q = _check_in(aid)
    audit("CHECK-IN", "queue_entry", q["queue_id"])
    db().commit()
    return jsonify(ok=True, queue=q, message=f"Checked in. Queue number {q['queue_no']}.")


@bp.get("/queue")
@requires("2.0")
def queue():
    """Queue list for staff with estimated waiting time (FR-03)."""
    branch = request.args.get("branch_id") or current()["branch_id"]
    q = rows("""SELECT q.*, a.appointment_id, a.service_type, a.booking_type, a.appointment_datetime, p.patient_id,
                p.full_name, p.allergies, s.full_name AS doctor, a.staff_id FROM queue_entry q JOIN appointment a USING(appointment_id)
                JOIN patient p ON p.patient_id=a.patient_id JOIN staff s ON s.staff_id=a.staff_id
                WHERE a.branch_id=? AND DATE(q.check_in_time)=? ORDER BY q.check_in_time""", branch, today())
    waiting_by_doc = {}
    for r in q:
        if r["queue_status"] in ("Waiting", "Vitals Taken"):
            waiting_by_doc[r["staff_id"]] = waiting_by_doc.get(r["staff_id"], 0) + 1
            r["est_wait_min"] = (waiting_by_doc[r["staff_id"]] - 1) * 12
    return jsonify(queue=q)


# ---------- 2.5 View Daily Appointment List ----------
@bp.get("/appointments")
@requires("2.0")
def daily():
    me = current()
    branch = request.args.get("branch_id") or me["branch_id"]
    day = to_date(request.args.get("date", today()))
    sql = """SELECT a.*, p.full_name, p.phone, s.full_name AS doctor, q.queue_no, q.queue_status FROM appointment a
             JOIN patient p USING(patient_id) JOIN staff s ON s.staff_id=a.staff_id
             LEFT JOIN queue_entry q ON q.appointment_id=a.appointment_id
             WHERE a.branch_id=? AND DATE(a.appointment_datetime)=?"""
    args = [branch, day]
    if me["role"] in ("doctor", "dentist"):
        sql += " AND a.staff_id=?"
        args.append(me["staff_id"])
    return jsonify(appointments=rows(sql + " ORDER BY a.appointment_datetime", *args))


@bp.post("/reminders/run")
@requires("2.0w")
def run_reminders():
    """2.4 batch: reminders for tomorrow's bookings (normally run by a nightly job)."""
    tmr = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    ids = [r["appointment_id"] for r in rows("""SELECT appointment_id FROM appointment WHERE DATE(appointment_datetime)=?
                                                 AND status='Booked' AND branch_id=?""", tmr, current()["branch_id"])]
    for aid in ids:
        _notify(aid, "Reminder")
    db().commit()
    return jsonify(ok=True, message=f"{len(ids)} reminder SMS sent for tomorrow.")
