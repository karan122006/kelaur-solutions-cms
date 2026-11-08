"""Builds the demo database: 5 SFC branches, 48 staff, patients, stock and ~45 days of history,
so every DFD flow (and the 7.0 dashboard) has data to show. Run: python -m backend.seed"""
import json
import os
import random
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from .db import DB_PATH, connect
from .p3_consultation import FEES, PROCEDURES

random.seed(7)
DEMO_PASSWORD = "Sfc@2026"

BRANCHES = [
    ("B01", "SFC Petaling Jaya (SS2)", "23 Jalan SS2/24, 47300 Petaling Jaya", "Petaling Jaya", "03-7875 1201"),
    ("B02", "SFC Damansara Utama", "8 Jalan SS21/37, 47400 Petaling Jaya", "Petaling Jaya", "03-7726 1202"),
    ("B03", "SFC Shah Alam Seksyen 7", "15 Jalan Plumbum 7/102, 40000 Shah Alam", "Shah Alam", "03-3342 1203"),
    ("B04", "SFC Shah Alam Seksyen 13", "4 Jalan Kristal 13/14, 40100 Shah Alam", "Shah Alam", "03-5511 1204"),
    ("B05", "SFC Subang Jaya (SS15)", "61 Jalan SS15/4, 47500 Subang Jaya", "Subang Jaya", "03-5612 1205"),
]
SHORT = {"B01": "pj", "B02": "du", "B03": "sa7", "B04": "sa13", "B05": "sj"}
FIRST = ["Mei Ling", "Hafiz", "Aisyah", "Wei Jie", "Priya", "Arjun", "Nurul", "Siti", "Jun Hao", "Kavitha", "Farid", "Hui Min",
         "Amirul", "Deepa", "Kok Leong", "Nadia", "Rajesh", "Shu Fen", "Izzat", "Lakshmi", "Chee Keong", "Hana", "Ganesh",
         "Yee Ling", "Zulkifli", "Anita", "Boon Huat", "Farah", "Suresh", "Li Ting", "Hakim", "Meena", "Zhi Wei", "Aina",
         "Vikram", "Pei Shan", "Danial", "Sangeetha", "Kah Wai", "Alya", "Ravi", "Xin Yi", "Irfan", "Malini", "Jia Hui"]
LAST_C = ["Tan", "Lim", "Wong", "Lee", "Chong", "Ng", "Ong", "Goh", "Chan", "Teo"]
LAST_M = ["binti Ahmad", "bin Ismail", "binti Hassan", "bin Abdullah", "binti Yusof", "bin Rahman", "binti Osman"]
LAST_I = ["a/l Subramaniam", "a/p Krishnan", "a/l Muthu", "a/p Raman", "a/l Pillai", "a/p Nair"]
ALLERGIES = ["None known"] * 8 + ["Penicillin", "Amoxicillin", "Ibuprofen", "Seafood", "Sulfa drugs", "Peanuts"]
DIAG = {"General Practice": [("Fever, cough and runny nose", "Upper respiratory tract infection", "Rest, fluids, symptomatic relief"),
                             ("Loose stools x2 days", "Acute gastroenteritis", "Oral rehydration, light diet"),
                             ("Headache, BP review", "Hypertension - follow up", "Continue amlodipine, low-salt diet"),
                             ("Sneezing, itchy eyes", "Allergic rhinitis", "Antihistamine, avoid triggers"),
                             ("Epigastric pain after meals", "Gastritis", "PPI for 2 weeks"),
                             ("Fasting sugar review", "Type 2 diabetes - follow up", "Continue metformin, HbA1c in 3 months")],
        "Paediatrics": [("Fever 38.5, poor appetite", "Viral fever", "Paracetamol syrup, fluids"),
                        ("Wheeze at night", "Mild asthma exacerbation", "Salbutamol inhaler with spacer"),
                        ("Well-child visit, 18 months", "Routine immunisation", "MMR given, growth normal")],
        "Dental": [("Routine check", "Dental plaque / calculus", "Scaling and polishing"),
                   ("Pain lower molar", "Dental caries 36", "Composite filling")]}
MEDS = [("MD0000001", "Paracetamol 500mg tab", "tab", 200, 0.30), ("MD0000002", "Amoxicillin 250mg cap", "cap", 150, 0.80),
        ("MD0000003", "Ibuprofen 400mg tab", "tab", 120, 0.50), ("MD0000004", "Cetirizine 10mg tab", "tab", 100, 0.60),
        ("MD0000005", "Loratadine 10mg tab", "tab", 80, 0.70), ("MD0000006", "Metformin 500mg tab", "tab", 150, 0.40),
        ("MD0000007", "Amlodipine 5mg tab", "tab", 120, 0.60), ("MD0000008", "Omeprazole 20mg cap", "cap", 100, 0.90),
        ("MD0000009", "Salbutamol 100mcg inhaler", "inhaler", 15, 18.00), ("MD0000010", "Paracetamol 120mg/5ml syrup", "bottle", 25, 6.50),
        ("MD0000011", "Chlorpheniramine 2mg/5ml syrup", "bottle", 20, 5.50), ("MD0000012", "Oral rehydration salts", "sachet", 60, 1.20),
        ("MD0000013", "Diclofenac 1% gel", "tube", 20, 9.00), ("MD0000014", "Chlorhexidine 0.2% mouthwash", "bottle", 15, 12.00),
        ("MD0000015", "Mefenamic acid 250mg cap", "cap", 100, 0.50)]
RX_FOR = {"Upper respiratory tract infection": [("MD0000001", "1 tab 3x daily", 10), ("MD0000004", "1 tab at night", 5)],
          "Acute gastroenteritis": [("MD0000012", "1 sachet after each loose stool", 6)],
          "Hypertension - follow up": [("MD0000007", "1 tab daily", 30)],
          "Allergic rhinitis": [("MD0000005", "1 tab daily", 14)],
          "Gastritis": [("MD0000008", "1 cap before breakfast", 14)],
          "Type 2 diabetes - follow up": [("MD0000006", "1 tab 2x daily with meals", 60)],
          "Viral fever": [("MD0000010", "5ml 4x daily when febrile", 1)],
          "Mild asthma exacerbation": [("MD0000009", "2 puffs when needed", 1)],
          "Dental caries 36": [("MD0000015", "1 cap 3x daily after food", 9)],
          "Dental plaque / calculus": [("MD0000014", "Rinse 10ml 2x daily", 1)]}
PROVIDERS = [("PP0000001", "Selangor Corporate Panel", "Puan Rohana", "03-5510 8899", "GP & paediatric consultations and generic "
              "medicines covered; dental excluded. Guarantee letter not required.", 0.0),
             ("PP0000002", "MyHealth Panel Sdn Bhd", "Mr. Daniel Ooi", "03-7954 2211", "Outpatient GP covered up to RM150 per "
              "visit; patient pays 10% co-payment.", 0.10),
             ("PP0000003", "Prudent Life Insurance", "Ms. Kavitha Rao", "1-300-88-7755", "Outpatient & dental (RM500/yr). "
              "20% co-insurance. Claims within 30 days.", 0.20),
             ("PP0000004", "Harmoni Takaful Insurance", "Encik Faizal", "1-300-22-4646", "Outpatient GP & paediatrics; "
              "15% co-takaful.", 0.15)]
SUPPLIERS = [("SP0000001", "Duopharma Distribution", "03-6091 3000", "orders@duo-dist.example"),
             ("SP0000002", "Pharmaniaga Logistics", "03-3342 9999", "sales@pharma-log.example"),
             ("SP0000003", "Zuellig Pharma Malaysia", "03-7845 6000", "cs@zp-my.example")]


def ic_for(dob, i):
    return dob.strftime("%y%m%d") + random.choice(["10", "14", "08", "12"]) + f"{(i * 37) % 10000:04d}"


def name(i):
    pool = random.choice(["c", "m", "i"])
    f = FIRST[i % len(FIRST)]
    return {"c": lambda: f"{random.choice(LAST_C)} {f}", "m": lambda: f"{f} {random.choice(LAST_M)}",
            "i": lambda: f"{f} {random.choice(LAST_I)}"}[pool]()


def build(path=DB_PATH):
    if os.path.exists(path):
        os.remove(path)
    for ext in ("-wal", "-shm"):
        if os.path.exists(path + ext):
            os.remove(path + ext)
    con = connect(path)
    con.executescript(open(os.path.join(os.path.dirname(__file__), "schema.sql")).read())
    x = con.execute
    pw = generate_password_hash(DEMO_PASSWORD)
    for b in BRANCHES:
        x("INSERT INTO branch VALUES (?,?,?,?,?)", b)

    # ---- 48 staff -------------------------------------------------------
    staff, n = [], 0
    def add_staff(branch, full, role, spec=None, username=None):
        nonlocal n
        n += 1
        sid, uid = f"ST{n:07d}", f"US{n:07d}"
        x("INSERT INTO staff VALUES (?,?,?,?,?,?,?,?)", (sid, branch, full, role, spec, f"01{random.randint(2, 9)}-"
          f"{random.randint(100, 999)} {random.randint(1000, 9999)}", (username or sid).lower() + "@sfc.example", "Active"))
        x("INSERT INTO user_account(user_id, staff_id, username, password, account_status) VALUES (?,?,?,?,?)",
          (uid, sid, username or sid.lower(), pw, "Active"))
        staff.append(dict(staff_id=sid, branch_id=branch, full_name=full, role=role, specialisation=spec))
        return sid
    add_staff("B01", "Dr. Chong Mei Ling", "head_office", None, "hq")
    add_staff("B01", "Aung Ko Htwe", "admin", None, "admin")
    gp_names = ["Dr. Hafiz Rahman", "Dr. Tan Wei Jie", "Dr. Priya Menon", "Dr. Lim Shu Fen", "Dr. Amirul Hakim"]
    pd_names = ["Dr. Nurul Izzah", "Dr. Ganesh Kumar", "Dr. Ong Hui Min", "Dr. Farah Aziz", "Dr. Raj Pillai"]
    for k, b in enumerate(BRANCHES):
        bid, s = b[0], SHORT[b[0]]
        add_staff(bid, gp_names[k], "doctor", "General Practice", f"dr.{gp_names[k].split()[-1].lower()}")
        add_staff(bid, pd_names[k], "doctor", "Paediatrics", f"dr.{pd_names[k].split()[-1].lower()}")
        add_staff(bid, name(k * 3 + 1), "nurse", None, f"nurse.{s}")
        add_staff(bid, name(k * 3 + 2), "nurse", None, None)
        add_staff(bid, name(k * 3 + 3), "pharmacy", None, f"pharmacy.{s}")
        add_staff(bid, name(k * 3 + 4), "pharmacy", None, None)
        add_staff(bid, name(k * 3 + 5), "receptionist", None, f"reception.{s}")
        add_staff(bid, name(k * 3 + 6), "receptionist", None, None)
        add_staff(bid, name(k * 3 + 7), "branch_manager", None, f"manager.{s}")
    add_staff("B01", "Dr. Siti Aminah", "dentist", "Dental", "dr.aminah")
    assert len(staff) == 48, len(staff)

    for p in PROVIDERS:
        x("INSERT INTO panel_provider VALUES (?,?,?,?,?,?)", p)
    for s in SUPPLIERS:
        x("INSERT INTO supplier VALUES (?,?,?,?)", s)
    for m in MEDS:
        x("INSERT INTO medication VALUES (?,?,?,?,?)", m)

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # ---- D4 stock -------------------------------------------------------
    nb = 0
    for b in BRANCHES:
        for m in MEDS:
            for j in range(2):
                nb += 1
                lvl = m[3]
                qty = random.randint(int(lvl * 0.3), int(lvl * 2.2)) if j == 0 else random.randint(int(lvl * .5), lvl * 2)
                exp = today + timedelta(days=random.choice([40, 75, 160, 300, 420, 540]) if j == 0 else random.randint(200, 700))
                x("INSERT INTO stock_batch VALUES (?,?,?,?,?,?,?)", (f"SB{nb:07d}", m[0], b[0], random.choice(SUPPLIERS)[0],
                  f"{m[1][:3].upper()}{random.randint(1000, 9999)}{'AB'[j]}", exp.strftime("%Y-%m-%d"), qty))
    # deliberate imbalance (the case-study problem): B03 low on paracetamol, B05 overstocked & near expiry
    x("UPDATE stock_batch SET quantity_on_hand=40 WHERE branch_id='B03' AND medication_id='MD0000001'")
    x("""UPDATE stock_batch SET quantity_on_hand=600, expiry_date=? WHERE branch_id='B05' AND medication_id='MD0000001'
         AND batch_id=(SELECT MIN(batch_id) FROM stock_batch WHERE branch_id='B05' AND medication_id='MD0000001')""",
      ((today + timedelta(days=50)).strftime("%Y-%m-%d"),))
    x("UPDATE stock_batch SET quantity_on_hand=4 WHERE branch_id='B01' AND medication_id='MD0000009'")
    x("INSERT INTO stock_transfer VALUES ('TR0000001',(SELECT MIN(batch_id) FROM stock_batch WHERE branch_id='B05' AND "
      "medication_id='MD0000001'),'B05','B03',200,'Requested',?)", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))

    # ---- D1 patients ----------------------------------------------------
    patients = []
    for i in range(160):
        age = random.choice([random.randint(1, 12), random.randint(18, 75), random.randint(25, 60)])
        dob = today - timedelta(days=age * 365 + random.randint(0, 364))
        pid = f"PT{i + 1:07d}"
        br = random.choice(BRANCHES)[0]
        reg = today - timedelta(days=random.randint(1, 700))
        nm = name(i + 11)
        x("INSERT INTO patient VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (pid, br, ic_for(dob, i + 3), nm, dob.strftime("%Y-%m-%d"), random.choice(["Male", "Female"]),
           f"01{random.randint(1, 9)}{random.randint(1000000, 9999999)}", f"{random.randint(1, 99)}, Jalan SS{random.randint(1, 25)}/"
           f"{random.randint(1, 40)}, {random.choice(['Petaling Jaya', 'Shah Alam', 'Subang Jaya'])}",
           f"{name(i + 50)} - 01{random.randint(2, 9)}{random.randint(1000000, 9999999)}", random.choice(ALLERGIES),
           reg.strftime("%Y-%m-%d %H:%M:%S"), reg.strftime("%Y-%m-%d %H:%M:%S"), None))
        cov = None
        if random.random() < 0.4:
            prov = random.choice(PROVIDERS)
            cov = prov[0]
            x("INSERT INTO patient_coverage VALUES (?,?,?,?,?)", (f"CV{len(patients) + 1:07d}", pid, prov[0],
              f"{prov[1][:2].upper()}{random.randint(100000, 999999)}", (today + timedelta(days=random.randint(60, 600))).strftime("%Y-%m-%d")))
        patients.append(dict(patient_id=pid, age=age, branch=br, cov=cov))
    # The demo patient from the report scenario: registered in PJ, visits other branches
    x("UPDATE patient SET full_name='Lee Wei Ming', allergies='Penicillin', ic_passport_no='880512105523' WHERE patient_id='PT0000001'")

    # ---- D2 schedules ---------------------------------------------------
    docs = [s for s in staff if s["role"] in ("doctor", "dentist")]
    ns = 0
    for dd in range(-45, 15):
        day = today + timedelta(days=dd)
        for d in docs:
            ns += 1
            leave = "On Leave" if random.random() < 0.04 and dd > 1 else "On Duty"
            end = "13:00" if day.weekday() >= 5 else ("21:00" if d["role"] != "dentist" else "17:00")
            x("INSERT INTO staff_schedule VALUES (?,?,?,?,?,?,?)", (f"SS{ns:07d}", d["staff_id"], d["branch_id"],
              day.strftime("%Y-%m-%d"), "09:00", end, leave))

    # ---- History: appointments -> queue -> consultation -> Rx -> bill -> payment -> claim ----------
    c = dict(ap=0, qe=0, cn=0, rx=0, ri=0, bl=0, bi=0, py=0, cl=0, nt=0)
    def nid(k, pre):
        c[k] += 1
        return f"{pre}{c[k]:07d}"
    stock_use = {}
    for dd in range(-45, 8):
        day = today + timedelta(days=dd)
        for d in docs:
            if x("SELECT leave_status FROM staff_schedule WHERE staff_id=? AND work_date=?", (d["staff_id"], day.strftime("%Y-%m-%d"))
                 ).fetchone()[0] != "On Duty":
                continue
            hours = 4 if day.weekday() >= 5 else (8 if d["role"] == "dentist" else 12)
            fill = random.uniform(0.3, 0.6) if dd <= 0 else random.uniform(0.1, 0.45) / (1 + dd * 0.2)
            slots = random.sample(range(hours * 3), int(hours * 3 * fill))
            for sl in sorted(slots):
                t = day + timedelta(hours=9, minutes=20 * sl)
                svc = d["specialisation"]
                pool = [p for p in patients if (p["age"] <= 12) == (svc == "Paediatrics")] if svc != "Dental" else patients
                p = random.choice(pool if random.random() < 0.85 else patients)
                aid = nid("ap", "AP")
                walk = random.random() < 0.25
                if dd < 0 or (dd == 0 and t < datetime.now() - timedelta(minutes=40)):
                    status = random.choices(["Completed", "Cancelled", "No-show"], [86, 9, 5])[0]
                else:
                    status = "Booked"
                x("INSERT INTO appointment VALUES (?,?,?,?,?,?,?,?)", (aid, p["patient_id"], d["staff_id"], d["branch_id"], svc,
                  t.strftime("%Y-%m-%d %H:%M"), "Walk-in" if walk and status != "Booked" else random.choice(["Phone", "Phone", "Counter"]), status))
                if status != "Completed":
                    continue
                qid = nid("qe", "QE")
                x("INSERT INTO queue_entry VALUES (?,?,?,?,?)", (qid, aid, f"{'W' if walk else 'A'}{c['qe'] % 120 + 1:03d}",
                  (t - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"), "Done"))
                sym, dx, tx = random.choice(DIAG[svc])
                charges = [{"item_type": "Consultation", "description": f"{svc} consultation", "quantity": 1, "unit_price": FEES[svc]}]
                if svc == "Dental":
                    pr = next(q for q in PROCEDURES if q["description"] == ("Scaling & polishing" if "calculus" in dx else "Tooth filling (composite)"))
                    charges.append({**pr, "quantity": 1})
                elif "immunisation" in dx:
                    charges.append({**PROCEDURES[4], "quantity": 1})
                elif random.random() < 0.08:
                    charges.append({**random.choice(PROCEDURES[:3]), "quantity": 1})
                cid = nid("cn", "CN")
                vit = {"temp": round(random.uniform(36.4, 38.6), 1), "bp": f"{random.randint(105, 150)}/{random.randint(65, 95)}",
                       "pulse": random.randint(64, 105), "weight": random.randint(10, 30) if p["age"] <= 12 else random.randint(48, 92)}
                x("INSERT INTO consultation VALUES (?,?,?,?,?,?,?,?,?,?,?)", (cid, qid, p["patient_id"], d["staff_id"], json.dumps(vit),
                  sym, dx, tx, (t + timedelta(days=90)).strftime("%Y-%m-%d") if "follow up" in dx else None,
                  t.strftime("%Y-%m-%d %H:%M:%S"), json.dumps(charges)))
                lines = list(charges)
                if dx in RX_FOR:
                    rx = nid("rx", "RX")
                    x("INSERT INTO prescription VALUES (?,?,?,?)", (rx, cid, t.strftime("%Y-%m-%d %H:%M:%S"), "Dispensed"))
                    for med, dose, q in RX_FOR[dx]:
                        bid = x("""SELECT batch_id FROM stock_batch WHERE medication_id=? AND branch_id=? ORDER BY expiry_date LIMIT 1""",
                                (med, d["branch_id"])).fetchone()[0]
                        stock_use[bid] = stock_use.get(bid, 0) + q
                        x("INSERT INTO prescription_item VALUES (?,?,?,?,?,?)", (nid("ri", "RI"), rx, med, bid, dose, q))
                        m = next(mm for mm in MEDS if mm[0] == med)
                        lines.append({"item_type": "Medicine", "description": f"{m[1]} ({dose})", "quantity": q, "unit_price": m[4]})
                total = round(sum(l["quantity"] * l["unit_price"] for l in lines), 2)
                prov = next((pp for pp in PROVIDERS if pp[0] == p["cov"]), None)
                payer = "Self-pay" if not prov else ("Insurance" if "Insurance" in prov[1] else "Panel")
                share = total if payer == "Self-pay" else round(total * prov[5], 2)
                bl = nid("bl", "BL")
                x("INSERT INTO bill VALUES (?,?,?,?,?,?,?,?,?,?)", (bl, cid, p["patient_id"], d["branch_id"],
                  (t + timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S"), payer, total, share, 0, "Paid"))
                for l in lines:
                    x("INSERT INTO bill_item VALUES (?,?,?,?,?,?,?)", (nid("bi", "BI"), bl, l["item_type"], l["description"],
                      l["quantity"], l["unit_price"], round(l["quantity"] * l["unit_price"], 2)))
                if share > 0:
                    py = nid("py", "PY")
                    meth = random.choices(["Cash", "Card", "E-wallet"], [40, 35, 25])[0]
                    when = (t + timedelta(minutes=27)).strftime("%Y-%m-%d %H:%M:%S")
                    staff_rec = next(s for s in staff if s["branch_id"] == d["branch_id"] and s["role"] == "receptionist")
                    x("INSERT INTO payment VALUES (?,?,?,?,?,?,?,?,?)", (py, bl, when, meth, share,
                      None if meth == "Cash" else f"{'APV' if meth == 'Card' else 'TNG'}{random.randint(100000, 999999)}",
                      staff_rec["staff_id"], "RC" + py[2:], when))
                if payer != "Self-pay":
                    age_days = -dd
                    st = ("Draft" if age_days < 4 else "Submitted" if age_days < 12 else
                          random.choices(["Approved", "Paid", "Rejected", "Submitted"], [35, 45, 8, 12])[0])
                    amt = round(total - share, 2)
                    x("INSERT INTO claim VALUES (?,?,?,?,?,?,?)", (nid("cl", "CL"), bl, prov[0], st, amt,
                      amt if st in ("Approved", "Paid") else (0 if st == "Rejected" else None),
                      None if st == "Draft" else (t + timedelta(days=3)).strftime("%Y-%m-%d")))
    for bid, used in stock_use.items():
        x("UPDATE stock_batch SET quantity_on_hand=MAX(quantity_on_hand-?/6, 0) WHERE batch_id=?", (used, bid))

    # ---- Today at PJ: a live queue in different stages ------------------
    now = datetime.now()
    pj_docs = [d for d in docs if d["branch_id"] == "B01" and d["role"] == "doctor"]
    stages = ["Waiting", "Waiting", "Vitals Taken", "Vitals Taken", "Waiting", "Waiting"]
    kids = [p for p in patients if p["age"] <= 12]
    adults = [p for p in patients if p["age"] > 12]
    for k in range(6):
        d = pj_docs[k % 2]
        p = (kids if d["specialisation"] == "Paediatrics" else adults)[k * 7 % 40]
        aid = nid("ap", "AP")
        t = now - timedelta(minutes=55 - k * 8)
        x("INSERT INTO appointment VALUES (?,?,?,?,?,?,?,?)", (aid, p["patient_id"], d["staff_id"], "B01", d["specialisation"],
          t.strftime("%Y-%m-%d %H:%M:%S"), "Walk-in" if k in (1, 4) else "Phone", "Checked-in"))
        qid = nid("qe", "QE")
        x("INSERT INTO queue_entry VALUES (?,?,?,?,?)", (qid, aid, f"{'W' if k in (1, 4) else 'A'}{k + 1:03d}",
          t.strftime("%Y-%m-%d %H:%M:%S"), stages[k]))
        if stages[k] == "Vitals Taken":
            x("INSERT INTO consultation(consultation_id, queue_id, patient_id, staff_id, vitals, visit_date) VALUES (?,?,?,?,?,?)",
              (nid("cn", "CN"), qid, p["patient_id"], d["staff_id"], json.dumps({"temp": 37.9, "bp": "128/84", "pulse": 92, "weight": 64}),
               now.strftime("%Y-%m-%d %H:%M:%S")))
    # Guarantee Lee Wei Ming (PT0000001) has an appointment today at PJ for the walkthrough
    gp = next(s for s in staff if s["branch_id"] == "B01" and s["specialisation"] == "General Practice")
    x("""INSERT OR IGNORE INTO appointment VALUES (?,?,?,?,?,?,?,?)""", (nid("ap", "AP"), "PT0000001", gp["staff_id"], "B01",
      "General Practice", (now + timedelta(days=1)).strftime("%Y-%m-%d") + " 10:00", "Phone", "Booked"))

    # ---- 8.0 message log + staff alerts --------------------------------
    for (aid, pid, dt) in x("""SELECT appointment_id, patient_id, appointment_datetime FROM appointment ORDER BY appointment_id DESC
                               LIMIT 25""").fetchall():
        x("INSERT INTO notification VALUES (?,?,?,?,?,?,?)", (nid("nt", "NT"), pid, None, "Appointment Confirmation",
          f"SFC: your appointment {aid} on {dt} is confirmed.", random.choice(["Delivered"] * 9 + ["Failed"]),
          (now - timedelta(hours=random.randint(1, 72))).strftime("%Y-%m-%d %H:%M:%S")))
    for s in staff:
        if s["role"] in ("pharmacy", "branch_manager", "head_office") and s["branch_id"] in ("B01", "B03"):
            x("INSERT INTO notification VALUES (?,?,?,?,?,?,?)", (nid("nt", "NT"), None, s["staff_id"], "Stock Alert",
              "Low stock: Salbutamol 100mcg inhaler at 4 (reorder level 15)." if s["branch_id"] == "B01" else
              "Low stock: Paracetamol 500mg tab at 40 (reorder level 200).", "Unread", now.strftime("%Y-%m-%d %H:%M:%S")))
        if s["role"] == "head_office":
            x("INSERT INTO notification VALUES (?,?,?,?,?,?,?)", (nid("nt", "NT"), None, s["staff_id"], "Stock Alert",
              "Transfer TR0000001 requested: 200 units to B03.", "Unread", now.strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()
    from . import db as _db
    _old, _db.DB_PATH = _db.DB_PATH, path
    try:
        _db.migrate()
    finally:
        _db.DB_PATH = _old
    return path


if __name__ == "__main__":
    print("Demo database created at", build())
    print("All demo accounts use the password:", DEMO_PASSWORD)
