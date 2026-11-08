"""Back-end test suite for the SFC Clinic Management System.
One test class per DFD Level-0 process (1.0 - 9.0) plus authentication and a robustness sweep.
Uses a throw-away database, so your real data/cms.db is never touched.

Run from the project folder:   python -m unittest tests.test_api -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = os.path.join(tempfile.mkdtemp(), "test_cms.db")
os.environ["CMS_DB"] = TMP

from backend.seed import build, DEMO_PASSWORD  # noqa: E402
build(TMP)
from app import app, prepare  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402


class Client(FlaskClient):
    """Adds the anti-CSRF header the real front end sends with every change."""
    def open(self, *a, **kw):
        kw.setdefault("headers", {})
        if isinstance(kw["headers"], dict):
            kw["headers"].setdefault("X-Requested-With", "SFC-CMS")
        return super().open(*a, **kw)


app.test_client_class = Client
prepare()

TODAY = datetime.now().strftime("%Y-%m-%d")
TOMORROW = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
_ic = [880000000000]


def new_ic():
    _ic[0] += 7
    return str(_ic[0])


class Base(unittest.TestCase):
    def setUp(self):
        self.c = app.test_client()

    def login(self, user):
        self.c = app.test_client()
        r = self.c.post("/api/login", json={"username": user, "password": DEMO_PASSWORD})
        self.assertEqual(r.status_code, 200, r.json)
        return r

    def ok(self, r, code=200):
        self.assertEqual(r.status_code, code, f"{r.status_code}: {r.get_data(as_text=True)[:300]}")
        return r.json

    def register(self, **kw):
        self.login("reception.pj")
        d = dict(full_name=kw.pop("full_name", "Test Patient " + new_ic()[-4:]), ic_passport_no=new_ic(),
                 date_of_birth="1990-05-05", gender="Female", phone="0123456789",
                 emergency_contact="Kin - 0129998888", allergies="None known")
        d.update(kw)
        return self.ok(self.c.post("/api/patients", json=d))["patient_id"]

    def walk_in(self, pid, service="General Practice"):
        self.login("reception.pj")
        return self.ok(self.c.post("/api/walkin", json={"patient_id": pid, "service_type": service}))


# ------------------------------------------------------------------ authentication / 9.0 access
class T0Auth(Base):
    def test_login_ok_and_me(self):
        self.login("hq")
        self.assertEqual(self.ok(self.c.get("/api/me"))["user"]["role"], "head_office")

    def test_login_bad_password(self):
        r = self.c.post("/api/login", json={"username": "hq", "password": "nope"})
        self.assertEqual(r.status_code, 401)

    def test_login_empty_body(self):
        self.assertEqual(self.c.post("/api/login", data="x", content_type="text/plain").status_code, 401)

    def test_not_logged_in(self):
        self.assertEqual(self.c.get("/api/patients?q=lee").status_code, 401)

    def test_logout(self):
        self.login("hq")
        self.ok(self.c.post("/api/logout"))
        self.assertEqual(self.c.get("/api/me").status_code, 401)

    def test_idle_timeout(self):
        self.login("hq")
        with self.c.session_transaction() as s:
            s["seen"] -= 301
        r = self.c.get("/api/me")
        self.assertEqual(r.status_code, 401)
        self.assertIn("inactivity", r.json["error"])

    def test_role_matrix(self):
        """Every role may open only the processes it needs (FR-11)."""
        expect = {
            "reception.pj": {"/api/billing/ready": 200, "/api/consult/queue": 403, "/api/users": 403, "/api/reports/dashboard": 403},
            "nurse.pj": {"/api/consult/queue": 200, "/api/billing/ready": 403, "/api/stock": 403},
            "dr.rahman": {"/api/consult/queue": 200, "/api/claims": 403, "/api/users": 403},
            "pharmacy.pj": {"/api/pharmacy/queue": 200, "/api/billing/ready": 403, "/api/appointments": 403},
            "manager.pj": {"/api/reports/dashboard": 200, "/api/stock": 200, "/api/consult/queue": 403},
            "hq": {"/api/stock/network": 200, "/api/reports/dashboard": 200, "/api/patients?q=le": 403},
            "admin": {"/api/users": 200, "/api/audit": 200, "/api/billing/ready": 403},
        }
        for user, paths in expect.items():
            self.login(user)
            for p, code in paths.items():
                self.assertEqual(self.c.get(p).status_code, code, f"{user} {p}")

    def test_csrf_header_required(self):
        from flask.testing import FlaskClient as Plain
        c = Plain(app, app.response_class, use_cookies=True)
        self.assertEqual(c.post("/api/login", json={"username": "hq", "password": DEMO_PASSWORD}).status_code, 403)

    def test_security_headers_and_gzip(self):
        r = self.c.get("/", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers.get("Content-Encoding"), "gzip")
        self.assertNotIn("__V__", __import__("gzip").decompress(r.data).decode())

    def test_login_rate_limit(self):
        c = app.test_client()
        for _ in range(5):
            self.assertEqual(c.post("/api/login", json={"username": "reception.du", "password": "bad"}).status_code, 401)
        self.assertEqual(c.post("/api/login", json={"username": "reception.du", "password": DEMO_PASSWORD}).status_code, 429)

    def test_health(self):
        self.assertTrue(self.ok(self.c.get("/api/health"))["ok"])

    def test_change_password_flow(self):
        self.login("admin")
        u = next(u for u in self.ok(self.c.get("/api/users"))["users"] if u["username"] == "pharmacy.sj")
        temp = self.ok(self.c.post(f"/api/users/{u['user_id']}/reset"))["message"].split("Temporary password: ")[1].split()[0]
        c = app.test_client()
        r = c.post("/api/login", json={"username": "pharmacy.sj", "password": temp})
        self.assertTrue(r.json["must_change_password"])
        self.assertEqual(c.post("/api/password", json={"current": "x", "new": "Newpass123"}).status_code, 422)
        self.assertEqual(c.post("/api/password", json={"current": temp, "new": "short"}).status_code, 422)
        self.assertEqual(c.post("/api/password", json={"current": temp, "new": "Newpass123"}).status_code, 200)
        self.assertFalse(c.get("/api/me").json["must_change_password"])
        self.assertEqual(app.test_client().post("/api/login", json={"username": "pharmacy.sj", "password": "Newpass123"}).status_code, 200)

    def test_backup(self):
        from backend import backup
        path = backup.backup_now()
        self.assertTrue(os.path.getsize(path) > 100000)

    def test_deactivated_cannot_login(self):
        self.login("admin")
        u = next(u for u in self.ok(self.c.get("/api/users"))["users"] if u["username"] == "reception.sj")
        self.ok(self.c.put(f"/api/users/{u['user_id']}", json={**u, "account_status": "Deactivated"}))
        r = app.test_client().post("/api/login", json={"username": "reception.sj", "password": DEMO_PASSWORD})
        self.assertEqual(r.status_code, 401)
        self.ok(self.c.put(f"/api/users/{u['user_id']}", json={**u, "account_status": "Active"}))


# ------------------------------------------------------------------ 1.0
class T1Patients(Base):
    def test_register_search_view(self):
        pid = self.register(full_name="Zara Unique Name")
        res = self.ok(self.c.get("/api/patients?q=Zara Unique"))["results"]
        self.assertEqual(res[0]["patient_id"], pid)
        p = self.ok(self.c.get(f"/api/patients/{pid}"))
        self.assertEqual(p["registered_branch"], "SFC Petaling Jaya (SS2)")
        self.assertIsNone(p["coverage"])

    def test_search_by_ic_phone_id(self):
        ic = new_ic()
        pid = self.register(ic_passport_no=ic, phone="0171112233")
        for q in (ic, "0171112233", pid):
            self.assertIn(pid, [r["patient_id"] for r in self.ok(self.c.get("/api/patients?q=" + q))["results"]])

    def test_search_short_and_none(self):
        self.login("reception.pj")
        self.assertEqual(self.ok(self.c.get("/api/patients?q=a"))["results"], [])
        self.assertEqual(self.ok(self.c.get("/api/patients?q=qqqzzzxx"))["message"], "No record found.")

    def test_ic_with_dashes_normalised(self):
        pid = self.register(ic_passport_no="910101-14-5678")
        self.assertEqual(self.ok(self.c.get(f"/api/patients/{pid}"))["ic_passport_no"], "910101145678")

    def test_validation_errors(self):
        self.login("reception.pj")
        r = self.c.post("/api/patients", json={"ic_passport_no": "12", "date_of_birth": "2999-01-01", "phone": "12"})
        self.assertEqual(r.status_code, 422)
        f = r.json["fields"]
        for k in ("full_name", "ic_passport_no", "date_of_birth", "phone", "allergies", "gender", "emergency_contact"):
            self.assertIn(k, f)

    def test_bad_date_format(self):
        self.login("reception.pj")
        r = self.c.post("/api/patients", json={"full_name": "A", "ic_passport_no": new_ic(), "date_of_birth": "31/12/1990",
                                                "gender": "Male", "phone": "0123456789", "emergency_contact": "x", "allergies": "None"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("date_of_birth", r.json["fields"])

    def test_panel_needs_policy(self):
        self.login("reception.pj")
        r = self.c.post("/api/patients", json={"full_name": "A", "ic_passport_no": new_ic(), "date_of_birth": "1990-01-01",
                                                "gender": "Male", "phone": "0123456789", "emergency_contact": "x",
                                                "allergies": "None", "provider_id": "PP0000002"})
        self.assertIn("policy_no", r.json["fields"])

    def test_duplicate_exact_and_possible(self):
        ic = new_ic()
        self.register(ic_passport_no=ic, full_name="Dup Person", phone="0135550000", date_of_birth="1980-02-02")
        r = self.c.post("/api/patients", json={"full_name": "Other", "ic_passport_no": ic, "date_of_birth": "1980-02-02",
                                                "gender": "Male", "phone": "0135550000", "emergency_contact": "x", "allergies": "None"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json["duplicate"]["type"], "exact")
        body = {"full_name": "Dup Person", "ic_passport_no": new_ic(), "date_of_birth": "1980-02-02", "gender": "Male",
                "phone": "0135550000", "emergency_contact": "x", "allergies": "None"}
        r = self.c.post("/api/patients", json=body)
        self.assertEqual(r.json["duplicate"]["type"], "possible")
        self.ok(self.c.post("/api/patients", json={**body, "confirm_possible_duplicate": True}))

    def test_update_keeps_own_ic_and_stamps(self):
        pid = self.register()
        p = self.ok(self.c.get(f"/api/patients/{pid}"))
        p.update(phone="0199990000", provider_id="PP0000003", policy_no="PL123", valid_until="")
        self.ok(self.c.put(f"/api/patients/{pid}", json=p))
        q = self.ok(self.c.get(f"/api/patients/{pid}"))
        self.assertEqual(q["phone"], "0199990000")
        self.assertEqual(q["coverage"]["provider_id"], "PP0000003")
        self.assertIsNone(q["coverage"]["valid_until"])
        self.assertTrue(q["updated_by_name"])

    def test_update_to_someone_elses_ic(self):
        a, b = self.register(), self.register()
        pa = self.ok(self.c.get(f"/api/patients/{a}"))
        pb = self.ok(self.c.get(f"/api/patients/{b}"))
        r = self.c.put(f"/api/patients/{a}", json={**pa, "ic_passport_no": pb["ic_passport_no"]})
        self.assertEqual(r.status_code, 409)

    def test_update_unknown_patient(self):
        self.login("reception.pj")
        r = self.c.put("/api/patients/PT9999999", json={"full_name": "A", "ic_passport_no": new_ic(), "date_of_birth": "1990-01-01",
                                                         "gender": "Male", "phone": "0123456789", "emergency_contact": "x", "allergies": "N"})
        self.assertEqual(r.status_code, 404)

    def test_view_unknown(self):
        self.login("reception.pj")
        self.assertEqual(self.c.get("/api/patients/PT9999999").status_code, 404)

    def test_confirmation_sms_logged(self):
        pid = self.register()
        self.login("reception.pj")
        log = self.ok(self.c.get("/api/notifications/sms"))["log"]
        self.assertTrue(any(m["patient_id"] == pid and m["notification_type"] == "Registration Confirmation" for m in log))

    def test_nurse_cannot_register(self):
        self.login("nurse.pj")
        self.assertEqual(self.c.post("/api/patients", json={}).status_code, 403)

    def test_cross_branch_history_visible(self):
        """Problem 1: a record made at PJ can be found from Subang Jaya."""
        pid = self.register(full_name="Cross Branch Person")
        self.login("reception.sj")
        self.assertIn(pid, [r["patient_id"] for r in self.ok(self.c.get("/api/patients?q=Cross Branch"))["results"]])


# ------------------------------------------------------------------ 2.0
class T2Appointments(Base):
    def first_free(self, service="General Practice", date=TOMORROW, branch="B01"):
        docs = self.ok(self.c.get(f"/api/slots?branch_id={branch}&service={service}&date={date}"))["doctors"]
        for d in docs:
            for s in d["slots"]:
                if s["free"]:
                    return d["staff_id"], s["datetime"]
        self.fail("no free slot")

    def test_book_confirm_and_double_booking_blocked(self):
        pid = self.register()
        sid, dt = self.first_free()
        body = {"patient_id": pid, "staff_id": sid, "service_type": "General Practice", "appointment_datetime": dt}
        aid = self.ok(self.c.post("/api/appointments", json=body))["appointment_id"]
        self.assertEqual(self.c.post("/api/appointments", json=body).status_code, 409)
        free = self.ok(self.c.get(f"/api/slots?service=General Practice&date={TOMORROW}&staff_id={sid}"))["doctors"][0]["slots"]
        self.assertFalse(next(s for s in free if s["datetime"] == dt)["free"])
        lst = self.ok(self.c.get(f"/api/appointments?date={TOMORROW}"))["appointments"]
        self.assertIn(aid, [a["appointment_id"] for a in lst])

    def test_missing_fields(self):
        self.login("reception.pj")
        self.assertEqual(self.c.post("/api/appointments", json={}).status_code, 422)

    def test_past_slot_rejected(self):
        pid = self.register()
        sid = self.first_free()[0]
        r = self.c.post("/api/appointments", json={"patient_id": pid, "staff_id": sid, "service_type": "General Practice",
                                                    "appointment_datetime": "2020-01-01 09:00"})
        self.assertEqual(r.status_code, 409)

    def test_reschedule_keeps_history_and_cancel(self):
        pid = self.register()
        sid, dt = self.first_free()
        a1 = self.ok(self.c.post("/api/appointments", json={"patient_id": pid, "staff_id": sid, "service_type": "General Practice",
                                                             "appointment_datetime": dt}))["appointment_id"]
        sid2, dt2 = self.first_free()
        a2 = self.ok(self.c.post("/api/appointments", json={"patient_id": pid, "staff_id": sid2, "service_type": "General Practice",
                                                             "appointment_datetime": dt2, "reschedule_of": a1}))["appointment_id"]
        appts = {a["appointment_id"]: a["status"] for a in self.ok(self.c.get(f"/api/patients/{pid}"))["appointments"]}
        self.assertEqual(appts[a1], "Rescheduled")
        self.assertEqual(appts[a2], "Booked")
        self.ok(self.c.post(f"/api/appointments/{a2}/cancel"))
        appts = {a["appointment_id"]: a["status"] for a in self.ok(self.c.get(f"/api/patients/{pid}"))["appointments"]}
        self.assertEqual(appts[a2], "Cancelled")
        # the freed slot can be booked again
        self.ok(self.c.post("/api/appointments", json={"patient_id": pid, "staff_id": sid2, "service_type": "General Practice",
                                                        "appointment_datetime": dt2}))

    def test_cancel_unknown(self):
        self.login("reception.pj")
        self.assertEqual(self.c.post("/api/appointments/AP9999999/cancel").status_code, 404)

    def test_walkin_and_checkin_twice(self):
        pid = self.register()
        r = self.walk_in(pid)
        self.assertTrue(r["queue"]["queue_no"].startswith("W"))
        self.assertEqual(self.c.post(f"/api/appointments/{r['appointment_id']}/checkin").status_code, 409)
        q = self.ok(self.c.get("/api/queue"))["queue"]
        self.assertIn(r["queue"]["queue_id"], [x["queue_id"] for x in q])

    def test_walkin_bad_patient(self):
        self.login("reception.pj")
        self.assertEqual(self.c.post("/api/walkin", json={}).status_code, 422)
        self.assertEqual(self.c.post("/api/walkin", json={"patient_id": "PT9999999"}).status_code, 422)

    def test_checkin_unknown(self):
        self.login("reception.pj")
        self.assertEqual(self.c.post("/api/appointments/AP9999999/checkin").status_code, 404)

    def test_leave_blocks_slots(self):
        """2.1: a doctor on leave has no slots that day."""
        self.login("manager.pj")
        sch = self.ok(self.c.get(f"/api/schedules?from={TOMORROW}"))
        doc = sch["staff"][0]["staff_id"]
        day = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        self.ok(self.c.post("/api/schedules", json={"staff_id": doc, "work_date": day, "leave_status": "On Leave"}))
        self.login("reception.pj")
        docs = self.ok(self.c.get(f"/api/slots?date={day}&service=General Practice&branch_id=B01"))["doctors"]
        docs += self.ok(self.c.get(f"/api/slots?date={day}&service=Paediatrics&branch_id=B01"))["doctors"]
        self.assertNotIn(doc, [d["staff_id"] for d in docs])
        self.login("manager.pj")
        self.ok(self.c.post("/api/schedules", json={"staff_id": doc, "work_date": day, "start_time": "09:00",
                                                     "end_time": "17:00", "leave_status": "On Duty"}))

    def test_schedule_validation(self):
        self.login("manager.pj")
        self.assertEqual(self.c.post("/api/schedules", json={}).status_code, 422)
        self.assertEqual(self.c.post("/api/schedules", json={"staff_id": "ST0000003", "work_date": TOMORROW,
                                                              "start_time": "17:00", "end_time": "09:00"}).status_code, 422)
        self.assertEqual(self.c.post("/api/schedules", json={"staff_id": "ST9999999", "work_date": TOMORROW,
                                                              "start_time": "09:00", "end_time": "17:00"}).status_code, 422)

    def test_receptionist_cannot_edit_schedule(self):
        self.login("reception.pj")
        self.assertEqual(self.c.post("/api/schedules", json={}).status_code, 403)

    def test_doctor_sees_only_own_list(self):
        self.login("dr.rahman")
        me = self.ok(self.c.get("/api/me"))["user"]["staff_id"]
        lst = self.ok(self.c.get(f"/api/appointments?date={TODAY}"))["appointments"]
        self.assertTrue(all(a["staff_id"] == me for a in lst))

    def test_reminders(self):
        self.login("reception.pj")
        self.assertIn("reminder", self.ok(self.c.post("/api/reminders/run"))["message"])

    def test_dental_slots(self):
        self.login("reception.pj")
        docs = self.ok(self.c.get(f"/api/slots?service=Dental&date={TOMORROW}&branch_id=B01"))["doctors"]
        self.assertTrue(docs)
        none = self.ok(self.c.get(f"/api/slots?service=Dental&date={TOMORROW}&branch_id=B02"))["doctors"]
        self.assertEqual(none, [])


# ------------------------------------------------------------------ 3.0 -> 4.0 -> 5.0 -> 6.0 full visit
class T3to6Visit(Base):
    def visit(self, allergies="None known", meds=(("MD0000001", 10),), payer_provider=None, service="General Practice",
              procedures=()):
        kw = {"allergies": allergies}
        if payer_provider:
            kw.update(provider_id=payer_provider, policy_no="P-1")
        pid = self.register(**kw)
        q = self.walk_in(pid, service)["queue"]
        self.login("nurse.pj")
        self.ok(self.c.post(f"/api/consult/{q['queue_id']}/vitals", json={"temp": 37.2, "bp": "120/80", "pulse": 80, "weight": 60}))
        doctor = "dr.izzah" if service == "Paediatrics" else "dr.aminah" if service == "Dental" else None
        if not doctor:
            # walk-in goes to whichever GP has the first free slot
            for d in ("dr.rahman",):
                self.login(d)
        else:
            self.login(doctor)
        return pid, q

    def test_vitals_validation(self):
        pid = self.register()
        q = self.walk_in(pid)["queue"]
        self.login("nurse.pj")
        for bad in ({"temp": 50, "bp": "120/80"}, {"temp": 37, "bp": "abc"}, {"temp": "x", "bp": "120/80"}, {}):
            self.assertEqual(self.c.post(f"/api/consult/{q['queue_id']}/vitals", json=bad).status_code, 422, bad)

    def test_full_self_pay_visit(self):
        pid, q = self.visit()
        v = self.ok(self.c.get(f"/api/consult/{q['queue_id']}"))
        self.assertEqual(v["consultation"]["vitals"]["bp"], "120/80")
        self.assertEqual(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={}).status_code, 422)
        r = self.ok(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={
            "diagnosis": "URTI", "procedures": ["Blood glucose test"],
            "prescription": [{"medication_id": "MD0000001", "dosage": "1 tab", "quantity": 10}]}))
        rx, cid = r["prescription_id"], r["consultation_id"]
        # billing must wait for pharmacy
        self.login("reception.pj")
        self.assertEqual(self.c.post(f"/api/billing/generate/{cid}").status_code, 409)
        # 4.0 dispense
        self.login("pharmacy.pj")
        before = sum(m["on_hand"] for m in self.ok(self.c.get("/api/stock"))["medications"] if m["medication_id"] == "MD0000001")
        self.assertEqual(self.c.post(f"/api/pharmacy/dispense/{rx}", json={}).status_code, 422)  # allergy box not ticked
        d = self.ok(self.c.post(f"/api/pharmacy/dispense/{rx}", json={"allergy_checked": True}))
        self.assertEqual(len(d["labels"]), 1)
        after = sum(m["on_hand"] for m in self.ok(self.c.get("/api/stock"))["medications"] if m["medication_id"] == "MD0000001")
        self.assertEqual(before - after, 10)
        self.assertEqual(self.c.post(f"/api/pharmacy/dispense/{rx}", json={"allergy_checked": True}).status_code, 409)
        # 5.0 billing
        self.login("reception.pj")
        b = self.ok(self.c.post(f"/api/billing/generate/{cid}"))["bill"]
        self.assertEqual(b["payer_type"], "Self-pay")
        self.assertAlmostEqual(b["total_amount"], 35 + 10 + 10 * 0.30)
        self.assertEqual(self.c.post(f"/api/billing/generate/{cid}").status_code, 409)
        bid = b["bill_id"]
        for bad in ({"payment_method": "Bitcoin", "amount": 1}, {"payment_method": "Cash", "amount": 0},
                    {"payment_method": "Cash", "amount": -5}, {"payment_method": "Cash", "amount": "abc"},
                    {"payment_method": "Card", "amount": 1}, {"payment_method": "Cash", "amount": 9999}):
            self.assertEqual(self.c.post(f"/api/billing/{bid}/pay", json=bad).status_code, 422, bad)
        p1 = self.ok(self.c.post(f"/api/billing/{bid}/pay", json={"payment_method": "Cash", "amount": 20}))
        self.assertEqual(p1["bill"]["bill_status"], "Partially Paid")
        p2 = self.ok(self.c.post(f"/api/billing/{bid}/pay", json={"payment_method": "E-wallet", "amount": b["total_amount"] - 20,
                                                                  "reference_no": "TNG1"}))
        self.assertEqual(p2["bill"]["bill_status"], "Paid")
        self.assertEqual(p2["bill"]["outstanding_balance"], 0)
        self.assertNotEqual(p1["receipt_no"], p2["receipt_no"])
        self.assertEqual(self.c.post(f"/api/billing/{bid}/pay", json={"payment_method": "Cash", "amount": 1}).status_code, 422)
        q2 = [x for x in self.ok(self.c.get("/api/queue"))["queue"] if x["queue_id"] == q["queue_id"]][0]
        self.assertEqual(q2["queue_status"], "Done")

    def test_float_rounding_full_payment(self):
        """Paying exactly the shown balance must always close the bill."""
        pid, q = self.visit()
        r = self.ok(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={
            "diagnosis": "x", "prescription": [{"medication_id": "MD0000003", "quantity": 7}]}))
        self.login("pharmacy.pj")
        self.ok(self.c.post(f"/api/pharmacy/dispense/{r['prescription_id']}", json={"allergy_checked": True}))
        self.login("reception.pj")
        b = self.ok(self.c.post(f"/api/billing/generate/{r['consultation_id']}"))["bill"]
        self.ok(self.c.post(f"/api/billing/{b['bill_id']}/pay", json={"payment_method": "Cash", "amount": 0.1}))
        rest = self.ok(self.c.get(f"/api/billing/{b['bill_id']}"))["outstanding_balance"]
        p = self.ok(self.c.post(f"/api/billing/{b['bill_id']}/pay", json={"payment_method": "Cash", "amount": rest}))
        self.assertEqual(p["bill"]["bill_status"], "Paid")

    def test_allergy_class_alert_and_override(self):
        pid, q = self.visit(allergies="Penicillin")
        body = {"diagnosis": "Tonsillitis", "prescription": [{"medication_id": "MD0000002", "quantity": 15}]}
        r = self.c.post(f"/api/consult/{q['queue_id']}/complete", json=body)
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json["allergy"])
        r = self.ok(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={**body, "override_allergy": True}))
        self.login("pharmacy.pj")
        rx = [p for p in self.ok(self.c.get("/api/pharmacy/queue"))["prescriptions"] if p["prescription_id"] == r["prescription_id"]][0]
        self.assertEqual(rx["allergy_conflicts"], ["Amoxicillin 250mg cap"])

    def test_bad_medication_and_unknown_queue(self):
        pid, q = self.visit()
        r = self.c.post(f"/api/consult/{q['queue_id']}/complete",
                        json={"diagnosis": "x", "prescription": [{"medication_id": "MD9999999", "quantity": 1}]})
        self.assertEqual(r.status_code, 422)
        r = self.c.post(f"/api/consult/{q['queue_id']}/complete",
                        json={"diagnosis": "x", "prescription": [{"medication_id": "MD0000001", "quantity": "lots"}]})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.c.get("/api/consult/QE9999999").status_code, 404)
        self.assertEqual(self.c.post("/api/consult/QE9999999/complete", json={"diagnosis": "x"}).status_code, 404)

    def test_complete_twice_blocked(self):
        pid, q = self.visit()
        self.ok(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={"diagnosis": "x"}))
        self.assertEqual(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={"diagnosis": "y"}).status_code, 409)

    def test_nurse_cannot_complete(self):
        pid = self.register()
        q = self.walk_in(pid)["queue"]
        self.login("nurse.pj")
        self.assertEqual(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={"diagnosis": "x"}).status_code, 403)

    def test_status_update(self):
        pid = self.register()
        q = self.walk_in(pid)["queue"]
        self.login("nurse.pj")
        self.assertEqual(self.c.post(f"/api/consult/{q['queue_id']}/status", json={"status": "Bogus"}).status_code, 422)
        self.ok(self.c.post(f"/api/consult/{q['queue_id']}/status", json={"status": "Waiting"}))

    def test_no_prescription_goes_to_paying(self):
        pid, q = self.visit()
        r = self.ok(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={"diagnosis": "Review only"}))
        self.assertIsNone(r["prescription_id"])
        self.login("reception.pj")
        self.assertIn(r["consultation_id"], [p["consultation_id"] for p in self.ok(self.c.get("/api/billing/ready"))["pending"]])

    def test_panel_bill_copay_and_claim_lifecycle(self):
        pid, q = self.visit(payer_provider="PP0000002")  # MyHealth Panel, 10 % co-pay
        r = self.ok(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={"diagnosis": "x"}))
        self.login("reception.pj")
        b = self.ok(self.c.post(f"/api/billing/generate/{r['consultation_id']}"))["bill"]
        self.assertEqual(b["payer_type"], "Panel")
        self.assertAlmostEqual(b["outstanding_balance"], 3.5)
        self.assertAlmostEqual(b["panel_share"], 31.5)
        self.ok(self.c.post(f"/api/billing/{b['bill_id']}/pay", json={"payment_method": "Cash", "amount": 3.5}))
        # 6.0
        self.ok(self.c.post("/api/claims/generate"))
        cl = [c for c in self.ok(self.c.get("/api/claims"))["claims"] if c["bill_id"] == b["bill_id"]][0]
        self.assertEqual(cl["claim_status"], "Draft")
        self.assertAlmostEqual(cl["amount_claimed"], 31.5)
        self.ok(self.c.post("/api/claims/submit", json={"ids": [cl["claim_id"]]}))
        self.assertEqual(self.c.post(f"/api/claims/{cl['claim_id']}/decision", json={"status": "Approved", "amount_approved": 999}).status_code, 422)
        self.assertEqual(self.c.post(f"/api/claims/{cl['claim_id']}/decision", json={"status": "Approved", "amount_approved": "abc"}).status_code, 422)
        self.assertEqual(self.c.post(f"/api/claims/{cl['claim_id']}/decision", json={"status": "Maybe"}).status_code, 422)
        self.ok(self.c.post(f"/api/claims/{cl['claim_id']}/decision", json={"status": "Rejected", "reason": "Expired"}))
        self.login("manager.pj")
        self.assertTrue(any(a["notification_type"] == "Rejected Claim" and cl["claim_id"] in a["message"]
                            for a in self.ok(self.c.get("/api/notifications"))["alerts"]))
        self.ok(self.c.post(f"/api/claims/{cl['claim_id']}/resubmit"))
        self.ok(self.c.post("/api/claims/submit", json={"ids": [cl["claim_id"]]}))
        self.ok(self.c.post(f"/api/claims/{cl['claim_id']}/decision", json={"status": "Paid"}))
        c2 = [c for c in self.ok(self.c.get("/api/claims"))["claims"] if c["claim_id"] == cl["claim_id"]][0]
        self.assertEqual((c2["claim_status"], c2["amount_approved"]), ("Paid", 31.5))

    def test_zero_copay_panel_bill_auto_paid(self):
        pid, q = self.visit(payer_provider="PP0000001")  # 0 % co-pay
        r = self.ok(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={"diagnosis": "x"}))
        self.login("reception.pj")
        b = self.ok(self.c.post(f"/api/billing/generate/{r['consultation_id']}"))["bill"]
        self.assertEqual((b["bill_status"], b["outstanding_balance"]), ("Paid", 0))

    def test_insurance_payer_type(self):
        pid, q = self.visit(payer_provider="PP0000003")
        r = self.ok(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={"diagnosis": "x"}))
        self.login("reception.pj")
        self.assertEqual(self.ok(self.c.post(f"/api/billing/generate/{r['consultation_id']}"))["bill"]["payer_type"], "Insurance")

    def test_dental_procedure_billed(self):
        pid, q = self.visit(service="Dental")
        r = self.ok(self.c.post(f"/api/consult/{q['queue_id']}/complete", json={"diagnosis": "Caries", "procedures": ["Tooth filling (composite)"]}))
        self.login("reception.pj")
        b = self.ok(self.c.post(f"/api/billing/generate/{r['consultation_id']}"))["bill"]
        self.assertEqual(b["total_amount"], 60 + 120)

    def test_billing_unknown(self):
        self.login("reception.pj")
        self.assertEqual(self.c.post("/api/billing/generate/CN9999999").status_code, 404)
        self.assertEqual(self.c.get("/api/billing/BL9999999").status_code, 404)
        self.assertEqual(self.c.post("/api/billing/BL9999999/pay", json={"payment_method": "Cash", "amount": 1}).status_code, 422)

    def test_claims_bad_inputs(self):
        self.login("reception.pj")
        self.assertEqual(self.c.post("/api/claims/CL9999999/decision", json={"status": "Paid"}).status_code, 422)
        self.assertEqual(self.c.post("/api/claims/submit", json={"ids": "CL1"}).status_code, 422)
        self.assertEqual(self.c.post("/api/claims/CL9999999/resubmit").status_code, 404)

    def test_provider_rules(self):
        self.login("manager.pj")
        for bad in ({"copay_rate": 2}, {"copay_rate": "x"}, {}):
            self.assertEqual(self.c.put("/api/providers/PP0000004", json=bad).status_code, 422)
        self.ok(self.c.put("/api/providers/PP0000004", json={"copay_rate": 0.15, "coverage_rules": "OK"}))
        self.assertEqual(self.c.put("/api/providers/PP9999999", json={"copay_rate": 0.1}).status_code, 404)


# ------------------------------------------------------------------ 4.0 stock
class T4Stock(Base):
    def test_receive_adjust_lists(self):
        self.login("pharmacy.pj")
        future = (datetime.now() + timedelta(days=400)).strftime("%Y-%m-%d")
        for bad in ({}, {"medication_id": "MD0000001", "batch_no": "X", "expiry_date": future, "quantity": "abc"},
                    {"medication_id": "MD0000001", "batch_no": "X", "expiry_date": "2020-01-01", "quantity": 5},
                    {"medication_id": "MD9999999", "batch_no": "X", "expiry_date": future, "quantity": 5}):
            self.assertEqual(self.c.post("/api/stock/receive", json=bad).status_code, 422, bad)
        self.ok(self.c.post("/api/stock/receive", json={"medication_id": "MD0000004", "supplier_id": "SP0000001",
                                                         "batch_no": "TESTRCV", "expiry_date": future, "quantity": 50}))
        b = [x for x in self.ok(self.c.get("/api/stock"))["batches"] if x["batch_no"] == "TESTRCV"][0]
        for bad in ({"batch_id": b["batch_id"], "reason": "Damaged", "quantity": "abc"},
                    {"batch_id": b["batch_id"], "reason": "Stolen", "quantity": 1},
                    {"batch_id": b["batch_id"], "reason": "Damaged", "quantity": 9999}):
            self.assertEqual(self.c.post("/api/stock/adjust", json=bad).status_code, 422, bad)
        self.ok(self.c.post("/api/stock/adjust", json={"batch_id": b["batch_id"], "reason": "Damaged", "quantity": 5}))
        self.ok(self.c.post("/api/stock/adjust", json={"batch_id": b["batch_id"], "reason": "Count correction (+)", "quantity": 2}))
        b2 = [x for x in self.ok(self.c.get("/api/stock"))["batches"] if x["batch_id"] == b["batch_id"]][0]
        self.assertEqual(b2["quantity_on_hand"], 47)

    def test_transfer_request_and_approval(self):
        self.login("pharmacy.pj")
        b = self.ok(self.c.get("/api/stock"))["batches"][0]
        for bad in ({}, {"batch_id": b["batch_id"], "to_branch_id": "B01", "quantity": 1},
                    {"batch_id": b["batch_id"], "to_branch_id": "B02", "quantity": "x"},
                    {"batch_id": b["batch_id"], "to_branch_id": "B02", "quantity": 10 ** 6},
                    {"batch_id": b["batch_id"], "to_branch_id": "B99", "quantity": 1}):
            self.assertEqual(self.c.post("/api/stock/transfer", json=bad).status_code, 422, bad)
        self.ok(self.c.post("/api/stock/transfer", json={"batch_id": b["batch_id"], "to_branch_id": "B02", "quantity": 1}))
        self.assertEqual(self.c.post("/api/stock/transfer/TR0000001/approve").status_code, 403)  # pharmacy cannot approve
        self.login("hq")
        t = [t for t in self.ok(self.c.get("/api/stock?branch_id=B01"))["transfers"] if t["transfer_status"] == "Requested"
             and t["batch_id"] == b["batch_id"]][0]
        self.ok(self.c.post(f"/api/stock/transfer/{t['transfer_id']}/approve"))
        self.assertEqual(self.c.post(f"/api/stock/transfer/{t['transfer_id']}/approve").status_code, 409)
        self.assertEqual(self.c.post("/api/stock/transfer/TR0000001/maybe").status_code, 422)
        self.assertEqual(self.c.post("/api/stock/transfer/TR9999999/approve").status_code, 409)

    def test_network_view(self):
        self.login("hq")
        n = self.ok(self.c.get("/api/stock/network"))
        self.assertEqual(len(n["cells"]), 15 * 5)

    def test_low_stock_alert(self):
        """Dispensing below reorder level alerts head office (4.0 -> 8.0 Stock Alert)."""
        self.login("pharmacy.pj")
        b = [x for x in self.ok(self.c.get("/api/stock"))["batches"] if x["medication_id"] == "MD0000009"][0]
        self.ok(self.c.post("/api/stock/adjust", json={"batch_id": b["batch_id"], "reason": "Damaged", "quantity": 1}))
        self.login("hq")
        self.assertTrue(any("Salbutamol" in a["message"] for a in self.ok(self.c.get("/api/notifications"))["alerts"]))


# ------------------------------------------------------------------ 7.0
class T7Reports(Base):
    def test_dashboard_scopes_and_filters(self):
        self.login("hq")
        d = self.ok(self.c.get("/api/reports/dashboard"))
        self.assertEqual(d["filters"]["branch_id"], "ALL")
        self.assertEqual(len(d["by_branch"]), 5)
        self.assertGreater(d["kpi"]["collected"], 0)
        d2 = self.ok(self.c.get(f"/api/reports/dashboard?branch_id=B03&service=Paediatrics&from={TODAY}&to={TODAY}"))
        self.assertEqual(d2["filters"]["branch_id"], "B03")
        self.login("manager.pj")
        self.assertEqual(self.ok(self.c.get("/api/reports/dashboard?branch_id=B05"))["filters"]["branch_id"], "B01")

    def test_bad_dates(self):
        self.login("hq")
        self.assertEqual(self.c.get("/api/reports/dashboard?from=garbage").status_code, 422)
        self.assertEqual(self.c.get(f"/api/reports/dashboard?from={TODAY}&to=2000-01-01").status_code, 422)

    def test_exports(self):
        self.login("hq")
        for k in ("revenue", "appointments", "claims", "stock", "patients"):
            r = self.c.get(f"/api/reports/export/{k}")
            self.assertEqual(r.status_code, 200, k)
            self.assertIn("text/csv", r.content_type)
            self.assertGreater(len(r.get_data(as_text=True).splitlines()), 2, k)
        self.assertEqual(self.c.get("/api/reports/export/salaries").status_code, 404)


# ------------------------------------------------------------------ 8.0
class T8Notifications(Base):
    def test_alerts_read_and_sms(self):
        self.login("hq")
        n = self.ok(self.c.get("/api/notifications"))
        self.assertGreater(n["unread"], 0)
        self.ok(self.c.post("/api/notifications/read"))
        self.assertEqual(self.ok(self.c.get("/api/notifications"))["unread"], 0)
        self.assertTrue(self.ok(self.c.get("/api/notifications/sms"))["log"])

    def test_failed_sms_logged(self):
        from backend.p8_notify import sms_gateway
        self.assertEqual(sms_gateway("12", "x"), "Failed")
        self.assertEqual(sms_gateway("012-345 6789", "x"), "Delivered")


# ------------------------------------------------------------------ 9.0
class T9Users(Base):
    def test_create_edit_reset_and_audit(self):
        self.login("admin")
        self.assertEqual(self.c.post("/api/users", json={"full_name": "X", "role": "nurse", "branch_id": "B02",
                                                          "username": "weak.pw", "password": "abc"}).status_code, 422)
        self.assertEqual(self.c.post("/api/users", json={"full_name": "X", "role": "pilot", "branch_id": "B02",
                                                          "username": "x1", "password": "abcdefg12"}).status_code, 422)
        self.assertEqual(self.c.post("/api/users", json={"full_name": "X", "role": "nurse", "branch_id": "B02",
                                                          "username": "hq", "password": "abcdefg12"}).status_code, 409)
        self.ok(self.c.post("/api/users", json={"full_name": "New Nurse", "role": "nurse", "branch_id": "B02",
                                                 "username": "nurse.new", "password": "Welcome123"}))
        app.test_client().post("/api/login", json={"username": "nurse.new", "password": "Welcome123"})
        u = next(u for u in self.ok(self.c.get("/api/users"))["users"] if u["username"] == "nurse.new")
        self.assertEqual(self.c.put(f"/api/users/{u['user_id']}", json={"role": "nurse"}).status_code, 422)
        self.ok(self.c.put(f"/api/users/{u['user_id']}", json={**u, "role": "receptionist"}))
        msg = self.ok(self.c.post(f"/api/users/{u['user_id']}/reset"))["message"]
        temp = msg.split("Temporary password: ")[1].split()[0]
        self.assertEqual(app.test_client().post("/api/login", json={"username": "nurse.new", "password": temp}).status_code, 200)
        self.assertEqual(self.c.post("/api/users/US9999999/reset").status_code, 404)
        log = self.ok(self.c.get("/api/audit?q=nurse.new"))["log"]
        self.assertTrue(log)

    def test_admin_cannot_lock_self_out(self):
        self.login("admin")
        me = next(u for u in self.ok(self.c.get("/api/users"))["users"] if u["username"] == "admin")
        r = self.c.put(f"/api/users/{me['user_id']}", json={**me, "account_status": "Deactivated"})
        self.assertEqual(r.status_code, 422)
        r = self.c.put(f"/api/users/{me['user_id']}", json={**me, "role": "nurse"})
        self.assertEqual(r.status_code, 422)

    def test_audit_records_patient_view(self):
        pid = self.register()
        self.c.get(f"/api/patients/{pid}")
        self.login("admin")
        self.assertTrue(any(l["action"] == "VIEW" for l in self.ok(self.c.get(f"/api/audit?q={pid}"))["log"]))


# ------------------------------------------------------------------ access rules added after the first test run
class T10Rules(Base):
    def test_walkin_twice_same_day(self):
        pid = self.register()
        self.walk_in(pid)
        self.assertEqual(self.c.post("/api/walkin", json={"patient_id": pid}).status_code, 409)

    def test_receptionist_cannot_change_coverage(self):
        self.login("reception.pj")
        self.assertEqual(self.c.put("/api/providers/PP0000001", json={"copay_rate": 0.5}).status_code, 403)

    def test_manager_transfer_scope(self):
        self.login("manager.du")        # Damansara Utama manager; TR0000001 is Subang Jaya -> Shah Alam 7
        self.assertEqual(self.c.post("/api/stock/transfer/TR0000001/approve").status_code, 403)

    def test_manager_other_branch_schedule(self):
        self.login("manager.du")
        self.assertEqual(self.c.post("/api/schedules", json={"staff_id": "ST0000003", "work_date": TOMORROW,
                                                              "start_time": "09:00", "end_time": "17:00"}).status_code, 403)

    def test_claim_other_branch(self):
        self.login("reception.sj")
        pj = [c for c in self.app_claims("hq").json["claims"] if c["branch_id"] == "B01" and c["claim_status"] == "Submitted"][0]
        self.login("reception.sj")
        self.assertEqual(self.c.post(f"/api/claims/{pj['claim_id']}/decision", json={"status": "Paid"}).status_code, 403)

    def app_claims(self, user):
        self.login(user)
        return self.c.get("/api/claims")

    def test_pharmacy_cannot_adjust_other_branch(self):
        self.login("hq")
        b = self.ok(self.c.get("/api/stock?branch_id=B04"))["batches"][0]
        self.login("pharmacy.pj")
        self.assertEqual(self.c.post("/api/stock/adjust", json={"batch_id": b["batch_id"], "reason": "Damaged", "quantity": 1}).status_code, 403)


# ------------------------------------------------------------------ robustness sweep
class TZRobustness(Base):
    """Hit every write endpoint with junk; nothing may crash with a 500."""
    ENDPOINTS = [
        ("reception.pj", "post", "/api/patients"), ("reception.pj", "put", "/api/patients/PT0000001"),
        ("reception.pj", "post", "/api/appointments"), ("reception.pj", "post", "/api/walkin"),
        ("reception.pj", "post", "/api/appointments/AP0000001/checkin"), ("reception.pj", "post", "/api/appointments/AP0000001/cancel"),
        ("manager.pj", "post", "/api/schedules"), ("nurse.pj", "post", "/api/consult/QE0000001/vitals"),
        ("nurse.pj", "post", "/api/consult/QE0000001/status"), ("dr.rahman", "post", "/api/consult/QE0000001/complete"),
        ("pharmacy.pj", "post", "/api/pharmacy/dispense/RX0000001"), ("pharmacy.pj", "post", "/api/stock/receive"),
        ("pharmacy.pj", "post", "/api/stock/adjust"), ("pharmacy.pj", "post", "/api/stock/transfer"),
        ("reception.pj", "post", "/api/billing/generate/CN0000001"), ("reception.pj", "post", "/api/billing/BL0000001/pay"),
        ("reception.pj", "post", "/api/claims/submit"), ("reception.pj", "post", "/api/claims/CL0000001/decision"),
        ("manager.pj", "put", "/api/providers/PP0000001"), ("admin", "post", "/api/users"), ("admin", "put", "/api/users/US0000003"),
    ]
    JUNK = [None, {}, [], "text", {"amount": [1], "quantity": {"a": 1}, "ids": 5, "status": 3, "patient_id": 7,
                                  "medication_id": None, "date_of_birth": 19900101, "full_name": ["x"], "copay_rate": None,
                                  "prescription": "x", "procedures": 5, "items": "x", "role": None, "start_time": 5}]

    def test_no_500s(self):
        app.config["PROPAGATE_EXCEPTIONS"] = False
        crashes = []
        for user, verb, path in self.ENDPOINTS:
            self.login(user)
            for j in self.JUNK:
                if j is None:
                    r = getattr(self.c, verb)(path)
                elif isinstance(j, str):
                    r = getattr(self.c, verb)(path, data=j, content_type="application/json")
                else:
                    r = getattr(self.c, verb)(path, data=json.dumps(j), content_type="application/json")
                if r.status_code >= 500:
                    crashes.append(f"{verb.upper()} {path} {json.dumps(j)[:60]} -> {r.status_code}")
        self.assertEqual(crashes, [], "\n" + "\n".join(crashes))

    def test_get_endpoints_with_odd_params(self):
        app.config["PROPAGATE_EXCEPTIONS"] = False
        crashes = []
        for user, path in [("reception.pj", "/api/slots?date=nope&service=x&branch_id=zz"), ("reception.pj", "/api/appointments?date=x"),
                           ("manager.pj", "/api/schedules?from=nope"), ("hq", "/api/stock?branch_id=ZZ"),
                           ("hq", "/api/claims?branch_id=ZZ&provider_id=x"), ("admin", "/api/audit?q=%25%27"),
                           ("reception.pj", "/api/patients?q=%25%27%22;--")]:
            self.login(user)
            r = self.c.get(path)
            if r.status_code >= 500:
                crashes.append(f"{path} -> {r.status_code}")
        self.assertEqual(crashes, [], "\n" + "\n".join(crashes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
