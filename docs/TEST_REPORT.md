# Test report: SFC Clinic Management System prototype

**Date:** 8 November 2026 · **Result:** 79 back-end tests, 158 browser checks and 286 device-layout checks: all pass.

## What was tested

| Suite | File | Scope | Result |
|---|---|---|---|
| Back-end (API) | `tests/test_api.py` | 79 tests (incl. security headers, anti-forgery header, sign-in lockout, password change, backup): every DFD process 1.0–9.0, sign-in and the 5-minute timeout, the role-access rules for all 8 roles, a full visit from registration to paid claim, and a sweep that sends junk input to all 21 write functions | 79 / 79 pass |
| Devices (layout) | `tests/test_devices.py` | 26 screen states × 11 devices (Galaxy Z Fold folded 280 px, Galaxy S8, iPhone SE, iPhone 13 mini, iPhone 14, Pixel 7, iPhone 14 Pro Max, iPhone 14 landscape, iPad mini, iPad Air landscape, laptop): overlapping elements, sideways scrolling, cut-off text, tap-target size, text size | 286 / 286 pass |
| Browser (UI) | `tests/test_ui.py` | 158 checks: every screen for every role, every form, dialog, print-out and Excel export, EN/BM switch, idle sign-out, and phone-size layout (390 px) for 9 screens | 158 / 158 pass |

Both suites use their own throw-away database, so they never change `data/cms.db`.

## How to re-run

```
python -m unittest tests.test_api -v
pip install playwright && python -m playwright install chromium
python tests/test_ui.py
```

## Bugs found and fixed

| # | Component | Bug found by the tests | Fix |
|---|---|---|---|
| 1 | 2.0 Walk-in | Two walk-ins in the same second after clinic hours clashed and crashed (500 error) | Each after-hours walk-in now gets a unique time |
| 2 | 2.0 Walk-in | The same patient could be walked in twice the same day | Refused with "already in today's queue" |
| 3 | 2.0 Appointments | Cancel / check-in of an unknown or already-cancelled appointment crashed | Clear 404 / 409 messages |
| 4 | 2.1 Doctor availability | An unknown doctor or a bad time crashed; a manager could edit another branch's doctors | Validated; managers limited to their own branch |
| 5 | 3.0 Consultation | Unknown medicine or a non-number quantity crashed; a visit could be completed twice | Validated; second completion refused |
| 6 | 3.0 Consultation | Vitals accepted impossible pulse/weight values | Pulse 20–250, weight 0.5–300 kg |
| 7 | 3.0 Consultation | Allergy override was not recorded | Override is written to the audit log |
| 8 | 4.0 Stock | Receive / adjust / transfer crashed on a non-number quantity or unknown medicine/branch | Validated with clear messages |
| 9 | 4.0 Stock | Pharmacy could adjust another branch's stock; a branch manager could approve any branch's transfer | Limited to own branch |
| 10 | 5.0 Billing | Billing an unknown visit crashed | 404 "Visit not found" |
| 11 | 6.0 Claims | Non-number approved amount crashed; decisions allowed on Draft claims; staff could act on other branches' claims; receptionists could change coverage rules | Validated and restricted |
| 12 | 7.0 Reports | A branch manager could view another branch's dashboard by changing the address; bad dates were accepted | Manager locked to own branch; From must be on or before To |
| 13 | 9.0 Users | The administrator could deactivate or demote their own account (locked out) | Refused |
| 14 | 9.0 Audit | Searching the audit log by a staff username missed changes made *to* that account | Search now matches the account changed, too |
| 15 | 1.0 Patients | Non-text values (lists, numbers) in the form crashed; editing to Self-pay kept the old panel | Treated as missing; coverage removed |
| 16 | Layout | On phones, Claims and Reports scrolled sideways | Grids and tables now fit the screen |
| 17 | Whole system | Any unexpected error showed an HTML error page | Every error now returns a short, readable message |

## Production hardening and phone layout (second round)

| # | Area | Problem | Fix |
|---|---|---|---|
| 18 | Server | Ran on Flask's development server | Runs on waitress (production server, 8 threads) |
| 19 | Sessions | Every restart signed all staff out | Session key kept in `data/secret.key` |
| 20 | Security | No limit on password guessing | 5 failures lock that username for 10 minutes |
| 21 | Security | Change requests could be forged from another site | Anti-forgery header on every change + SameSite=Strict cookie |
| 22 | Security | No browser security headers | CSP, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy |
| 23 | Accounts | Reset passwords were never changed; no way to change your own | Forced change after reset; *Change password* in the menu |
| 24 | Data | No backups (NFR-6) | Automatic daily backup (14 kept) + `backup.bat` |
| 25 | Operations | No error log or health check | Rotating log in `data/logs`, `/api/health` |
| 26 | Speed | Stale CSS/JS after updates; uncompressed responses | Version-stamped assets, gzip |
| 27 | Phones | Two-column forms in dialogs collapsed onto each other below 320 px (Receive stock, New account) | Fields stack in one column |
| 28 | Phones | Sidebar pushed the page down; top bar crowded | Slide-out menu drawer; compact top bar |
| 29 | Phones/tablets | Wide tables scrolled sideways | Tables become stacked cards below 900 px; tighter columns on tablets |
| 30 | Phones | Patient header text ran under the buttons; scroll boxes nested inside the page | Header wraps; no nested scrolling on phones |
| 31 | Phones | Small text links (Cancel, Change, Prepare claims) were hard to tap | 40 px tap areas on touch screens |
| 32 | Phones | Charts' labels shrank to unreadable size | Charts redraw for the screen width |
| 33 | Phones | iPhone zoomed into every input; queue board needed sideways scrolling | 16 px inputs; queue lanes stack |
| 34 | Phones | Tapping a patient/prescription/bill left the details off-screen | Page scrolls to the details |
| 35 | Accessibility | Closed phone menu was still reachable by keyboard and screen readers | Hidden when closed |
