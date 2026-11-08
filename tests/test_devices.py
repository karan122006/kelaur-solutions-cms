"""Phone / tablet layout test: every screen state, for every role, on 11 device sizes.
Automatic checks on each screen: no sideways scrolling, no overlapping text or controls, no text cut off,
no card that scrolls sideways by accident, tap targets big enough, text not too small.
Full-page screenshots go to tests/device_shots/<device>/ for review by eye.

Run from the project folder (needs: pip install playwright && python -m playwright install chromium):
    python tests/test_devices.py
"""
import asyncio
from http.cookiejar import CookieJar
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 5057
B = f"http://127.0.0.1:{PORT}/"
CHROME = os.environ.get("CHROME_PATH")
SHOTS = os.path.join(ROOT, "tests", "device_shots")
ONLY = os.environ.get("DEVICES")          # e.g. DEVICES="Galaxy S8,iPhone 14" to run a subset

DEVICES = [  # name, width, height, scale, mobile/touch
    ("Galaxy Z Fold (folded)", 280, 653, 3, True), ("Galaxy S8", 360, 740, 3, True), ("iPhone SE", 375, 667, 2, True),
    ("iPhone 13 mini", 375, 812, 3, True), ("iPhone 14", 390, 844, 3, True), ("Pixel 7", 412, 915, 2.6, True),
    ("iPhone 14 Pro Max", 430, 932, 3, True), ("iPhone 14 landscape", 844, 390, 3, True), ("iPad mini", 768, 1024, 2, True),
    ("iPad Air landscape", 1180, 820, 2, True), ("Laptop", 1366, 768, 1, False),
]

CHECK_JS = r"""
() => {
  const vw = window.innerWidth, out = {overflow: 0, overlaps: [], clipped: [], cardScroll: [], small: [], tiny: []};
  out.overflow = document.documentElement.scrollWidth - vw;
  const vis = e => { const s = getComputedStyle(e); if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) return false;
                     const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const name = e => (e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).slice(0,2).join('.') : '')
                     + ' "' + (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().slice(0, 28) + '"');
  const skip = e => e.closest('svg, #print, .toast, #tip, .idle, [aria-hidden=true]');
  const all = [...document.querySelectorAll('body *')].filter(e => !skip(e) && vis(e));
  const leaves = all.filter(e => ['INPUT','SELECT','TEXTAREA','BUTTON','IMG'].includes(e.tagName)
     || [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()));
  // overlaps between leaves that are not nested in each other
  // visible part of each element after clipping by scrolling / overflow-hidden ancestors
  const clipOne = (e, r) => { let L = r.left, T = r.top, R = r.right, Bm = r.bottom;
    for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) {
      const s = getComputedStyle(a); if (s.overflowX === 'visible' && s.overflowY === 'visible') continue;
      const ar = a.getBoundingClientRect(); L = Math.max(L, ar.left); T = Math.max(T, ar.top); R = Math.min(R, ar.right); Bm = Math.min(Bm, ar.bottom); }
    return {left: L, top: T, right: R, bottom: Bm}; };
  // inline text that wraps onto several lines is measured line by line, not as one big box
  const frags = e => (getComputedStyle(e).display === 'inline' ? [...e.getClientRects()] : [e.getBoundingClientRect()])
                      .map(r => clipOne(e, r)).filter(r => r.right - r.left > 1 && r.bottom - r.top > 1);
  const rects = [];
  for (const e of leaves) for (const r of frags(e)) rects.push([e, r]);
  for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
    const [a, ra] = rects[i], [b, rb] = rects[j];
    if (a === b || a.contains(b) || b.contains(a)) continue;
    const ox = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left), oy = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
    if (ox > 3 && oy > 3) {
      // ignore pairs where one is inside a fixed overlay above the other (modals, drawer) - only same-layer overlaps count
      const la = a.closest('.modal, .side, .scrim, .top'), lb = b.closest('.modal, .side, .scrim, .top');
      if (la !== lb) continue;
      out.overlaps.push(name(a) + ' × ' + name(b));
    }
  }
  // text cut off
  for (const e of leaves) {
    if (['INPUT','SELECT','TEXTAREA','IMG'].includes(e.tagName)) continue;
    const s = getComputedStyle(e);
    if (e.scrollWidth > e.clientWidth + 2 && e.clientWidth > 0 && ['hidden','clip'].includes(s.overflowX) && s.textOverflow !== 'ellipsis') out.clipped.push(name(e));
    const r = e.getBoundingClientRect();
    if (r.right > vw + 1 && !e.closest('.scroll, .tabs, .side')) out.clipped.push('off-screen: ' + name(e));
    const fs = parseFloat(s.fontSize);
    if (fs < 10.5) out.tiny.push(name(e) + ' ' + fs + 'px');
  }
  // cards that scroll sideways (intended only for the stock matrix and the bill)
  for (const c of all.filter(e => e.matches('.card, .scroll'))) {
    if (c.scrollWidth > c.clientWidth + 2 && !c.querySelector('table.keep')) out.cardScroll.push(name(c) + ' +' + (c.scrollWidth - c.clientWidth) + 'px');
  }
  // tap targets (touch screens)
  for (const e of all.filter(e => e.matches('button, a.btn, input:not([type=checkbox]):not([type=radio]), select, .slot, .chip, .tile, .list li[tabindex]'))) {
    const r = e.getBoundingClientRect();
    if (e.closest('.chart')) continue;
    if (r.height < 30 || r.width < 30) out.small.push(name(e) + ` ${Math.round(r.width)}x${Math.round(r.height)}`);
  }
  for (const k of ['overlaps','clipped','cardScroll','small','tiny']) out[k] = [...new Set(out[k])];
  return out;
}
"""

results = []


def call(path, data=None, jar=None):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(B + path.lstrip("/"), data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json", "X-Requested-With": "SFC-CMS"},
                                 method="POST" if data is not None else "GET")
    with opener.open(req) as r:
        return json.loads(r.read() or b"{}")


def as_user(user):
    jar = CookieJar()
    call("/api/login", {"username": user, "password": "Sfc@2026"}, jar)
    return jar


def make_data():
    """Fresh visits so the pharmacy queue and an unpaid bill exist for the screenshots."""
    out = {}
    for n, rx in ((1, True), (2, False)):
        j = as_user("reception.pj")
        pid = call("/api/patients", {"full_name": f"Siti Nurhaliza binti Abdul Rahman {n}", "ic_passport_no": f"9001011400{n:02d}",
                                     "date_of_birth": "1990-01-01", "gender": "Female", "phone": f"01234500{n:02d}",
                                     "emergency_contact": "Abdul Rahman bin Hashim - 0198887766", "allergies": "Penicillin, seafood",
                                     "provider_id": "PP0000002", "policy_no": "MYH-77881"}, j)["patient_id"]
        q = call("/api/walkin", {"patient_id": pid}, j)["queue"]
        n_ = as_user("nurse.pj")
        call(f"/api/consult/{q['queue_id']}/vitals", {"temp": 37.8, "bp": "128/84", "pulse": 90, "weight": 58}, n_)
        d = as_user("dr.rahman")
        body = {"diagnosis": "Acute upper respiratory tract infection with mild dehydration", "symptoms": "Fever 2 days",
                "procedures": ["Blood glucose test"]}
        if rx:
            body["prescription"] = [{"medication_id": "MD0000001", "dosage": "1 tab 4x daily when fever", "quantity": 10},
                                    {"medication_id": "MD0000012", "dosage": "1 sachet after each loose stool", "quantity": 6}]
        r = call(f"/api/consult/{q['queue_id']}/complete", body, d)
        out[n] = r
    j = as_user("reception.pj")
    out["bill"] = call(f"/api/billing/generate/{out[2]['consultation_id']}", {}, j)["bill"]["bill_id"]
    return out


async def login(pg, user):
    await pg.goto(B)
    await pg.wait_for_timeout(250)
    await pg.evaluate("fetch('/api/logout',{method:'POST',headers:{'X-Requested-With':'SFC-CMS'}})")
    await pg.goto(B)
    await pg.wait_for_timeout(300)
    await pg.fill("input[autocomplete=username]", user)
    await pg.fill("input[type=password]", "Sfc@2026")
    await pg.click("form .btn.lg")
    await pg.wait_for_timeout(700)


async def go(pg, page, wait=700):
    await pg.goto(B + "#" + page)
    await pg.wait_for_timeout(wait)


def V(pg, sel):
    return pg.locator(sel + " >> visible=true").first


# each state: (role, name, async setup(pg))
async def s_login(pg): await pg.goto(B); await pg.wait_for_timeout(500)
async def s_drawer(pg): await go(pg, "home"); await V(pg, ".menu-btn").click() if await pg.locator(".menu-btn >> visible=true").count() else None; await pg.wait_for_timeout(400)
async def s_patient(pg):
    await go(pg, "patients"); await V(pg, "input[type=search]").fill("Siti Nurhaliza"); await pg.wait_for_timeout(600)
    await V(pg, ".list li").click(); await pg.wait_for_timeout(600)
async def s_register(pg):
    await go(pg, "patients"); await V(pg, "text=Register new patient").click(); await V(pg, "form >> text=Continue").click(); await pg.wait_for_timeout(300)
async def s_book(pg):
    await go(pg, "appointments"); await V(pg, "input[placeholder='Name, IC, phone or ID']").fill("Siti"); await pg.wait_for_timeout(600)
    await V(pg, ".list li").click(); await V(pg, ".slot:not([disabled])").click(); await pg.wait_for_timeout(300)
async def s_daily(pg): await go(pg, "appointments"); await V(pg, ".tabs button:has-text('Daily list')").click(); await pg.wait_for_timeout(600)
async def s_queue(pg): await go(pg, "appointments"); await V(pg, ".tabs button:has-text('Queue board')").click(); await pg.wait_for_timeout(600)
async def s_sched(pg): await go(pg, "appointments"); await V(pg, ".tabs button:has-text('Doctor availability')").click(); await pg.wait_for_timeout(600)
async def s_sched_modal(pg): await s_sched(pg); await V(pg, "td .linkbtn").click(); await pg.wait_for_timeout(300)
async def s_billing(pg):
    await go(pg, "billing"); await V(pg, ".list li:has-text('Siti Nurhaliza')").click(); await pg.wait_for_timeout(700)
async def s_claims(pg): await go(pg, "claims", 900)
async def s_messages(pg): await go(pg, "messages", 900)
async def s_home(pg): await go(pg, "home", 900)
async def s_consult_nurse(pg):
    await go(pg, "consult"); await V(pg, ".list li").click(); await pg.wait_for_timeout(700)
async def s_consult_doc(pg):
    await go(pg, "consult"); await V(pg, ".list li").click(); await pg.wait_for_timeout(700)
    await V(pg, "text=Add medicine").click(); await V(pg, ".chip").click(); await pg.wait_for_timeout(300)
async def s_rx(pg):
    await go(pg, "pharmacy"); await V(pg, ".list li:has-text('Siti Nurhaliza')").click(); await pg.wait_for_timeout(500)
async def s_stock(pg): await go(pg, "pharmacy"); await V(pg, ".tabs button:has-text('Branch stock')").click(); await pg.wait_for_timeout(700)
async def s_receive(pg): await s_stock(pg); await V(pg, "button:has-text('Receive stock')").click(); await pg.wait_for_timeout(300)
async def s_transfers(pg): await go(pg, "pharmacy"); await V(pg, ".tabs button:has-text('Transfers')").click(); await pg.wait_for_timeout(700)
async def s_network(pg): await go(pg, "pharmacy"); await V(pg, ".tabs button:has-text('Network')").click(); await pg.wait_for_timeout(700)
async def s_reports(pg): await go(pg, "reports", 1200)
async def s_users(pg): await go(pg, "admin", 900)
async def s_user_modal(pg): await s_users(pg); await V(pg, "button:has-text('New account')").click(); await pg.wait_for_timeout(300)
async def s_audit(pg): await s_users(pg); await V(pg, "button:has-text('Access & audit')").click(); await pg.wait_for_timeout(700)
async def s_password(pg): await go(pg, "home"); await pg.evaluate("document.body._x_dataStack[0].pw={current:'',new:'',confirm:'',forced:false,err:''}"); await pg.wait_for_timeout(300)

STATES = [
    (None, "01 sign-in", s_login),
    ("reception.pj", "02 home", s_home), ("reception.pj", "03 menu drawer", s_drawer), ("reception.pj", "04 patient record", s_patient),
    ("reception.pj", "05 register form errors", s_register), ("reception.pj", "06 book appointment", s_book),
    ("reception.pj", "07 daily list", s_daily), ("reception.pj", "08 queue board", s_queue), ("reception.pj", "09 billing", s_billing),
    ("reception.pj", "10 claims", s_claims), ("reception.pj", "11 messages", s_messages), ("reception.pj", "12 change password", s_password),
    ("nurse.pj", "13 vitals", s_consult_nurse), ("dr.rahman", "14 consultation", s_consult_doc),
    ("pharmacy.pj", "15 dispense", s_rx), ("pharmacy.pj", "16 branch stock", s_stock), ("pharmacy.pj", "17 receive stock", s_receive),
    ("manager.pj", "18 doctor availability", s_sched), ("manager.pj", "19 availability dialog", s_sched_modal),
    ("manager.pj", "20 branch report", s_reports), ("hq", "21 network stock", s_network), ("hq", "22 transfers", s_transfers),
    ("hq", "23 all-branch report", s_reports), ("admin", "24 users", s_users), ("admin", "25 new account", s_user_modal),
    ("admin", "26 audit log", s_audit),
]


async def main():
    db = os.path.join(tempfile.mkdtemp(), "dev_test.db")
    env = {**os.environ, "CMS_DB": db, "PORT": str(PORT)}
    subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, r'{ROOT}'); from backend.seed import build; build(r'{db}')"],
                   check=True, env=env)
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "app.py")], env=env, cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(B, timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    make_data()
    problems = 0
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(**({"executable_path": CHROME} if CHROME else {}), args=["--no-sandbox"])
            for (dname, w, h, scale, mobile) in DEVICES:
                if ONLY and dname not in ONLY.split(","):
                    continue
                ctx = await browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1 if not mobile else min(scale, 2),
                                                is_mobile=mobile, has_touch=mobile)
                await ctx.add_init_script("window.print = () => {}")
                pg = await ctx.new_page()
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                folder = os.path.join(SHOTS, dname.replace(" ", "_").replace("(", "").replace(")", ""))
                os.makedirs(folder, exist_ok=True)
                current = "?"
                for role, sname, fn in STATES:
                    try:
                        if role and role != current:
                            await login(pg, role)
                            current = role
                        if role is None:
                            await pg.goto(B)
                            await pg.evaluate("fetch('/api/logout',{method:'POST',headers:{'X-Requested-With':'SFC-CMS'}})")
                            current = None
                        await fn(pg)
                        r = await pg.evaluate(CHECK_JS)
                        await pg.screenshot(path=os.path.join(folder, sname.replace(" ", "_") + ".png"), full_page=True)
                    except Exception as e:
                        r = {"overflow": 0, "overlaps": [], "clipped": [], "cardScroll": [], "small": [], "tiny": [],
                             "error": str(e).splitlines()[0][:160]}
                    bad = {k: v for k, v in r.items() if (k == "overflow" and v > 1) or (k in ("overlaps", "clipped", "cardScroll", "error") and v)}
                    warn = {k: r[k] for k in ("small", "tiny") if r.get(k) and mobile}
                    results.append((dname, sname, bad, warn))
                    if bad:
                        problems += 1
                        print(f"FAIL {dname:24} {sname:26} {json.dumps(bad)[:400]}")
                    elif warn:
                        print(f"warn {dname:24} {sname:26} {json.dumps(warn)[:300]}")
                    else:
                        print(f"PASS {dname:24} {sname}")
                    # close anything left open so the next state starts clean
                    await pg.evaluate("""(()=>{const s=document.body._x_dataStack&&document.body._x_dataStack[0]; if(s){s.navOpen=false;s.pw=null;s.modal=null;
                        if(s.ap){s.ap.sForm=null} if(s.ph){s.ph.recv=null;s.ph.adj=null;s.ph.tr=null} if(s.ad){s.ad.form=null}}})()""")
                if errs:
                    problems += 1
                    print(f"FAIL {dname}: JavaScript errors {errs[:3]}")
                await ctx.close()
            await browser.close()
    finally:
        srv.terminate()
    total = len(results)
    print(f"\n{total - problems} of {total} screen checks passed on {len({r[0] for r in results})} devices"
          f" ({sum(1 for r in results if r[3])} with minor tap-size/text-size notes).")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    asyncio.run(main())
