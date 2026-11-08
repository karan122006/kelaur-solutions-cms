"""Process 5.0 Manage Billing & Payments  (DFD L0 + Level-1 Fig 6.4)
External entities: Receptionist, Patient.  Data stores: D3 (reads Charges & Dispensed Items), D5 (Bill & Payment Data).
  5.1 Generate Itemised Bill  5.2 Validate Payment  5.3 Record Payment
  5.4 Update Balance & Bill Status  5.5 Issue Payment Receipt
D5 is then read by 6.0 (Billing Data) and 7.0 (Revenue Data)."""
import json

from flask import Blueprint, jsonify, request

from .auth import body, current, requires
from .db import audit, db, next_id, now, one, rows, today
from .validate import must_exist, text

bp = Blueprint("p5", __name__, url_prefix="/api/billing")
METHODS = ("Cash", "Card", "E-wallet")


@bp.get("/ready")
@requires("5.0")
def ready():
    """Completed visits waiting to be billed + today's bills at this branch."""
    br = current()["branch_id"]
    pending = rows("""SELECT c.consultation_id, c.visit_date, c.diagnosis, p.patient_id, p.full_name, s.full_name AS doctor,
                      q.queue_no, r.status AS rx_status FROM consultation c JOIN patient p USING(patient_id)
                      JOIN staff s ON s.staff_id=c.staff_id LEFT JOIN queue_entry q ON q.queue_id=c.queue_id
                      LEFT JOIN prescription r ON r.consultation_id=c.consultation_id
                      WHERE s.branch_id=? AND c.diagnosis IS NOT NULL
                      AND NOT EXISTS (SELECT 1 FROM bill b WHERE b.consultation_id=c.consultation_id)
                      ORDER BY c.visit_date""", br)
    bills = rows("""SELECT b.*, p.full_name FROM bill b JOIN patient p USING(patient_id) WHERE b.branch_id=?
                    AND (DATE(b.bill_date)=? OR b.bill_status<>'Paid') ORDER BY b.bill_date DESC""", br, today())
    return jsonify(pending=pending, bills=bills)


@bp.post("/generate/<cid>")
@requires("5.0")
def generate_bill(cid):
    """5.1 Generate Itemised Bill: D3 Charges & Dispensed Items -> Bill Record (D5) + Itemised Bill (Receptionist)"""
    must_exist("consultation", "consultation_id", cid, "Visit")
    if one("SELECT bill_id FROM bill WHERE consultation_id=?", cid):
        return jsonify(error="A bill already exists for this visit."), 409
    c = one("""SELECT c.*, s.branch_id FROM consultation c JOIN staff s ON s.staff_id=c.staff_id WHERE consultation_id=?""", cid)
    if not c["diagnosis"]:
        return jsonify(error="The doctor has not completed this visit yet."), 409
    rx = one("SELECT status FROM prescription WHERE consultation_id=?", cid)
    if rx and rx["status"] != "Dispensed":
        return jsonify(error="Medicines have not been dispensed yet. Bill after the pharmacy completes the prescription."), 409
    lines = [dict(l) for l in json.loads(c["charges"] or "[]")]
    lines += [{"item_type": "Medicine", "description": f"{r['medication_name']} ({r['dosage'] or ''})".replace(" ()", ""),
               "quantity": r["quantity"], "unit_price": r["unit_price"]} for r in rows(
        """SELECT m.medication_name, m.unit_price, i.quantity, i.dosage FROM prescription_item i JOIN prescription r
           USING(prescription_id) JOIN medication m USING(medication_id) WHERE r.consultation_id=?""", cid)]
    cov = one("""SELECT pc.*, pp.provider_name, pp.copay_rate, pp.coverage_rules FROM patient_coverage pc
                 JOIN panel_provider pp USING(provider_id) WHERE pc.patient_id=? AND (COALESCE(pc.valid_until,'')='' OR pc.valid_until>=?)""",
              c["patient_id"], today())
    payer = "Self-pay" if not cov else ("Insurance" if "insurance" in cov["provider_name"].lower() else "Panel")
    total = round(sum(l["quantity"] * l["unit_price"] for l in lines), 2)
    bid = next_id("bill")
    # With a panel/insurer the patient owes only the co-payment; the rest is claimed by process 6.0
    patient_share = round(total * cov["copay_rate"], 2) if payer != "Self-pay" else total
    db().execute("INSERT INTO bill VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (bid, cid, c["patient_id"], c["branch_id"], now(), payer, total, 0, patient_share,
                  "Unpaid" if patient_share > 0 else "Paid"))
    for l in lines:
        db().execute("INSERT INTO bill_item VALUES (?,?,?,?,?,?,?)", (next_id("bill_item"), bid, l["item_type"],
                     l["description"], l["quantity"], l["unit_price"], round(l["quantity"] * l["unit_price"], 2)))
    audit("GENERATE", "bill", bid)
    db().commit()
    return jsonify(ok=True, bill=itemised(bid))


def itemised(bid):
    b = one("""SELECT b.*, p.full_name, p.ic_passport_no, br.branch_name, br.address, br.phone AS branch_phone
               FROM bill b JOIN patient p USING(patient_id) JOIN branch br ON br.branch_id=b.branch_id WHERE bill_id=?""", bid)
    if not b:
        return None
    b["items"] = rows("SELECT * FROM bill_item WHERE bill_id=? ORDER BY bill_item_id", bid)
    b["payments"] = rows("""SELECT y.*, s.full_name AS received_by_name FROM payment y LEFT JOIN staff s ON s.staff_id=y.received_by
                            WHERE bill_id=? ORDER BY payment_date""", bid)
    b["coverage"] = one("""SELECT pp.provider_name, pp.copay_rate, pc.policy_no FROM patient_coverage pc
                           JOIN panel_provider pp USING(provider_id) WHERE pc.patient_id=?""", b["patient_id"])
    b["panel_share"] = round(b["total_amount"] - (b["amount_paid"] + b["outstanding_balance"]), 2) \
        if b["payer_type"] != "Self-pay" else 0
    return b


@bp.get("/<bid>")
@requires("5.0")
def get_bill(bid):
    b = itemised(bid)
    return (jsonify(b), 200) if b else (jsonify(error="Bill not found."), 404)


def validate_payment(d, b):
    """5.2 Validate Payment -> Validated Payment | Payment Error"""
    try:
        amt = d.get("amount", 0)
        amt = 0 if isinstance(amt, (bool, list, dict)) else round(float(amt), 2)
    except (TypeError, ValueError):
        amt = 0
    if not b:
        return None, "Bill not found."
    if b["bill_status"] == "Paid":
        return None, "This bill is already fully paid."
    if not isinstance(d.get("payment_method"), str) or d["payment_method"] not in METHODS:
        return None, "Choose Cash, Card or E-wallet."
    if amt <= 0:
        return None, "Amount must be more than RM 0.00."
    if amt > b["outstanding_balance"] + 0.001:
        return None, f"Amount is more than the outstanding balance (RM {b['outstanding_balance']:.2f})."
    ref = text(d.get("reference_no"))[:30]
    if d["payment_method"] != "Cash" and not ref:
        return None, "Enter the card approval code or e-wallet transaction ID."
    return {"amount": amt, "payment_method": d["payment_method"], "reference_no": ref or None}, None


@bp.post("/<bid>/pay")
@requires("5.0")
def pay(bid):
    b = one("SELECT * FROM bill WHERE bill_id=?", bid)
    v, err = validate_payment(body(), b)
    if err:
        return jsonify(error=err), 422
    # 5.3 Record Payment -> Payment Record (D5)
    pid = next_id("payment")
    db().execute("INSERT INTO payment(payment_id, bill_id, payment_date, payment_method, amount, reference_no, received_by) "
                 "VALUES (?,?,?,?,?,?,?)", (pid, bid, now(), v["payment_method"], v["amount"], v["reference_no"],
                                            current()["staff_id"]))
    # 5.4 Update Balance & Bill Status (reads Bill & Payment Totals from D5)
    paid = one("SELECT COALESCE(SUM(amount),0) s FROM payment WHERE bill_id=?", bid)["s"]
    due = round(b["outstanding_balance"] + b["amount_paid"] - paid, 2)
    status = "Paid" if due <= 0.001 else "Partially Paid"
    db().execute("UPDATE bill SET amount_paid=?, outstanding_balance=?, bill_status=? WHERE bill_id=?",
                 (round(paid, 2), max(due, 0), status, bid))
    # 5.5 Issue Payment Receipt -> Receipt Record (D5) + Payment Receipt (Patient)
    rc = "RC" + pid[2:]
    db().execute("UPDATE payment SET receipt_no=?, receipt_issued_at=? WHERE payment_id=?", (rc, now(), pid))
    if status == "Paid":
        db().execute("""UPDATE queue_entry SET queue_status='Done' WHERE queue_id=(SELECT queue_id FROM consultation
                        WHERE consultation_id=?)""", (b["consultation_id"],))
    audit("PAYMENT", "payment", pid)
    db().commit()
    return jsonify(ok=True, receipt_no=rc, payment_id=pid, bill=itemised(bid),
                   message=f"Payment recorded. Receipt {rc}. Status: {status}.")
