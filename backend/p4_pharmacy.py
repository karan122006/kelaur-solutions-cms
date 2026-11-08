"""Process 4.0 Manage Pharmacy Dispensing & Stock (DFD L0)
In : Pharmacy Assistant -> Dispensing & Stock Entries;  D3 -> Prescription Details
Out: Pharmacy Assistant <- Prescription Queue, Allergy Alert & Label;  4.0 -> D3 Dispensed Items
     4.0 <-> D4 Stock Updates / Stock Levels & Expiry;  4.0 -> 8.0 Stock Alert Data"""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from .auth import body, current, requires
from .db import audit, db, next_id, now, one, rows, today
from .p8_notify import alert_staff
from .clinical import allergy_conflicts
from .validate import must_exist, text, to_date, to_int

bp = Blueprint("p4", __name__, url_prefix="/api")
NEAR_EXPIRY_DAYS = 90


def _branch():
    me = current()
    return request.args.get("branch_id") or me["branch_id"] or "B01"


def fefo_batches(med_id, branch_id):
    """First-expiry-first-out list of usable batches."""
    return rows("""SELECT batch_id, batch_no, expiry_date, quantity_on_hand FROM stock_batch WHERE medication_id=? AND branch_id=?
                   AND quantity_on_hand>0 AND expiry_date>=? ORDER BY expiry_date""", med_id, branch_id, today())


@bp.get("/pharmacy/queue")
@requires("4.0")
def rx_queue():
    branch = _branch()
    pres = rows("""SELECT r.prescription_id, r.issued_at, r.status, c.consultation_id, c.diagnosis, p.patient_id, p.full_name,
                   p.date_of_birth, p.allergies, s.full_name AS doctor, q.queue_no FROM prescription r
                   JOIN consultation c USING(consultation_id) JOIN patient p ON p.patient_id=c.patient_id
                   JOIN staff s ON s.staff_id=c.staff_id LEFT JOIN queue_entry q ON q.queue_id=c.queue_id
                   WHERE s.branch_id=? AND (r.status='Pending' OR DATE(r.issued_at)=?) ORDER BY r.status DESC, r.issued_at""",
                branch, today())
    for r in pres:
        r["items"] = rows("""SELECT i.*, m.medication_name, m.unit FROM prescription_item i JOIN medication m USING(medication_id)
                             WHERE prescription_id=?""", r["prescription_id"])
        for i in r["items"]:
            i["batches"] = fefo_batches(i["medication_id"], branch)
            i["available"] = sum(b["quantity_on_hand"] for b in i["batches"])
        allergy = (r["allergies"] or "").lower()
        r["allergy_alert"] = bool(allergy and allergy not in ("none known", "none"))
        r["allergy_conflicts"] = allergy_conflicts(r["allergies"], [i["medication_name"] for i in r["items"]])
    return jsonify(prescriptions=pres)


@bp.post("/pharmacy/dispense/<rx>")
@requires("4.0w")
def dispense(rx):
    d = body()
    if not d.get("allergy_checked"):
        return jsonify(error="Confirm that you have checked the patient's allergies before dispensing."), 422
    r = must_exist("prescription", "prescription_id", rx, "Prescription")
    if r["status"] != "Pending":
        return jsonify(error="This prescription has already been dispensed."), 409
    branch = current()["branch_id"]
    items = rows("SELECT * FROM prescription_item WHERE prescription_id=?", rx)
    chosen = {x.get("item_id"): x.get("batch_id") for x in (d.get("items") if isinstance(d.get("items"), list) else [])
              if isinstance(x, dict)}
    labels = []
    for i in items:
        bid = chosen.get(i["item_id"]) or (fefo_batches(i["medication_id"], branch) or [{}])[0].get("batch_id")
        b = one("SELECT * FROM stock_batch WHERE batch_id=?", bid) if isinstance(bid, str) else None
        if (not b or b["quantity_on_hand"] < i["quantity"] or b["expiry_date"] < today() or b["branch_id"] != branch
                or b["medication_id"] != i["medication_id"]):
            m = one("SELECT medication_name FROM medication WHERE medication_id=?", i["medication_id"])
            return jsonify(error=f"Not enough usable stock of {m['medication_name']} in the chosen batch."), 409
        db().execute("UPDATE stock_batch SET quantity_on_hand=quantity_on_hand-? WHERE batch_id=?", (i["quantity"], bid))
        db().execute("UPDATE prescription_item SET batch_id=? WHERE item_id=?", (bid, i["item_id"]))
        labels.append(i["item_id"])
        _check_reorder(i["medication_id"], branch)
    db().execute("UPDATE prescription SET status='Dispensed' WHERE prescription_id=?", (rx,))
    db().execute("""UPDATE queue_entry SET queue_status='Paying' WHERE queue_id=(SELECT queue_id FROM consultation
                    WHERE consultation_id=?)""", (r["consultation_id"],))
    audit("DISPENSE", "prescription", rx)
    db().commit()
    return jsonify(ok=True, message="Dispensed. Stock updated automatically.", labels=label_data(rx))


def label_data(rx):
    return rows("""SELECT i.dosage, i.quantity, m.medication_name, m.unit, b.batch_no, b.expiry_date, p.full_name,
                   p.patient_id, br.branch_name, br.phone, r.issued_at, s.full_name AS doctor FROM prescription_item i
                   JOIN medication m USING(medication_id) JOIN stock_batch b ON b.batch_id=i.batch_id
                   JOIN prescription r USING(prescription_id) JOIN consultation c ON c.consultation_id=r.consultation_id
                   JOIN patient p ON p.patient_id=c.patient_id JOIN staff s ON s.staff_id=c.staff_id
                   JOIN branch br ON br.branch_id=s.branch_id WHERE i.prescription_id=?""", rx)


def _check_reorder(med_id, branch):
    m = one("""SELECT m.medication_name, m.reorder_level, COALESCE(SUM(b.quantity_on_hand),0) qty FROM medication m
               LEFT JOIN stock_batch b ON b.medication_id=m.medication_id AND b.branch_id=? AND b.expiry_date>=?
               WHERE m.medication_id=?""", branch, today(), med_id)
    if m["qty"] <= m["reorder_level"]:
        alert_staff(branch, ("pharmacy", "branch_manager", "head_office"), "Stock Alert",
                    f"Low stock: {m['medication_name']} at {m['qty']} (reorder level {m['reorder_level']}).")


@bp.get("/stock")
@requires("4.0")
def stock():
    branch = _branch()
    soon = (datetime.now() + timedelta(days=NEAR_EXPIRY_DAYS)).strftime("%Y-%m-%d")
    meds = rows("""SELECT m.*, COALESCE(SUM(CASE WHEN b.expiry_date>=? THEN b.quantity_on_hand END),0) AS on_hand,
                   COALESCE(SUM(CASE WHEN b.expiry_date BETWEEN ? AND ? THEN b.quantity_on_hand END),0) AS near_expiry,
                   MIN(CASE WHEN b.quantity_on_hand>0 AND b.expiry_date>=? THEN b.expiry_date END) AS next_expiry
                   FROM medication m LEFT JOIN stock_batch b ON b.medication_id=m.medication_id AND b.branch_id=?
                   GROUP BY m.medication_id ORDER BY m.medication_name""", today(), today(), soon, today(), branch)
    batches = rows("""SELECT b.*, m.medication_name, sp.supplier_name FROM stock_batch b JOIN medication m USING(medication_id)
                      LEFT JOIN supplier sp USING(supplier_id) WHERE b.branch_id=? AND b.quantity_on_hand>0
                      ORDER BY b.expiry_date""", branch)
    for b in batches:
        b["flag"] = "Expired" if b["expiry_date"] < today() else ("Near expiry" if b["expiry_date"] <= soon else "")
    return jsonify(medications=meds, batches=batches, suppliers=rows("SELECT * FROM supplier"),
                   transfers=rows("""SELECT t.*, m.medication_name, b.batch_no, f.branch_name AS from_name, tb.branch_name AS to_name
                                     FROM stock_transfer t JOIN stock_batch b USING(batch_id) JOIN medication m USING(medication_id)
                                     JOIN branch f ON f.branch_id=t.from_branch_id JOIN branch tb ON tb.branch_id=t.to_branch_id
                                     WHERE ? IN (t.from_branch_id, t.to_branch_id) OR ?='ALL'
                                     ORDER BY t.requested_at DESC LIMIT 30""", branch,
                                  "ALL" if current()["role"] == "head_office" else ""))


@bp.get("/stock/network")
@requires("4.0")
def network():
    """Head office: stock levels network-wide (FR-06)."""
    soon = (datetime.now() + timedelta(days=NEAR_EXPIRY_DAYS)).strftime("%Y-%m-%d")
    data = rows("""SELECT m.medication_id, m.medication_name, m.reorder_level, br.branch_id, br.branch_name,
                   COALESCE(SUM(CASE WHEN b.expiry_date>=? THEN b.quantity_on_hand END),0) qty,
                   COALESCE(SUM(CASE WHEN b.expiry_date BETWEEN ? AND ? THEN b.quantity_on_hand END),0) near
                   FROM medication m CROSS JOIN branch br LEFT JOIN stock_batch b ON b.medication_id=m.medication_id
                   AND b.branch_id=br.branch_id GROUP BY m.medication_id, br.branch_id ORDER BY m.medication_name, br.branch_id""",
                today(), today(), soon)
    return jsonify(cells=data, branches=rows("SELECT branch_id, branch_name FROM branch ORDER BY branch_id"))


@bp.post("/stock/receive")
@requires("4.0w")
def receive():
    d = body()
    if not text(d.get("medication_id")) or not text(d.get("batch_no")) or not text(d.get("expiry_date")):
        return jsonify(error="Medication, batch number, expiry date and a quantity above 0 are required."), 422
    must_exist("medication", "medication_id", d["medication_id"], "Medicine", 422)
    if text(d.get("supplier_id")):
        must_exist("supplier", "supplier_id", d["supplier_id"], "Supplier", 422)
    else:
        d["supplier_id"] = None
    qty = to_int(d.get("quantity"), "Quantity", 1, 100000)
    d["expiry_date"] = to_date(d["expiry_date"], "Expiry date")
    if d["expiry_date"] <= today():
        return jsonify(error="Cannot receive stock that is already expired."), 422
    d["batch_no"] = text(d["batch_no"])[:30]
    bid = next_id("stock_batch")
    db().execute("INSERT INTO stock_batch VALUES (?,?,?,?,?,?,?)", (bid, d["medication_id"], current()["branch_id"],
                                                                    d.get("supplier_id"), d["batch_no"], d["expiry_date"], qty))
    audit("RECEIVE", "stock_batch", bid)
    db().commit()
    return jsonify(ok=True, message=f"Received {qty} units into batch {d['batch_no']}.")


@bp.post("/stock/adjust")
@requires("4.0w")
def adjust():
    d = body()
    b = one("SELECT * FROM stock_batch WHERE batch_id=?", d["batch_id"]) if isinstance(d.get("batch_id"), str) else None
    qty = to_int(d.get("quantity"), "Quantity", 1) if b else 0
    if b and b["branch_id"] != current()["branch_id"]:
        return jsonify(error="You can only adjust stock at your own branch."), 403
    if not b or qty <= 0 or d.get("reason") not in ("Damaged", "Disposed (expired)", "Count correction (-)", "Count correction (+)"):
        return jsonify(error="Choose a batch, a reason and a quantity above 0."), 422
    delta = qty if d["reason"] == "Count correction (+)" else -qty
    if b["quantity_on_hand"] + delta < 0:
        return jsonify(error="Adjustment would make the quantity negative."), 422
    db().execute("UPDATE stock_batch SET quantity_on_hand=quantity_on_hand+? WHERE batch_id=?", (delta, b["batch_id"]))
    audit(f"ADJUST {d['reason']} {delta:+d}", "stock_batch", b["batch_id"])
    _check_reorder(b["medication_id"], b["branch_id"])
    db().commit()
    return jsonify(ok=True, message="Stock adjusted and logged.")


@bp.post("/stock/transfer")
@requires("4.0")
def request_transfer():
    d = body()
    b = one("SELECT * FROM stock_batch WHERE batch_id=?", d["batch_id"]) if isinstance(d.get("batch_id"), str) else None
    to = text(d.get("to_branch_id"))
    qty = to_int(d.get("quantity"), "Quantity", 1) if b and to else 0
    if b and current()["role"] != "head_office" and b["branch_id"] != current()["branch_id"]:
        return jsonify(error="You can only send stock from your own branch."), 403
    if to and not one("SELECT 1 FROM branch WHERE branch_id=?", to):
        return jsonify(error="Unknown destination branch."), 422
    if not b or not to or qty <= 0 or qty > b["quantity_on_hand"] or to == b["branch_id"]:
        return jsonify(error="Choose a batch, a different destination branch and a quantity you hold."), 422
    tid = next_id("stock_transfer")
    db().execute("INSERT INTO stock_transfer VALUES (?,?,?,?,?,?,?)",
                 (tid, b["batch_id"], b["branch_id"], to, qty, "Requested", now()))
    alert_staff(None, ("head_office",), "Stock Alert", f"Transfer {tid} requested: {qty} units to {to}.")
    audit("TRANSFER-REQUEST", "stock_transfer", tid)
    db().commit()
    return jsonify(ok=True, message="Transfer requested. Head office has been alerted for approval.")


@bp.post("/stock/transfer/<tid>/<decision>")
@requires("4.0a")
def decide_transfer(tid, decision):
    if decision not in ("approve", "reject"):
        return jsonify(error="Decision must be approve or reject."), 422
    t = one("SELECT * FROM stock_transfer WHERE transfer_id=?", tid)
    if not t or t["transfer_status"] != "Requested":
        return jsonify(error="This transfer has already been decided."), 409
    me = current()
    if me["role"] == "branch_manager" and me["branch_id"] not in (t["from_branch_id"], t["to_branch_id"]):
        return jsonify(error="Branch managers can only decide transfers that involve their own branch."), 403
    if decision == "approve":
        b = one("SELECT * FROM stock_batch WHERE batch_id=?", t["batch_id"])
        if b["quantity_on_hand"] < t["quantity"]:
            return jsonify(error="Source branch no longer holds enough stock."), 409
        db().execute("UPDATE stock_batch SET quantity_on_hand=quantity_on_hand-? WHERE batch_id=?", (t["quantity"], b["batch_id"]))
        dest = one("SELECT batch_id FROM stock_batch WHERE branch_id=? AND medication_id=? AND batch_no=?",
                   t["to_branch_id"], b["medication_id"], b["batch_no"])
        if dest:
            db().execute("UPDATE stock_batch SET quantity_on_hand=quantity_on_hand+? WHERE batch_id=?", (t["quantity"], dest["batch_id"]))
        else:
            db().execute("INSERT INTO stock_batch VALUES (?,?,?,?,?,?,?)", (next_id("stock_batch"), b["medication_id"],
                         t["to_branch_id"], b["supplier_id"], b["batch_no"], b["expiry_date"], t["quantity"]))
    db().execute("UPDATE stock_transfer SET transfer_status=? WHERE transfer_id=?",
                 ("Approved" if decision == "approve" else "Rejected", tid))
    audit(f"TRANSFER-{decision.upper()}", "stock_transfer", tid)
    db().commit()
    return jsonify(ok=True, message=f"Transfer {decision}d.")
