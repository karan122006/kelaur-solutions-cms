"""Process 6.0 Manage Insurance & Panel Claims (DFD L0)
In : D5 -> Billing Data;  Panel/Insurance Provider -> Claim Decision & Coverage Rules
Out: Panel/Insurance Provider <- Claim Submission;  6.0 <-> D6 Claim Data / Claim Status;  6.0 -> 8.0 Rejected Claim Alert
D6 is read by 7.0 (Claim Data)."""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from .auth import body, current, requires
from .db import audit, db, next_id, now, one, rows
from .p8_notify import alert_staff
from .validate import must_exist, text, to_money

bp = Blueprint("p6", __name__, url_prefix="/api")
OVERDUE_DAYS = 30


def _scope():
    me = current()
    return None if me["role"] == "head_office" else me["branch_id"]


@bp.get("/claims")
@requires("6.0")
def list_claims():
    br = request.args.get("branch_id") or _scope()
    cutoff = (datetime.now() - timedelta(days=OVERDUE_DAYS)).strftime("%Y-%m-%d")
    sql = """SELECT c.*, b.branch_id, br.branch_name, b.total_amount, b.bill_date, p.full_name, p.patient_id, pp.provider_name,
             pc.policy_no FROM claim c JOIN bill b USING(bill_id) JOIN branch br ON br.branch_id=b.branch_id
             JOIN patient p ON p.patient_id=b.patient_id JOIN panel_provider pp ON pp.provider_id=c.provider_id
             LEFT JOIN patient_coverage pc ON pc.patient_id=p.patient_id AND pc.provider_id=c.provider_id WHERE 1=1"""
    args = []
    if br:
        sql += " AND b.branch_id=?"
        args.append(br)
    if request.args.get("provider_id"):
        sql += " AND c.provider_id=?"
        args.append(request.args["provider_id"])
    data = rows(sql + " ORDER BY c.claim_id DESC", *args)
    for c in data:
        c["flag"] = ("Rejected" if c["claim_status"] == "Rejected" else
                     "Overdue" if c["claim_status"] == "Submitted" and (c["submitted_date"] or "") < cutoff else "")
    unclaimed = rows("""SELECT COUNT(*) n FROM bill b WHERE payer_type<>'Self-pay' AND NOT EXISTS
                        (SELECT 1 FROM claim c WHERE c.bill_id=b.bill_id)""" + (" AND b.branch_id=?" if br else ""),
                     *([br] if br else []))[0]["n"]
    summary = rows("""SELECT pp.provider_name, br.branch_name, COUNT(*) claims, SUM(c.amount_claimed) claimed,
                      SUM(COALESCE(c.amount_approved,0)) approved,
                      SUM(c.claim_status='Rejected') rejected FROM claim c JOIN bill b USING(bill_id)
                      JOIN branch br ON br.branch_id=b.branch_id JOIN panel_provider pp ON pp.provider_id=c.provider_id"""
                   + (" WHERE b.branch_id=?" if br else "") + " GROUP BY pp.provider_id, br.branch_id ORDER BY claimed DESC",
                   *([br] if br else []))
    return jsonify(claims=data, unclaimed=unclaimed, summary=summary,
                   providers=rows("SELECT * FROM panel_provider ORDER BY provider_name"))


@bp.post("/claims/generate")
@requires("6.0")
def generate():
    """Billing Data (D5) -> Claim Data (D6): one Draft claim per panel/insurance bill."""
    br = _scope()
    bills = rows("""SELECT b.bill_id, b.total_amount, b.patient_id, b.amount_paid, b.outstanding_balance FROM bill b
                    WHERE payer_type<>'Self-pay' AND NOT EXISTS (SELECT 1 FROM claim c WHERE c.bill_id=b.bill_id)"""
                 + (" AND b.branch_id=?" if br else ""), *([br] if br else []))
    n = 0
    for b in bills:
        cov = one("SELECT provider_id FROM patient_coverage WHERE patient_id=?", b["patient_id"])
        if not cov:
            continue
        claimable = round(b["total_amount"] - b["amount_paid"] - b["outstanding_balance"], 2)
        db().execute("INSERT INTO claim VALUES (?,?,?,?,?,?,?)",
                     (next_id("claim"), b["bill_id"], cov["provider_id"], "Draft", claimable, None, None))
        n += 1
    audit(f"GENERATE {n} claims", "claim")
    db().commit()
    return jsonify(ok=True, message=f"{n} draft claim(s) prepared from billing records." if n else "No new bills to claim.")


@bp.post("/claims/submit")
@requires("6.0")
def submit():
    """Claim Submission -> Panel / Insurance Provider"""
    ids = body().get("ids", [])
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="Send a list of claim IDs."), 422
    br = _scope()
    for cid in ids:
        db().execute("""UPDATE claim SET claim_status='Submitted', submitted_date=? WHERE claim_id=? AND claim_status='Draft'
                        AND (? IS NULL OR bill_id IN (SELECT bill_id FROM bill WHERE branch_id=?))""", (now()[:10], cid, br, br))
    audit(f"SUBMIT {len(ids)} claims", "claim")
    db().commit()
    return jsonify(ok=True, message=f"{len(ids)} claim(s) submitted to the panel/insurer.")


@bp.post("/claims/<cid>/decision")
@requires("6.0")
def decision(cid):
    """Claim Decision from Panel / Insurance Provider -> D6; rejection -> 8.0 Rejected Claim Alert"""
    d = body()
    st = d.get("status")
    c = one("""SELECT c.*, b.branch_id FROM claim c JOIN bill b USING(bill_id) WHERE claim_id=?""", cid)
    if not c:
        return jsonify(error="Claim not found."), 422
    if _scope() and c["branch_id"] != _scope():
        return jsonify(error="This claim belongs to another branch."), 403
    if not isinstance(st, str) or st not in ("Approved", "Rejected", "Paid"):
        return jsonify(error="Choose Approved, Rejected or Paid."), 422
    if c["claim_status"] not in ("Submitted", "Approved"):
        return jsonify(error=f"Only submitted claims can receive a decision (this one is {c['claim_status']})."), 409
    amt = d.get("amount_approved")
    if st == "Rejected":
        amt = 0
    elif amt in (None, ""):
        amt = c["amount_approved"] if st == "Paid" and c["amount_approved"] is not None else c["amount_claimed"]
    else:
        amt = to_money(amt, "Approved amount")
    if amt < 0 or amt > c["amount_claimed"] + 0.001:
        return jsonify(error="Approved amount must be between 0 and the amount claimed."), 422
    db().execute("UPDATE claim SET claim_status=?, amount_approved=? WHERE claim_id=?", (st, amt, cid))
    if st == "Rejected":
        alert_staff(c["branch_id"], ("receptionist", "branch_manager"), "Rejected Claim",
                    f"Claim {cid} was rejected: {text(d.get('reason'))[:200] or 'no reason given'}. Please review and resubmit.")
    audit(f"CLAIM {st}", "claim", cid)
    db().commit()
    return jsonify(ok=True, message=f"Claim {cid} marked {st}.")


@bp.post("/claims/<cid>/resubmit")
@requires("6.0")
def resubmit(cid):
    c = must_exist("claim", "claim_id", cid, "Claim")
    if c["claim_status"] != "Rejected":
        return jsonify(error="Only rejected claims can be corrected and redone."), 409
    db().execute("UPDATE claim SET claim_status='Draft', amount_approved=NULL WHERE claim_id=? AND claim_status='Rejected'", (cid,))
    db().commit()
    return jsonify(ok=True, message="Claim moved back to Draft for correction.")


@bp.put("/providers/<pid>")
@requires("6.0")
def update_provider(pid):
    """Coverage Rules from Panel / Insurance Provider"""
    if current()["role"] == "receptionist":
        return jsonify(error="Only branch managers and head office can change coverage rules."), 403
    must_exist("panel_provider", "provider_id", pid, "Panel / insurer")
    d = body()
    try:
        rate = d.get("copay_rate")
        if isinstance(rate, (bool, list, dict)):
            raise ValueError
        rate = float(rate)
        assert 0 <= rate <= 1
    except (TypeError, ValueError, AssertionError):
        return jsonify(error="Co-pay rate must be between 0 and 1 (e.g. 0.10 for 10%)."), 422
    db().execute("UPDATE panel_provider SET coverage_rules=?, copay_rate=? WHERE provider_id=?", (text(d.get("coverage_rules"))[:500], rate, pid))
    audit("UPDATE coverage rules", "panel_provider", pid)
    db().commit()
    return jsonify(ok=True, message="Coverage rules updated.")
