"""Process 1.0 Manage Patient Registration & Records  (DFD L0 + Level-1 Fig 6.5)
External entities: Patient, Receptionist.   Data store: D1 Patient Records.
Sub-processes 1.1 - 1.5 are implemented as the functions below."""
import re
from datetime import date

from flask import Blueprint, jsonify, request

from .auth import body, current, requires
from .db import audit, db, next_id, now, one, rows
from .validate import must_exist, text
from .p8_notify import send_sms

bp = Blueprint("p1", __name__, url_prefix="/api/patients")

MANDATORY = ["full_name", "ic_passport_no", "date_of_birth", "gender", "phone", "emergency_contact", "allergies"]


def capture_validate(d):
    """1.1 Capture & Validate Registration Details -> Validated Registration Data | Validation Error"""
    fields = MANDATORY + ["address", "provider_id", "policy_no", "valid_until"]
    v = {k: text(d.get(k)) for k in fields}      # anything that is not text counts as missing
    v["confirm_possible_duplicate"] = d.get("confirm_possible_duplicate") is True
    errors = {f: "This field is required." for f in MANDATORY if not v[f]}
    ic = re.sub(r"[\s-]", "", v["ic_passport_no"])
    if ic and not (re.fullmatch(r"\d{12}", ic) or re.fullmatch(r"[A-Za-z]\d{6,9}", ic)):
        errors["ic_passport_no"] = "Enter a 12-digit IC (no dashes) or a passport number like A12345678."
    phone = re.sub(r"\D", "", v["phone"])
    if v["phone"] and not 9 <= len(phone) <= 12:
        errors["phone"] = "Phone must be 9 to 12 digits."
    if v["gender"] and v["gender"] not in ("Male", "Female"):
        errors["gender"] = "Choose Male or Female."
    try:
        if v["date_of_birth"] and date.fromisoformat(v["date_of_birth"]) > date.today():
            errors["date_of_birth"] = "Date of birth cannot be in the future."
    except ValueError:
        errors["date_of_birth"] = "Use a valid date."
    if v["provider_id"]:
        if not one("SELECT 1 FROM panel_provider WHERE provider_id=?", v["provider_id"]):
            errors["provider_id"] = "Unknown panel / insurer."
        if not v["policy_no"]:
            errors["policy_no"] = "Policy / membership number is required when a panel is chosen."
        if v["valid_until"]:
            try:
                date.fromisoformat(v["valid_until"])
            except ValueError:
                errors["valid_until"] = "Use a valid date."
    if errors:
        return None, errors
    v.update(ic_passport_no=ic.upper(), phone=phone)
    return v, None


def check_duplicate(v, patient_id=None):
    """1.2 Check for Duplicate Patient (reads D1) -> Duplicate Alert | New/Updated Patient Data"""
    exact = one("SELECT patient_id, full_name FROM patient WHERE ic_passport_no=? AND patient_id IS NOT ?",
                v["ic_passport_no"], patient_id)
    if exact:
        return {"type": "exact", "patient_id": exact["patient_id"], "full_name": exact["full_name"],
                "message": f"A patient with this IC/passport already exists ({exact['patient_id']}). No new record was created."}
    close = one("""SELECT patient_id, full_name FROM patient WHERE LOWER(full_name)=LOWER(?) AND date_of_birth=?
                   AND phone=? AND patient_id IS NOT ?""", v["full_name"], v["date_of_birth"], v["phone"], patient_id)
    if close and not v.get("confirm_possible_duplicate"):
        return {"type": "possible", "patient_id": close["patient_id"], "full_name": close["full_name"],
                "message": "Possible duplicate: same name, date of birth and phone. Confirm to continue."}
    return None


def create_update(v, patient_id=None):
    """1.3 Create / Update Patient Record (writes D1) -> Patient Data, Registration Notice"""
    me = current()
    fields = ["full_name", "ic_passport_no", "date_of_birth", "gender", "phone", "address", "emergency_contact", "allergies"]
    if patient_id:
        db().execute(f"UPDATE patient SET {', '.join(f + '=?' for f in fields)}, last_updated_at=?, last_updated_by=? "
                     "WHERE patient_id=?", [v.get(f) for f in fields] + [now(), me["staff_id"], patient_id])
        audit("UPDATE", "patient", patient_id)
    else:
        patient_id = next_id("patient")
        db().execute(f"INSERT INTO patient(patient_id, registered_branch_id, {', '.join(fields)}, registration_date, "
                     "last_updated_at, last_updated_by) VALUES (?,?," + ",".join("?" * len(fields)) + ",?,?,?)",
                     [patient_id, me["branch_id"]] + [v.get(f) for f in fields] + [now(), now(), me["staff_id"]])
        audit("CREATE", "patient", patient_id)
    if not v.get("provider_id") and patient_id:
        db().execute("DELETE FROM patient_coverage WHERE patient_id=?", (patient_id,))
    if v.get("provider_id"):
        db().execute("DELETE FROM patient_coverage WHERE patient_id=?", (patient_id,))
        db().execute("INSERT INTO patient_coverage VALUES (?,?,?,?,?)",
                     (next_id("patient_coverage"), patient_id, v["provider_id"], v["policy_no"], v.get("valid_until") or None))
    return patient_id


def issue_confirmation(patient_id, updated):
    """1.5 Issue Registration Confirmation -> Registration Confirmation (to Patient, printed or SMS)"""
    p = one("""SELECT p.patient_id, p.full_name, p.phone, b.branch_name, p.registration_date, p.last_updated_at
               FROM patient p JOIN branch b ON b.branch_id=p.registered_branch_id WHERE patient_id=?""", patient_id)
    text = (f"Sunrise Family Clinics: {p['full_name']}, your details were updated on {p['last_updated_at'][:10]}."
            if updated else f"Welcome to Sunrise Family Clinics. Your patient ID is {p['patient_id']} "
            f"(registered at {p['branch_name']}). Show this at any SFC branch.")
    send_sms(patient_id, "Registration Confirmation", text)
    return {**p, "message": text}


@bp.post("")
@requires("1.0w")
def register():
    validated, errors = capture_validate(body())
    if errors:
        return jsonify(error="Please correct the highlighted fields.", fields=errors), 422
    dup = check_duplicate(validated)
    if dup:
        return jsonify(error=dup["message"], duplicate=dup), 409
    pid = create_update(validated)
    conf = issue_confirmation(pid, updated=False)
    db().commit()
    return jsonify(ok=True, patient_id=pid, confirmation=conf)


@bp.put("/<pid>")
@requires("1.0w")
def update(pid):
    must_exist("patient", "patient_id", pid, "Patient")
    validated, errors = capture_validate(body())
    if errors:
        return jsonify(error="Please correct the highlighted fields.", fields=errors), 422
    dup = check_duplicate(validated, pid)
    if dup and dup["type"] == "exact":
        return jsonify(error=dup["message"], duplicate=dup), 409
    create_update(validated, pid)
    conf = issue_confirmation(pid, updated=True)
    db().commit()
    return jsonify(ok=True, patient_id=pid, confirmation=conf)


@bp.get("")
@requires("1.0")
def search():
    """1.4 Search & Retrieve Patient Record — by name, IC/passport, phone or patient ID, all branches."""
    q = request.args.get("q", "").strip()[:60]
    if len(q) < 2:
        return jsonify(results=[])
    like = f"%{q}%"
    res = rows("""SELECT p.patient_id, p.full_name, p.ic_passport_no, p.phone, p.date_of_birth, p.gender, p.allergies,
                  b.branch_name AS registered_branch FROM patient p JOIN branch b ON b.branch_id=p.registered_branch_id
                  WHERE p.full_name LIKE ? OR p.ic_passport_no LIKE ? OR p.phone LIKE ? OR p.patient_id LIKE ?
                  ORDER BY p.full_name LIMIT 25""", like, like, like, like)
    audit("SEARCH", "patient", q[:30])
    db().commit()
    return jsonify(results=res, message=None if res else "No record found.")


@bp.get("/<pid>")
@requires("1.0")
def get(pid):
    p = one("""SELECT p.*, b.branch_name AS registered_branch, s.full_name AS updated_by_name FROM patient p
               JOIN branch b ON b.branch_id=p.registered_branch_id LEFT JOIN staff s ON s.staff_id=p.last_updated_by
               WHERE p.patient_id=?""", pid)
    if not p:
        return jsonify(error="No record found."), 404
    p["coverage"] = one("""SELECT c.*, pp.provider_name, pp.copay_rate FROM patient_coverage c
                          JOIN panel_provider pp ON pp.provider_id=c.provider_id WHERE c.patient_id=?""", pid)
    # Visit history from ALL branches in date order (FR-04) — read from D3 for the record view
    p["visits"] = rows("""SELECT c.consultation_id, c.visit_date, c.diagnosis, c.treatment, s.full_name AS doctor,
                          s.specialisation, b.branch_name FROM consultation c JOIN staff s ON s.staff_id=c.staff_id
                          JOIN branch b ON b.branch_id=s.branch_id WHERE c.patient_id=? ORDER BY c.visit_date DESC""", pid)
    p["appointments"] = rows("""SELECT a.appointment_id, a.appointment_datetime, a.service_type, a.status, s.full_name AS doctor,
                                b.branch_name FROM appointment a JOIN staff s ON s.staff_id=a.staff_id
                                JOIN branch b ON b.branch_id=a.branch_id WHERE a.patient_id=?
                                ORDER BY a.appointment_datetime DESC LIMIT 10""", pid)
    audit("VIEW", "patient", pid)
    db().commit()
    return jsonify(p)
