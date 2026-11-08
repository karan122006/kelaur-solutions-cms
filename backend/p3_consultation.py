"""Process 3.0 Manage Consultation & Medical Records (DFD L0)
In : Nurse  -> Vital Signs & Queue Status Update      Doctor/Dentist -> Consultation Notes & Prescription Order
Out: Nurse  <- Patient Details, Allergies & Queue List Doctor/Dentist <- Medical History & Appointment List
Stores: reads D1 (Patient Details & Allergies), reads D2 (Queue & Appointment list),
        writes/reads D3 (Consultation & Prescription Data, Visit History)."""
import json

from flask import Blueprint, jsonify, request

from .auth import body, current, requires
from .db import audit, db, next_id, now, one, rows, today
from .p8_notify import alert_staff
from .clinical import allergy_conflicts
from .validate import Invalid, must_exist, text, to_date, to_int

bp = Blueprint("p3", __name__, url_prefix="/api/consult")

FEES = {"General Practice": 35.0, "Paediatrics": 40.0, "Dental": 60.0}
PROCEDURES = [  # price list used by the consultation screen (bill lines)
    {"item_type": "Procedure", "description": "Wound dressing", "unit_price": 25},
    {"item_type": "Procedure", "description": "Nebuliser treatment", "unit_price": 30},
    {"item_type": "Procedure", "description": "Blood glucose test", "unit_price": 10},
    {"item_type": "Vaccine", "description": "Influenza vaccine", "unit_price": 75},
    {"item_type": "Vaccine", "description": "MMR vaccine (child)", "unit_price": 65},
    {"item_type": "Dental", "description": "Scaling & polishing", "unit_price": 90},
    {"item_type": "Dental", "description": "Tooth filling (composite)", "unit_price": 120},
    {"item_type": "Dental", "description": "Simple extraction", "unit_price": 100},
]


@bp.get("/queue")
@requires("3.0")
def queue_list():
    me = current()
    sql = """SELECT q.queue_id, q.queue_no, q.queue_status, q.check_in_time, a.service_type, a.appointment_datetime,
             p.patient_id, p.full_name, p.date_of_birth, p.gender, p.allergies, s.full_name AS doctor, c.vitals
             FROM queue_entry q JOIN appointment a USING(appointment_id) JOIN patient p ON p.patient_id=a.patient_id
             JOIN staff s ON s.staff_id=a.staff_id LEFT JOIN consultation c ON c.queue_id=q.queue_id
             WHERE a.branch_id=? AND DATE(q.check_in_time)=?"""
    args = [me["branch_id"], today()]
    if me["role"] in ("doctor", "dentist"):
        sql += " AND a.staff_id=?"
        args.append(me["staff_id"])
    return jsonify(queue=rows(sql + " ORDER BY q.check_in_time", *args), procedures=PROCEDURES)


def _draft(queue_id):
    must_exist("queue_entry", "queue_id", queue_id, "Queue entry")
    c = one("SELECT * FROM consultation WHERE queue_id=?", queue_id)
    if c:
        return c
    q = one("""SELECT a.patient_id, a.staff_id FROM queue_entry q JOIN appointment a USING(appointment_id)
               WHERE q.queue_id=?""", queue_id)
    cid = next_id("consultation")
    db().execute("INSERT INTO consultation(consultation_id, queue_id, patient_id, staff_id, visit_date) VALUES (?,?,?,?,?)",
                 (cid, queue_id, q["patient_id"], q["staff_id"], now()))
    return one("SELECT * FROM consultation WHERE consultation_id=?", cid)


@bp.post("/<queue_id>/vitals")
@requires("3.0")
def vitals(queue_id):
    """Nurse: Vital Signs & Queue Status Update -> D3 / D2"""
    v = body()
    v = {k: v.get(k) for k in ("temp", "bp", "pulse", "weight")}
    try:
        if isinstance(v["temp"], (list, dict, bool)) or not 30 <= float(v["temp"]) <= 45:
            raise ValueError
        sys_, dia = [int(x) for x in str(v.get("bp", "")).split("/")]
        if not (60 <= sys_ <= 260 and 30 <= dia <= 160):
            raise ValueError
        for k, lo, hi in (("pulse", 20, 250), ("weight", 0.5, 300)):
            if v[k] not in (None, ""):
                if isinstance(v[k], (list, dict, bool)) or not lo <= float(v[k]) <= hi:
                    raise ValueError
    except (ValueError, TypeError):
        return jsonify(error="Check the readings: temperature 30–45 °C, blood pressure like 120/80, pulse 20–250, weight 0.5–300 kg."), 422
    c = _draft(queue_id)
    db().execute("UPDATE consultation SET vitals=? WHERE consultation_id=?", (json.dumps(v), c["consultation_id"]))
    db().execute("UPDATE queue_entry SET queue_status='Vitals Taken' WHERE queue_id=?", (queue_id,))
    audit("VITALS", "consultation", c["consultation_id"])
    db().commit()
    return jsonify(ok=True, message="Vitals saved. Patient moved to 'Vitals Taken'.")


@bp.post("/<queue_id>/status")
@requires("3.0")
def status(queue_id):
    must_exist("queue_entry", "queue_id", queue_id, "Queue entry")
    s = body().get("status")
    if not isinstance(s, str) or s not in ("Waiting", "Vitals Taken", "In Consultation", "At Pharmacy", "Paying", "Done"):
        return jsonify(error="Unknown status."), 422
    db().execute("UPDATE queue_entry SET queue_status=? WHERE queue_id=?", (s, queue_id))
    db().commit()
    return jsonify(ok=True)


@bp.get("/<queue_id>")
@requires("3.0")
def open_visit(queue_id):
    """Medical History & Appointment List to Doctor (reads D1 + D3 across all branches)."""
    must_exist("queue_entry", "queue_id", queue_id, "Queue entry")
    q = one("""SELECT q.*, a.service_type, a.patient_id FROM queue_entry q JOIN appointment a USING(appointment_id)
               WHERE q.queue_id=?""", queue_id)
    p = one("SELECT * FROM patient WHERE patient_id=?", q["patient_id"])
    c = _draft(queue_id)
    hist = rows("""SELECT c.visit_date, c.symptoms, c.diagnosis, c.treatment, c.vitals, s.full_name AS doctor,
                   s.specialisation, b.branch_name FROM consultation c JOIN staff s ON s.staff_id=c.staff_id
                   JOIN branch b ON b.branch_id=s.branch_id WHERE c.patient_id=? AND c.consultation_id<>? AND c.diagnosis IS NOT NULL
                   ORDER BY c.visit_date DESC""", q["patient_id"], c["consultation_id"])
    meds = rows("SELECT medication_id, medication_name, unit, unit_price FROM medication ORDER BY medication_name")
    if q["queue_status"] in ("Waiting", "Vitals Taken") and current()["role"] in ("doctor", "dentist"):
        db().execute("UPDATE queue_entry SET queue_status='In Consultation' WHERE queue_id=?", (queue_id,))
    audit("VIEW", "consultation", c["consultation_id"])
    db().commit()
    c["vitals"] = json.loads(c["vitals"]) if c.get("vitals") else None
    for h in hist:
        h["vitals"] = json.loads(h["vitals"]) if h.get("vitals") else None
    return jsonify(queue=q, patient=p, consultation=c, history=hist, medications=meds, procedures=PROCEDURES,
                   fee=FEES.get(q["service_type"], 35.0))


@bp.post("/<queue_id>/complete")
@requires("3.0w")
def complete(queue_id):
    """Consultation Notes & Prescription Order -> D3 (Consultation & Prescription Data)"""
    d = body()
    must_exist("queue_entry", "queue_id", queue_id, "Queue entry")
    if not text(d.get("diagnosis")):
        return jsonify(error="Diagnosis is required before the visit can be completed.", fields={"diagnosis": "Required"}), 422
    q = one("""SELECT q.*, a.service_type, a.appointment_id, a.patient_id, a.branch_id FROM queue_entry q
               JOIN appointment a USING(appointment_id) WHERE q.queue_id=?""", queue_id)
    if one("SELECT 1 FROM consultation WHERE queue_id=? AND diagnosis IS NOT NULL", queue_id):
        return jsonify(error="This visit has already been completed."), 409
    p = one("SELECT allergies FROM patient WHERE patient_id=?", q["patient_id"])
    c = _draft(queue_id)
    raw = d.get("prescription") if isinstance(d.get("prescription"), list) else []
    items = []
    for i in raw:
        if not isinstance(i, dict) or not i.get("medication_id"):
            continue
        must_exist("medication", "medication_id", text(i["medication_id"]), "Medicine", 422)
        qty = to_int(i.get("quantity"), "Medicine quantity", 1, 1000)
        items.append({"medication_id": i["medication_id"], "dosage": text(i.get("dosage"))[:120], "quantity": qty})
    procs = [x for x in d.get("procedures", []) if isinstance(x, str)] if isinstance(d.get("procedures"), list) else []
    follow = to_date(d["follow_up_date"], "Follow-up date") if text(d.get("follow_up_date")) else None
    # allergy check at the point of prescribing (name or drug class)
    names = [one("SELECT medication_name FROM medication WHERE medication_id=?", i["medication_id"])["medication_name"] for i in items]
    hits = allergy_conflicts(p["allergies"], names)
    if hits and not d.get("override_allergy"):
        return jsonify(error=f"Allergy alert: patient is allergic to {p['allergies']}. {', '.join(hits)} may cause a reaction.",
                       allergy=True), 409
    if hits:
        audit("ALLERGY OVERRIDE " + ", ".join(hits), "consultation", c["consultation_id"])
    charges = [{"item_type": "Consultation", "description": f"{q['service_type']} consultation", "quantity": 1,
                "unit_price": FEES.get(q["service_type"], 35.0)}]
    for pr in procs:
        m = next((x for x in PROCEDURES if x["description"] == pr), None)
        if m:
            charges.append({**m, "quantity": 1})
    db().execute("""UPDATE consultation SET symptoms=?, diagnosis=?, treatment=?, follow_up_date=?, charges=?
                    WHERE consultation_id=?""", (text(d.get("symptoms")), text(d["diagnosis"]), text(d.get("treatment")),
                                                 follow, json.dumps(charges), c["consultation_id"]))
    rx = None
    if items:
        rx = next_id("prescription")
        db().execute("INSERT INTO prescription VALUES (?,?,?,?)", (rx, c["consultation_id"], now(), "Pending"))
        for i in items:
            db().execute("INSERT INTO prescription_item(item_id, prescription_id, medication_id, dosage, quantity) VALUES (?,?,?,?,?)",
                         (next_id("prescription_item"), rx, i["medication_id"], i["dosage"], i["quantity"]))
        alert_staff(q["branch_id"], "pharmacy", "Prescription Waiting", f"New prescription {rx} waiting at the counter.")
    db().execute("UPDATE queue_entry SET queue_status=? WHERE queue_id=?", ("At Pharmacy" if rx else "Paying", queue_id))
    db().execute("UPDATE appointment SET status='Completed' WHERE appointment_id=?", (q["appointment_id"],))
    audit("COMPLETE", "consultation", c["consultation_id"])
    db().commit()
    return jsonify(ok=True, consultation_id=c["consultation_id"], prescription_id=rx,
                   message="Visit saved." + (f" Prescription {rx} sent to pharmacy." if rx else " Patient sent to billing."))
