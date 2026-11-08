"""Browser test of every screen, role, dialog, print-out and export (needs: pip install playwright && playwright install chromium).
Starts its own server on port 5055 with a throw-away database, then clicks through the app like a user would.

Run from the project folder:   python tests/test_ui.py
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 5055
B = f"http://127.0.0.1:{PORT}/"
CHROME = os.environ.get("CHROME_PATH")          # optional: use an installed Chrome instead of Playwright's
results, js_errors, server_errors = [], [], []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))


async def main():
    db = os.path.join(tempfile.mkdtemp(), "ui_test.db")
    env = {**os.environ, "CMS_DB": db, "PORT": str(PORT)}
    subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, r'{ROOT}'); from backend.seed import build; build(r'{db}')"],
                   check=True, env=env)
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "app.py")], env=env, cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen(B, timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(**({"executable_path": CHROME} if CHROME else {}), args=["--no-sandbox"])
            ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
            await ctx.add_init_script("window.print = () => { window.__printed = (window.__printed || 0) + 1 }")
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: js_errors.append(str(e)))
            pg.on("console", lambda m: m.type == "error" and "status of 4" not in m.text and js_errors.append(m.text))
            pg.on("response", lambda r: r.status >= 500 and server_errors.append(f"{r.status} {r.url}"))
            await run(pg)
            await browser.close()
    finally:
        srv.terminate()
    check("no JavaScript errors in the whole run", not js_errors, js_errors[:5])
    check("no server (5xx) errors in the whole run", not server_errors, server_errors[:5])
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


async def state(pg, expr):
    return await pg.evaluate(f"(() => {{ const s = document.body._x_dataStack[0]; return {expr}; }})()")


async def login(pg, user, pw="Sfc@2026"):
    await pg.goto(B)
    await pg.wait_for_timeout(300)
    if await state(pg, "!!s.user"):
        if await pg.locator("button:has-text('Sign out') >> visible=true").count():
            await pg.locator("button:has-text('Sign out') >> visible=true").first.click()
        else:   # phone layout: sign-out lives in the menu drawer
            await click(pg, ".menu-btn")
            await pg.wait_for_timeout(300)
            await pg.locator(".side button:has-text('Sign out') >> visible=true").first.click()
        await pg.wait_for_load_state()
        await pg.wait_for_timeout(500)
    await pg.fill("input[autocomplete=username]", user)
    await pg.fill("input[type=password]", pw)
    await pg.click("form .btn.lg")
    await pg.wait_for_timeout(700)


async def goto(pg, page):
    await pg.goto(B + "#" + page)
    await pg.wait_for_timeout(700)


async def toast(pg):
    await pg.wait_for_timeout(500)
    return await state(pg, "s.toastMsg || ''")


def V(pg, sel):
    """First visible match: hidden screens stay in the page, so plain selectors could hit them."""
    return pg.locator(sel + " >> visible=true").first


async def click(pg, sel):
    await V(pg, sel).click()


async def fill(pg, sel, val):
    await V(pg, sel).fill(val)


async def select(pg, sel, **kw):
    await V(pg, sel).select_option(**kw)


async def visible(pg, sel):
    await pg.wait_for_timeout(150)
    return await pg.locator(sel + " >> visible=true").count() > 0


async def count(pg, sel):
    return await pg.locator(sel + " >> visible=true").count()


async def run(pg):
    # ---------------- sign-in ----------------
    await pg.goto(B)
    await pg.wait_for_timeout(500)
    check("sign-in page shows logo and photo", await visible(pg, ".login-form .logo") and await visible(pg, ".login-photo"))
    await fill(pg, "input[autocomplete=username]", "hq")
    await fill(pg, "input[type=password]", "wrong")
    await click(pg, "form .btn.lg")
    await pg.wait_for_timeout(500)
    check("wrong password shows an error", "Incorrect" in await pg.inner_text(".login-form"))
    await click(pg, ".login-form .seg button:has-text('BM')")
    check("BM toggle translates the sign-in button", await pg.inner_text("form .btn.lg") == "Log masuk")
    await click(pg, ".login-form .seg button:has-text('EN')")

    pages = {"reception.pj": ["patients", "appointments", "billing", "claims", "messages"],
             "nurse.pj": ["patients", "appointments", "consult", "messages"],
             "dr.rahman": ["patients", "appointments", "consult", "messages"],
             "dr.aminah": ["patients", "appointments", "consult", "messages"], "pharmacy.pj": ["patients", "pharmacy", "messages"],
             "manager.pj": ["patients", "appointments", "billing", "pharmacy", "claims", "reports", "messages"],
             "hq": ["pharmacy", "claims", "reports", "messages"], "admin": ["patients", "messages", "admin"]}
    for user, allowed in pages.items():
        await login(pg, user)
        check(f"{user}: signs in", await state(pg, "!!s.user"))
        nav = await pg.locator(".nav a").all_inner_texts()
        for pid in allowed:
            await goto(pg, pid)
            ok = await state(pg, f"s.page === '{pid}'") and await visible(pg, ".banner .in h1")
            check(f"{user}: opens {pid}", ok)
        for pid in ("admin", "reports", "billing"):
            if pid not in allowed:
                await goto(pg, pid)
                check(f"{user}: blocked from {pid}", await state(pg, "s.page === 'home'"))
        check(f"{user}: menu shows only allowed modules", len([n for n in nav if n.strip()]) == len(allowed) + 1, nav)

    # ---------------- 1.0 patients ----------------
    await login(pg, "reception.pj")
    await goto(pg, "patients")
    await click(pg, "text=Register new patient")
    await click(pg, "form >> text=Continue")
    check("1.1 empty step shows field errors", await pg.locator(".has-err").count() >= 3)
    await fill(pg, "label:has-text('Full name') input", "Ui Tester One")
    await fill(pg, "label:has-text('IC or passport') input", "930303-10-3333")
    await fill(pg, "label:has-text('Date of birth') input", "1993-03-03")
    await click(pg, "button:has-text('Male')")
    await click(pg, "form >> text=Continue")
    await fill(pg, "label:has-text('Mobile') input", "12")
    await click(pg, "form >> text=Continue")
    check("1.1 short phone rejected", "9–12 digits" in await V(pg, "form").inner_text())
    await fill(pg, "label:has-text('Mobile') input", "0123334444")
    await fill(pg, "label:has-text('Emergency contact') input", "Mum - 0129990000")
    await click(pg, "form >> text=Continue")
    await click(pg, "label.check:has-text('No known allergies')")
    await click(pg, "form >> text=Continue")
    await click(pg, "button:has-text('Back')")
    check("Back returns to the previous step", await state(pg, "s.pt.step") == 3)
    await click(pg, "form >> text=Continue")
    await click(pg, "button:has-text('Register patient')")
    t = await toast(pg)
    check("1.3 registration saves and shows the new ID", "Patient ID PT" in t, t)
    check("1.5 confirmation shown on record", await visible(pg, "text=Confirmation sent by SMS"))
    await click(pg, "button:has-text('Print slip')")
    check("registration slip prints", await pg.evaluate("window.__printed") == 1)
    await click(pg, "button:has-text('Edit details')")
    await click(pg, "form >> text=Continue")
    await fill(pg, "label:has-text('Mobile') input", "0123335555")
    for _ in range(2):
        await click(pg, "form >> text=Continue")
    await click(pg, "button:has-text('Save changes')")
    check("1.3 edit saves", "updated" in await toast(pg))
    # duplicate
    await click(pg, "text=Register new patient")
    await fill(pg, "label:has-text('Full name') input", "Someone Else")
    await fill(pg, "label:has-text('IC or passport') input", "930303103333")
    await fill(pg, "label:has-text('Date of birth') input", "1990-01-01")
    await click(pg, "button:has-text('Female')")
    await click(pg, "form >> text=Continue")
    await fill(pg, "label:has-text('Mobile') input", "0128887777")
    await fill(pg, "label:has-text('Emergency contact') input", "X - 0123")
    await click(pg, "form >> text=Continue")
    await click(pg, "label.check:has-text('No known allergies')")
    await click(pg, "form >> text=Continue")
    await click(pg, "button:has-text('Register patient')")
    await pg.wait_for_timeout(500)
    check("1.2 duplicate IC is caught", await visible(pg, "text=Duplicate found"))
    await click(pg, "button:has-text('Open Ui Tester One')")
    await pg.wait_for_timeout(500)
    check("duplicate alert opens the existing record", "Ui Tester One" in await V(pg, ".pbanner").inner_text())
    await fill(pg, "input[type=search]", "Ui Tester")
    await pg.wait_for_timeout(600)
    check("1.4 search finds the patient", await pg.locator(".list li:has-text('Ui Tester One')").count() == 1)
    await fill(pg, "input[type=search]", "zzqqxx")
    await pg.wait_for_timeout(600)
    check("1.4 no-match message", await visible(pg, "text=No record found"))

    # ---------------- 2.0 appointments ----------------
    await click(pg, "text=Register new patient")  # leave form; go via record's Book button instead
    await fill(pg, "input[type=search]", "Ui Tester")
    await pg.wait_for_timeout(600)
    await click(pg, ".list li:has-text('Ui Tester One')")
    await pg.wait_for_timeout(400)
    await click(pg, "a:has-text('Book appointment')")
    await pg.wait_for_timeout(800)
    check("Book appointment carries the patient across", "Ui Tester One" in await V(pg, ".note").inner_text())
    await click(pg, ".svc:has-text('Paediatrics')")
    await pg.wait_for_timeout(500)
    await click(pg, ".svc:has-text('General Practice')")
    await pg.wait_for_timeout(500)
    await pg.locator(".slot:not([disabled])").first.click()
    await click(pg, "button:has-text('Confirm booking')")
    check("2.3 booking confirmed with SMS", "SMS sent" in await toast(pg))
    taken = await count(pg, ".slot[disabled]")
    check("2.2 slot grid refreshes after booking", taken > 0)
    await click(pg, "button:has-text('2.5 Daily list')")
    await fill(pg, ".card-h input[type=date]", await state(pg, "s.ap.date"))
    await V(pg, ".card-h input[type=date]").dispatch_event("change")
    await pg.wait_for_timeout(600)
    row = pg.locator("tr:has-text('Ui Tester One')").first
    check("2.5 booking appears on the daily list", await row.count() == 1)
    await row.locator("button:has-text('Reschedule')").click()
    await pg.wait_for_timeout(600)
    check("reschedule switches to booking with a banner", await visible(pg, "text=Rescheduling"))
    await pg.locator(".slot:not([disabled])").nth(2).click()
    await click(pg, "button:has-text('Confirm new time')")
    check("reschedule saved", "confirmed" in await toast(pg))
    await click(pg, "button:has-text('2.5 Daily list')")
    await V(pg, ".card-h input[type=date]").dispatch_event("change")
    await pg.wait_for_timeout(600)
    await pg.locator("tr:has-text('Ui Tester One'):has-text('Booked') button:has-text('Cancel')").first.click()
    check("cancel asks for confirmation", await visible(pg, ".modal .box:has-text('Cancel appointment?')"))
    await click(pg, ".modal button:has-text('Cancel appointment')")
    check("cancel works", "cancelled" in await toast(pg))
    await click(pg, "button:has-text('2.4 Send tomorrow')")
    check("2.4 reminders run", "reminder" in await toast(pg))
    await click(pg, "button:has-text('Book & walk-in')")
    await fill(pg, "input[placeholder='Name, IC, phone or ID']", "Ui Tester")
    await pg.wait_for_timeout(600)
    await click(pg, ".list li:has-text('Ui Tester One')")
    await click(pg, "button:has-text('Walk-in now')")
    t = await toast(pg)
    check("walk-in gets a queue number", "Queue number W" in t, t)
    check("queue board shows the walk-in", await pg.locator(".qcard:has-text('Ui Tester One')").count() == 1)
    await click(pg, "button:has-text('Book & walk-in')")
    await fill(pg, "input[placeholder='Name, IC, phone or ID']", "Ui Tester")
    await pg.wait_for_timeout(600)
    await click(pg, ".list li:has-text('Ui Tester One')")
    await click(pg, "button:has-text('Walk-in now')")
    check("second walk-in the same day is refused", "already in today's queue" in await toast(pg))

    # ---------------- 3.0 nurse + doctor ----------------
    await login(pg, "nurse.pj")
    await goto(pg, "consult")
    await click(pg, ".list li:has-text('Ui Tester One')")
    await pg.wait_for_timeout(600)
    await fill(pg, "label:has-text('Temp') input", "37.9")
    await fill(pg, "label:has-text('Blood pressure') input", "999")
    await click(pg, "button:has-text('Save vitals')")
    await pg.wait_for_timeout(300)
    check("bad blood pressure is blocked", await state(pg, "s.cs.open !== null"))
    await fill(pg, "label:has-text('Blood pressure') input", "121/79")
    await click(pg, "button:has-text('Save vitals')")
    check("vitals saved", "Vitals saved" in await toast(pg))
    check("nurse sees no consultation notes form", not await visible(pg, "text=Consultation notes"))

    await login(pg, "dr.rahman")
    await goto(pg, "consult")
    await click(pg, ".list li:has-text('Ui Tester One')")
    await pg.wait_for_timeout(700)
    check("doctor sees vitals from nurse", await V(pg, "label:has-text('Blood pressure') input").input_value() == "121/79")
    await click(pg, "button:has-text('Complete visit')")
    check("diagnosis is required", "Diagnosis is required" in await toast(pg))
    await fill(pg, "label:has-text('Diagnosis') input", "Viral URTI")
    await click(pg, ".chip:has-text('Nebuliser')")
    await click(pg, "text=Add medicine")
    await click(pg, "text=Add medicine")
    check("two prescription rows added", await count(pg, "select[aria-label=Medicine]") == 2)
    await pg.locator("button[aria-label=Remove]").nth(1).click()
    check("prescription row can be removed", await count(pg, "select[aria-label=Medicine]") == 1)
    await select(pg, "select[aria-label=Medicine]", label="Paracetamol 500mg tab")
    await fill(pg, "input[aria-label=Dosage]", "1 tab 4x daily")
    await fill(pg, "input[aria-label=Quantity]", "8")
    est = await pg.inner_text("text=Estimated charges")
    check("estimated charges update (35 + 30 + 2.40)", "67.40" in est, est)
    await click(pg, "button:has-text('Complete visit')")
    check("visit completes and Rx goes to pharmacy", "sent to pharmacy" in await toast(pg))

    # ---------------- 4.0 pharmacy ----------------
    await login(pg, "pharmacy.pj")
    await goto(pg, "pharmacy")
    await click(pg, ".list li:has-text('Ui Tester One')")
    await pg.wait_for_timeout(300)
    check("dispense disabled until allergy check ticked", await pg.locator("button:has-text('Dispense')").is_disabled())
    await click(pg, "label.check:has-text('checked allergies')")
    await click(pg, "button:has-text('Dispense')")
    check("dispensed and stock deducted", "Stock updated" in await toast(pg))
    await click(pg, "button:has-text('Print labels')")
    check("labels print", await pg.evaluate("window.__printed") >= 1)
    await click(pg, "button:has-text('Branch stock')")
    await pg.wait_for_timeout(500)
    await fill(pg, "input[placeholder='Filter medicines']", "salbut")
    check("stock filter works", await count(pg, ".card.flush tbody tr") == 1, await count(pg, ".card.flush tbody tr"))
    await fill(pg, "input[placeholder='Filter medicines']", "")
    await click(pg, "button:has-text('Receive stock')")
    await select(pg, ".modal select >> nth=0", label="Cetirizine 10mg tab")
    await fill(pg, ".modal label:has-text('Batch number') input", "UI-BATCH-1")
    await fill(pg, ".modal input[type=date]", "2029-12-31")
    await fill(pg, ".modal label:has-text('Quantity') input", "40")
    await click(pg, ".modal button:has-text('Add to stock')")
    check("receive stock works", "Received 40" in await toast(pg))
    await click(pg, "button:has-text('Adjust / dispose')")
    await select(pg, ".modal select >> nth=0", index=1)
    await fill(pg, ".modal label:has-text('Quantity') input", "1")
    await click(pg, ".modal button:has-text('Save adjustment')")
    check("adjust stock works", "adjusted" in await toast(pg))
    await click(pg, "button:has-text('Request transfer')")
    await select(pg, ".modal select >> nth=0", index=1)
    await select(pg, ".modal select >> nth=1", index=2)
    await fill(pg, ".modal label:has-text('Quantity') input", "1")
    await click(pg, ".modal button:has-text('Send request')")
    check("transfer request works", "requested" in await toast(pg))
    await click(pg, "button:has-text('Network view')")
    await pg.wait_for_timeout(500)
    check("network view shows 5 branch columns", await count(pg, ".heat thead th") == 6)

    # ---------------- 5.0 billing ----------------
    await login(pg, "reception.pj")
    await goto(pg, "billing")
    await click(pg, ".list li:has-text('Ui Tester One')")
    await pg.wait_for_timeout(700)
    check("5.1 itemised bill shows 3 lines", await count(pg, ".doc tbody tr:has(.tiny)") == 3)
    await fill(pg, "label:has-text('Amount (RM)') input", "20")
    await fill(pg, "label:has-text('Cash received') input", "50")
    await pg.wait_for_timeout(200)
    txt = await V(pg, "label:has-text('Cash received')").inner_text()
    check("change to give is calculated", "30.00" in txt, [txt, await state(pg, "JSON.stringify(s.bl.pay)"), await state(pg, "s.change()")])
    await click(pg, "button:has-text('Record RM')")
    check("part payment recorded", "Partially Paid" in await toast(pg))
    await click(pg, "button[role=radio]:has-text('Card')")
    await click(pg, "button:has-text('Record RM')")
    check("card needs approval code", "approval code" in await toast(pg))
    await fill(pg, "label:has-text('Card approval code') input", "APV123")
    await click(pg, "button:has-text('Record RM')")
    check("balance paid in full", "Status: Paid" in await toast(pg))
    await click(pg, "button:has-text('Print receipt') >> nth=0")
    check("receipt prints", await pg.evaluate("window.__printed") >= 1)

    # ---------------- 6.0 claims ----------------
    await goto(pg, "claims")
    await pg.locator("tr:has-text('Draft') input[type=checkbox]").first.check()
    await click(pg, "button:has-text('Submit 1 selected')")
    check("claims submit", "submitted" in await toast(pg))
    await click(pg, ".seg button:has-text('Submitted')")
    await pg.locator("button:has-text('Record response')").first.click()
    await click(pg, ".modal .seg button:has-text('Rejected')")
    await fill(pg, ".modal input[placeholder*='policy expired']", "Missing GL")
    await click(pg, ".modal button:has-text('Save')")
    check("claim rejected", "Rejected" in await toast(pg))
    await click(pg, ".seg button:has-text('Rejected / overdue')")
    await pg.locator("button:has-text('Correct & redo')").first.click()
    check("rejected claim back to draft", "Draft" in await toast(pg))
    await click(pg, "text=Prepare claims")
    check("prepare claims runs", await toast(pg) != "")
    check("receptionist cannot edit coverage rules", await count(pg, ".list button:has-text('Update')") == 0)

    # ---------------- 2.1 schedules, 7.0 reports (manager) ----------------
    await login(pg, "manager.pj")
    check("manager sees rejected-claim alert", "Rejected Claim" in await pg.inner_text("body"))
    await goto(pg, "appointments")
    await click(pg, "button:has-text('2.1 Doctor availability')")
    await pg.wait_for_timeout(600)
    await pg.locator("td .linkbtn").nth(3).click()
    await click(pg, ".modal button:has-text('On leave')")
    await click(pg, ".modal button:has-text('Save')")
    check("2.1 leave saved", "Schedule saved" in await toast(pg))
    check("leave shows on the grid", await count(pg, "td .pill:has-text('Leave')") >= 1)
    await pg.locator("td .linkbtn").nth(3).click()
    await click(pg, ".modal button:has-text('On duty')")
    await fill(pg, ".modal label:has-text('Start') input", "18:00")
    await fill(pg, ".modal label:has-text('End') input", "09:00")
    await click(pg, ".modal button:has-text('Save')")
    check("end before start is refused", "End time" in await toast(pg))
    await click(pg, ".modal button:has-text('Cancel')")
    await goto(pg, "reports")
    await pg.wait_for_timeout(800)
    check("manager branch filter is locked", await count(pg, "select:disabled") >= 1)
    check("6 KPI tiles", await count(pg, ".kpi") == 6, await count(pg, ".kpi"))
    check("charts render (SVG)", await count(pg, "[data-chart] svg") >= 5)
    await pg.locator("[data-chart] rect.bar").first.hover()
    check("chart tooltip on hover", await pg.locator("#tip:not([hidden])").count() == 1)
    await click(pg, ".seg button:has-text('Table')")
    check("table view of revenue", await pg.locator(".card:has-text('Revenue collected per day') table tr").count() > 3)
    await click(pg, ".seg button:has-text('7 days')")
    await pg.wait_for_timeout(600)
    check("7-day preset applies", await state(pg, "s.rp.d.filters.from") == await state(pg, "s.todayStr(-6)"))
    async with pg.expect_download() as dl:
        await pg.locator("button:has-text('Excel')").first.click()
    d = await dl.value
    check("Excel (CSV) export downloads", d.suggested_filename.endswith(".csv"), d.suggested_filename)
    await click(pg, "button:has-text('Export PDF')")
    check("PDF export opens print", await pg.evaluate("window.__printed") >= 1)
    await fill(pg, "label:has-text('From') input", "2030-01-01")
    await click(pg, "button:has-text('Apply')")
    check("From after To is refused", "From date" in await toast(pg))

    # ---------------- 4.0 head office ----------------
    await login(pg, "hq")
    await goto(pg, "pharmacy")
    await click(pg, "button:has-text('Transfers')")
    await pg.wait_for_timeout(500)
    await pg.locator("button:has-text('Approve')").first.click()
    check("head office approves a transfer", "approved" in await toast(pg))
    await goto(pg, "reports")
    await pg.wait_for_timeout(800)
    check("head office sees all branches", await count(pg, ".card:has-text('Billed by branch') text.lbl") >= 10)
    await goto(pg, "messages")
    await pg.wait_for_timeout(2000)
    check("opening messages clears the unread badge", await state(pg, "s.unread") == 0)

    # ---------------- 9.0 admin ----------------
    await login(pg, "admin")
    await goto(pg, "admin")
    await click(pg, "button:has-text('New account')")
    await fill(pg, ".modal label:has-text('Full name') input", "Ui Test Nurse")
    await select(pg, ".modal label:has-text('Role') select", value="nurse")
    await fill(pg, ".modal label:has-text('Username') input", "ui.nurse")
    await fill(pg, ".modal label:has-text('Initial password') input", "short")
    await click(pg, ".modal button:has-text('Save account')")
    check("weak password refused", "Password policy" in await toast(pg))
    await fill(pg, ".modal label:has-text('Initial password') input", "Welcome123")
    await click(pg, ".modal button:has-text('Save account')")
    check("account created", "created" in await toast(pg))
    await pg.locator("tr:has-text('ui.nurse') button:has-text('Edit')").click()
    await select(pg, ".modal label:has-text('Account status') select", value="Deactivated")
    await click(pg, ".modal button:has-text('Save account')")
    check("account deactivated", "updated" in await toast(pg))
    await pg.locator("tr:has-text('ui.nurse') button:has-text('Reset password')").click()
    await click(pg, ".modal button:has-text('Reset password')")
    await pg.wait_for_timeout(500)
    check("reset shows a temporary password", "Temporary password" in await pg.inner_text(".modal"))
    await click(pg, ".modal button:has-text('Done')")
    await click(pg, "button:has-text('Access & audit report')")
    await fill(pg, "input[placeholder*='Filter by user']", "ui.nurse")
    await pg.wait_for_timeout(700)
    check("audit log filter works", await count(pg, "tbody tr") >= 2, await count(pg, "tbody tr"))

    # ---------------- language, idle timeout, mobile ----------------
    await click(pg, ".top .seg button:has-text('BM')")
    check("BM toggle translates the menu", "Pengguna & Audit" in await pg.inner_text(".nav"))
    await click(pg, ".top .seg button:has-text('EN')")
    await pg.evaluate("document.body._x_dataStack[0].lastAct = Date.now() - 280000")
    await pg.wait_for_timeout(5500)
    check("idle warning appears at 4m30s", await visible(pg, ".idle"))
    await pg.evaluate("document.body._x_dataStack[0].lastAct = Date.now() - 301000")
    await pg.wait_for_timeout(6500)
    check("signed out after 5 minutes idle", await visible(pg, ".login") and "inactivity" in await pg.inner_text(".login-form"))

    await pg.set_viewport_size({"width": 390, "height": 844})
    await login(pg, "reception.pj")
    for page in ("patients", "appointments", "billing", "claims"):
        await goto(pg, page)
        overflow = await pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        check(f"mobile: {page} has no sideways scrolling", overflow <= 2, f"{overflow}px")
    for user, page in (("dr.rahman", "consult"), ("hq", "pharmacy"), ("hq", "reports"), ("admin", "admin"), ("hq", "messages")):
        await login(pg, user)
        await goto(pg, page)
        await pg.wait_for_timeout(500)
        overflow = await pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        check(f"mobile: {page} ({user}) has no sideways scrolling", overflow <= 2, f"{overflow}px")
    await pg.set_viewport_size({"width": 1440, "height": 900})


if __name__ == "__main__":
    asyncio.run(main())
