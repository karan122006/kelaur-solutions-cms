-- Keluar Solutions · Sunrise Family Clinics CMS
-- Physical schema generated from ERD (Figure 6.3).
-- Columns marked  -- NEW  come from the Part-B data dictionaries
-- (D1 Patient Records, D5 Billing & Payment Records) or are the minimum
-- needed to run a DFD flow; everything else is exactly as drawn in the ERD.
PRAGMA foreign_keys = ON;

-- ───────────── Reference / organisation ─────────────
CREATE TABLE IF NOT EXISTS branch (
  branch_id   TEXT PRIMARY KEY,
  branch_name TEXT NOT NULL,
  address     TEXT,
  city        TEXT,
  phone       TEXT
);

CREATE TABLE IF NOT EXISTS staff (
  staff_id        TEXT PRIMARY KEY,
  branch_id       TEXT REFERENCES branch(branch_id),
  full_name       TEXT NOT NULL,
  role            TEXT NOT NULL,   -- admin, doctor, dentist, nurse, pharmacy, receptionist, branch_manager, head_office
  specialisation  TEXT,            -- General Practice / Paediatrics / Dental
  phone           TEXT,
  email           TEXT,
  status          TEXT DEFAULT 'Active'
);

-- ───────────── D7 User Account & System Log ─────────────
CREATE TABLE IF NOT EXISTS user_account (
  user_id        TEXT PRIMARY KEY,
  staff_id       TEXT UNIQUE REFERENCES staff(staff_id),
  username       TEXT UNIQUE NOT NULL,
  password       TEXT NOT NULL,             -- stored as a salted hash
  account_status TEXT DEFAULT 'Active',
  last_login     TEXT,
  must_change_password INTEGER DEFAULT 0   -- NEW: set after an administrator reset
);

CREATE TABLE IF NOT EXISTS audit_log (
  log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        TEXT REFERENCES user_account(user_id),
  action         TEXT NOT NULL,
  table_affected TEXT,
  record_id      TEXT,
  logged_at      TEXT DEFAULT (datetime('now','localtime'))
);

-- ───────────── D1 Patient Records ─────────────
CREATE TABLE IF NOT EXISTS panel_provider (
  provider_id    TEXT PRIMARY KEY,
  provider_name  TEXT NOT NULL,
  contact_person TEXT,
  phone          TEXT,
  coverage_rules TEXT,
  copay_rate     REAL DEFAULT 0       -- fraction the patient pays, e.g. 0.10
);

CREATE TABLE IF NOT EXISTS patient (
  patient_id           TEXT PRIMARY KEY,
  registered_branch_id TEXT REFERENCES branch(branch_id),
  ic_passport_no       TEXT UNIQUE NOT NULL,   -- NFR-7: one record per IC
  full_name            TEXT NOT NULL,
  date_of_birth        TEXT NOT NULL,
  gender               TEXT,
  phone                TEXT NOT NULL,
  address              TEXT,
  emergency_contact    TEXT NOT NULL,
  allergies            TEXT NOT NULL,
  registration_date    TEXT,                   -- NEW (D1 dictionary)
  last_updated_at      TEXT,                   -- NEW (D1 dictionary)
  last_updated_by      TEXT REFERENCES staff(staff_id)  -- NEW (D1 dictionary)
);

CREATE TABLE IF NOT EXISTS patient_coverage (
  coverage_id TEXT PRIMARY KEY,
  patient_id  TEXT REFERENCES patient(patient_id),
  provider_id TEXT REFERENCES panel_provider(provider_id),
  policy_no   TEXT NOT NULL,
  valid_until TEXT
);

-- ───────────── D2 Appointment & Schedule ─────────────
CREATE TABLE IF NOT EXISTS staff_schedule (
  schedule_id  TEXT PRIMARY KEY,
  staff_id     TEXT REFERENCES staff(staff_id),
  branch_id    TEXT REFERENCES branch(branch_id),
  work_date    TEXT NOT NULL,
  start_time   TEXT,
  end_time     TEXT,
  leave_status TEXT DEFAULT 'On Duty'      -- On Duty / On Leave
);

CREATE TABLE IF NOT EXISTS appointment (
  appointment_id       TEXT PRIMARY KEY,
  patient_id           TEXT REFERENCES patient(patient_id),
  staff_id             TEXT REFERENCES staff(staff_id),
  branch_id            TEXT REFERENCES branch(branch_id),
  service_type         TEXT NOT NULL,      -- General Practice / Paediatrics / Dental
  appointment_datetime TEXT NOT NULL,
  booking_type         TEXT DEFAULT 'Phone', -- Phone / Walk-in / Counter
  status               TEXT DEFAULT 'Booked' -- Booked / Rescheduled / Cancelled / Checked-in / Completed / No-show
);
-- NFR-7 style guard: one active booking per doctor per slot
CREATE UNIQUE INDEX IF NOT EXISTS ux_doctor_slot ON appointment(staff_id, appointment_datetime)
  WHERE status NOT IN ('Cancelled','Rescheduled');

CREATE TABLE IF NOT EXISTS queue_entry (
  queue_id       TEXT PRIMARY KEY,
  appointment_id TEXT UNIQUE REFERENCES appointment(appointment_id),
  queue_no       TEXT NOT NULL,
  check_in_time  TEXT,
  queue_status   TEXT DEFAULT 'Waiting'  -- Waiting / Vitals Taken / In Consultation / At Pharmacy / Paying / Done
);

-- ───────────── D3 Medical & Prescription Records ─────────────
CREATE TABLE IF NOT EXISTS consultation (
  consultation_id TEXT PRIMARY KEY,
  queue_id        TEXT REFERENCES queue_entry(queue_id),
  patient_id      TEXT REFERENCES patient(patient_id),
  staff_id        TEXT REFERENCES staff(staff_id),
  vitals          TEXT,
  symptoms        TEXT,
  diagnosis       TEXT,
  treatment       TEXT,
  follow_up_date  TEXT,
  visit_date      TEXT,
  charges         TEXT                      -- NEW: JSON bill lines (consultation, procedure, vaccine, dental) = 'Charges' flow D3 -> 5.0
);

CREATE TABLE IF NOT EXISTS prescription (
  prescription_id TEXT PRIMARY KEY,
  consultation_id TEXT REFERENCES consultation(consultation_id),
  issued_at       TEXT,
  status          TEXT DEFAULT 'Pending'   -- Pending / Dispensed
);

-- ───────────── D4 Medication Stock ─────────────
CREATE TABLE IF NOT EXISTS supplier (
  supplier_id   TEXT PRIMARY KEY,
  supplier_name TEXT NOT NULL,
  phone         TEXT,
  email         TEXT
);

CREATE TABLE IF NOT EXISTS medication (
  medication_id   TEXT PRIMARY KEY,
  medication_name TEXT NOT NULL,
  unit            TEXT,
  reorder_level   INTEGER DEFAULT 50,
  unit_price      REAL DEFAULT 0            -- NEW: price of dispensed items for billing
);

CREATE TABLE IF NOT EXISTS stock_batch (
  batch_id         TEXT PRIMARY KEY,
  medication_id    TEXT REFERENCES medication(medication_id),
  branch_id        TEXT REFERENCES branch(branch_id),
  supplier_id      TEXT REFERENCES supplier(supplier_id),
  batch_no         TEXT,
  expiry_date      TEXT,
  quantity_on_hand INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS prescription_item (
  item_id         TEXT PRIMARY KEY,
  prescription_id TEXT REFERENCES prescription(prescription_id),
  medication_id   TEXT REFERENCES medication(medication_id),
  batch_id        TEXT REFERENCES stock_batch(batch_id),  -- filled when dispensed
  dosage          TEXT,
  quantity        INTEGER
);

CREATE TABLE IF NOT EXISTS stock_transfer (
  transfer_id     TEXT PRIMARY KEY,
  batch_id        TEXT REFERENCES stock_batch(batch_id),
  from_branch_id  TEXT REFERENCES branch(branch_id),
  to_branch_id    TEXT REFERENCES branch(branch_id),
  quantity        INTEGER,
  transfer_status TEXT DEFAULT 'Requested',  -- Requested / Approved / Rejected
  requested_at    TEXT
);

-- ───────────── D5 Billing & Payment Records ─────────────
CREATE TABLE IF NOT EXISTS bill (
  bill_id             TEXT PRIMARY KEY,
  consultation_id     TEXT REFERENCES consultation(consultation_id),
  patient_id          TEXT REFERENCES patient(patient_id),
  branch_id           TEXT REFERENCES branch(branch_id),
  bill_date           TEXT,                 -- NEW (D5 dictionary)
  payer_type          TEXT DEFAULT 'Self-pay', -- NEW: Self-pay / Panel / Insurance
  total_amount        REAL DEFAULT 0,
  amount_paid         REAL DEFAULT 0,       -- NEW
  outstanding_balance REAL DEFAULT 0,       -- NEW
  bill_status         TEXT DEFAULT 'Unpaid' -- Unpaid / Partially Paid / Paid
);

CREATE TABLE IF NOT EXISTS bill_item (
  bill_item_id TEXT PRIMARY KEY,
  bill_id      TEXT REFERENCES bill(bill_id),
  item_type    TEXT,                        -- NEW: Consultation / Procedure / Medicine / Vaccine / Dental
  description  TEXT,                        -- NEW
  quantity     INTEGER CHECK (quantity >= 1),
  unit_price   REAL,                        -- NEW
  amount       REAL
);

CREATE TABLE IF NOT EXISTS payment (
  payment_id        TEXT PRIMARY KEY,
  bill_id           TEXT REFERENCES bill(bill_id),
  payment_date      TEXT,                   -- NEW
  payment_method    TEXT,                   -- Cash / Card / E-wallet
  amount            REAL,
  reference_no      TEXT,                   -- NEW
  received_by       TEXT REFERENCES staff(staff_id), -- NEW
  receipt_no        TEXT UNIQUE,            -- NEW
  receipt_issued_at TEXT                    -- NEW
);

-- ───────────── D6 Claim Records ─────────────
CREATE TABLE IF NOT EXISTS claim (
  claim_id        TEXT PRIMARY KEY,
  bill_id         TEXT REFERENCES bill(bill_id),
  provider_id     TEXT REFERENCES panel_provider(provider_id),
  claim_status    TEXT DEFAULT 'Draft',     -- Draft / Submitted / Approved / Rejected / Paid
  amount_claimed  REAL,
  amount_approved REAL,
  submitted_date  TEXT
);

-- ───────────── Process 8.0 message log ─────────────
CREATE TABLE IF NOT EXISTS notification (
  notification_id   TEXT PRIMARY KEY,
  patient_id        TEXT REFERENCES patient(patient_id),
  staff_id          TEXT REFERENCES staff(staff_id),
  notification_type TEXT,   -- Appointment Confirmation / Reminder / Cancellation / Stock Alert / Rejected Claim / Prescription Waiting
  message           TEXT,
  delivery_status   TEXT,   -- Queued / Sent / Delivered / Failed  (SMS gateway response)
  sent_at           TEXT
);
