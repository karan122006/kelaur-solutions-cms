# Sunrise Family Clinics: Clinic Management System (prototype)

**Designed by Keluar Solutions** · *Connect. Simplify. Care.*
Group assignment prototype for CT026-3-1 Systems Analysis & Design (Part A, Interface Design).

## Run it (Windows)

1. Install **Python 3.10 or newer** from python.org and tick *Add Python to PATH*.
2. Double-click **`run.bat`**. It installs Flask (about 1 MB), starts the server and opens `http://127.0.0.1:5000`.
3. Sign in with a demo account. Every account uses the password **`Sfc@2026`**.

| Role | Username | What they see |
|---|---|---|
| Receptionist (PJ) | `reception.pj` | Patients, Appointments, Billing, Claims |
| Nurse (PJ) | `nurse.pj` | Consultation queue + vitals |
| Doctor GP / Paediatrics (PJ) | `dr.rahman` / `dr.izzah` | Consultation, prescriptions, cross-branch history |
| Dentist (PJ) | `dr.aminah` | Dental consultations |
| Pharmacy assistant (PJ) | `pharmacy.pj` | Prescription queue, dispensing, stock |
| Branch manager (PJ) | `manager.pj` | Doctor availability, stock, claims, branch reports |
| Head office | `hq` | Network stock, transfer approvals, all-branch dashboard |
| Administrator | `admin` | Accounts, roles, audit log |

Other branches use the same pattern: `reception.du`, `reception.sa7`, `reception.sa13`, `reception.sj`, and so on.
To start again with fresh demo data, run **`reset_demo_data.bat`** (or delete the `data` folder).

Without the .bat file: `pip install -r requirements.txt` then `python app.py`.

## Running it for real (production settings)

* **Server:** `python app.py` uses **waitress**, a production web server (8 worker threads), not Flask's development server.
* **Other devices at the clinic:** set `HOST=0.0.0.0` before starting (in `run.bat`: add `set HOST=0.0.0.0` above `python app.py`), then open `http://<this-PC's-IP>:5000` on any phone, tablet or PC on the same network. Behind HTTPS, also set `CMS_HTTPS=1`.
* **Hide the demo buttons:** `set CMS_DEMO=0`.
* **Security built in:** hashed passwords, staff must choose their own password after an administrator reset, *Change password* in the menu, 5 failed sign-ins lock that username for 10 minutes, sign-in cookie is HttpOnly + SameSite=Strict, every change request carries an anti-forgery header, strict Content-Security-Policy and other security headers, role checks on every API call, 5-minute idle sign-out, audit log.
* **Sign-ins survive a restart:** the session key is kept in `data/secret.key` (keep this file private).
* **Backups:** a copy of the database is saved to `data/backups` when the server starts and every 24 hours (newest 14 kept). Run `backup.bat` for an extra copy at any time. To restore, stop the server and copy a backup over `data/cms.db`.
* **Logs:** errors and failed sign-ins go to `data/logs/cms.log` (rotated at 2 MB).
* **Health check:** `GET /api/health` returns `{"ok": true}` for uptime monitoring.
* **Speed:** responses are gzip-compressed and static files are cached with version stamps, so updates show up straight away without stale CSS.

## A walkthrough that crosses every DFD process

1. **reception.pj** → Patients → *Register new patient* (try a duplicate IC to see process 1.2) → Appointments → pick the patient → *Walk-in now*.
2. **nurse.pj** → Consultation → open the patient → record vitals.
3. **dr.rahman** (or **dr.izzah** for a child) → Consultation → write the diagnosis and prescribe. If the patient is allergic to Penicillin, prescribing Amoxicillin raises an allergy alert.
4. **pharmacy.pj** → Pharmacy → tick the allergy check → *Dispense*. Stock is deducted and labels print. Low stock alerts head office.
5. **reception.pj** → Billing → generate the itemised bill → take payment (card/e-wallet need a reference) → print the receipt. Panel patients pay only the co-pay.
6. **reception.pj** → Claims → *Prepare claims* → tick drafts → *Submit* → *Record response* (reject one to see the alert).
7. **hq** → Reports (all branches) and Pharmacy → *Network view* / *Transfers* → approve the PJ-bound transfer.
8. **admin** → Users & Audit → see every view, search and change logged.

## How the code follows the diagrams

The **DFD Level-0 (Fig 6.2)** is the architecture: every process is one backend module, and every data store maps to the ERD tables.

| DFD process | Backend module | API | Screen |
|---|---|---|---|
| 1.0 Manage Patient Registration & Records | `backend/p1_patients.py` (sub-processes 1.1–1.5 from the Level-1 DFD) | `/api/patients` | Patients |
| 2.0 Manage Appointments | `backend/p2_appointments.py` (2.1–2.5 from the Level-1 DFD) | `/api/slots`, `/api/appointments`, `/api/walkin`, `/api/queue`, `/api/schedules` | Appointments |
| 3.0 Manage Consultation & Medical Records | `backend/p3_consultation.py` | `/api/consult` | Consultation |
| 4.0 Manage Pharmacy Dispensing & Stock | `backend/p4_pharmacy.py` | `/api/pharmacy`, `/api/stock` | Pharmacy & Stock |
| 5.0 Manage Billing & Payments | `backend/p5_billing.py` (5.1–5.5 from the Level-1 DFD) | `/api/billing` | Billing & Payments |
| 6.0 Manage Insurance & Panel Claims | `backend/p6_claims.py` | `/api/claims`, `/api/providers` | Claims |
| 7.0 Generate Reports & Dashboard | `backend/p7_reports.py` | `/api/reports` | Reports & Dashboard |
| 8.0 Send Notifications & Reminders | `backend/p8_notify.py` (SMS gateway stand-in) | `/api/notifications` | Messages & Alerts |
| 9.0 Manage Users, Roles | `backend/p9_users.py` + `backend/auth.py` | `/api/users`, `/api/audit`, `/api/login` | Users & Audit |

| Data store | ERD tables (`backend/schema.sql`) |
|---|---|
| D1 Patient Records | PATIENT, PATIENT_COVERAGE (+ PANEL_PROVIDER) |
| D2 Appointment & Schedule | APPOINTMENT, QUEUE_ENTRY, STAFF_SCHEDULE |
| D3 Medical & Prescription Records | CONSULTATION, PRESCRIPTION, PRESCRIPTION_ITEM |
| D4 Medication Stock | MEDICATION, STOCK_BATCH, STOCK_TRANSFER, SUPPLIER |
| D5 Billing & Payment Records | BILL, BILL_ITEM, PAYMENT |
| D6 Claim Records | CLAIM |
| D7 User Account & System Log | USER_ACCOUNT, AUDIT_LOG |
| (8.0 message log) | NOTIFICATION |
| Reference | BRANCH, STAFF |

The external entities in the **Context Diagram (Fig 6.1)** become the roles that log in (Patient-facing flows go through the receptionist and SMS). The SMS Gateway and the Panel/Insurance Provider are simulated: SMS delivery status is logged, and claim decisions are recorded on the Claims screen.

Columns marked `-- NEW` in `schema.sql` are the fields the Part-B data dictionaries say must be added to the ERD (for example `registration_date`, `payer_type`, `outstanding_balance`, `receipt_no`), plus three that the flows need: `consultation.charges`, `medication.unit_price` and the Sunday/half-day schedule rows.

## Testing

* `python -m unittest tests.test_api -v`: 73 back-end tests (all processes, roles, bad input).
* `python tests/test_ui.py`: 158 browser checks (needs `pip install playwright` and `python -m playwright install chromium` once).
* `python tests/test_devices.py`: every screen state (26) for every role on 11 phone/tablet/laptop sizes, from a 280 px folded phone to a 1366 px laptop. It checks for overlapping elements, sideways scrolling, cut-off text and tap targets, and saves screenshots to `tests/device_shots`.

Both use a throw-away database. Results and the bugs they caught are in `docs/TEST_REPORT.md`.

## Technology (fast and light)

* **Backend:** Python 3 + Flask, with SQLite (built into Python). One central database file, `data/cms.db`.
* **Frontend:** plain HTML + CSS and **Alpine.js** (a 44 KB JavaScript framework, stored locally in `static/vendor`). No build step and no CDN, so it also works offline.
* **Phones and tablets:** below 900 px the menu becomes a slide-out drawer and every table turns into stacked cards. Inputs use 16 px text so iPhones don't zoom in, and the layout respects iPhone notch safe areas.
* **Weight:** the whole interface, including 16 photos, is about 1.1 MB on first load and is cached after that. HTML + CSS + JS is about 180 KB. The server starts at about 35 MB of RAM and stays under 100 MB in use.
* **Security in the prototype:** hashed passwords, role checks on every API call, 5-minute inactivity sign-out (warning at 4:30), audit log of record access, card numbers never stored.

Photos: Unsplash (Unsplash License): Vitaly Gariev, National Cancer Institute, Martha Dominguez de Gouveia, Hal Gatewood, Melany @ tuinfosalud.com, Ozkan Guner, Bermix Studio, Nathana Rebouças, SumUp.
