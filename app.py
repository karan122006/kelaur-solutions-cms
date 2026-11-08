"""Sunrise Family Clinics - Clinic Management System (CMS)
Designed by Keluar Solutions.   Run:  python app.py   then open http://127.0.0.1:5000

Each blueprint below is one process from the DFD Level-0 (Figure 6.2):
  1.0 Manage Patient Registration & Records      2.0 Manage Appointments
  3.0 Manage Consultation & Medical Records      4.0 Manage Pharmacy Dispensing & Stock
  5.0 Manage Billing & Payments                  6.0 Manage Insurance & Panel Claims
  7.0 Generate Reports & Dashboard               8.0 Send Notifications & Reminders
  9.0 Manage Users, Roles

Settings (environment variables, all optional):
  HOST=0.0.0.0        let other PCs / tablets on the clinic network connect (default: this PC only)
  PORT=5000           port to listen on
  CMS_HTTPS=1         mark the sign-in cookie Secure (set this when served behind HTTPS)
  CMS_DEMO=0          hide the demo-account buttons on the sign-in page
  CMS_DB=path         database file (default data/cms.db)
"""
import gzip
import hashlib
import logging
import os
import secrets
import sqlite3
import threading
import time
from logging.handlers import RotatingFileHandler

from flask import Flask, Response, g, jsonify, request, session

from backend import auth
from backend.auth import body, current, requires
from backend.db import DB_PATH, close, one, rows
from backend.validate import Invalid
from backend import (backup, p1_patients, p2_appointments, p3_consultation, p4_pharmacy, p5_billing,
                     p6_claims, p7_reports, p8_notify, p9_users)

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.dirname(os.path.abspath(DB_PATH))
os.makedirs(os.path.join(DATA, "logs"), exist_ok=True)
DEMO = os.environ.get("CMS_DEMO", "1") != "0"


def secret_key():
    """Kept in data/secret.key so restarting the server does not sign everybody out."""
    if os.environ.get("CMS_SECRET"):
        return os.environ["CMS_SECRET"]
    path = os.path.join(DATA, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    return open(path).read().strip()


app = Flask(__name__, static_folder=os.path.join(ROOT, "static"), static_url_path="/static")
app.config.update(SECRET_KEY=secret_key(), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                  SESSION_COOKIE_SECURE=os.environ.get("CMS_HTTPS") == "1", SESSION_COOKIE_NAME="sfc_session",
                  PERMANENT_SESSION_LIFETIME=8 * 3600, SEND_FILE_MAX_AGE_DEFAULT=31536000,
                  MAX_CONTENT_LENGTH=1 * 1024 * 1024, JSON_SORT_KEYS=False)
app.teardown_appcontext(close)
for m in (p1_patients, p2_appointments, p3_consultation, p4_pharmacy, p5_billing, p6_claims, p7_reports, p8_notify, p9_users):
    app.register_blueprint(m.bp)

# ---------------------------------------------------------------- logging
log = logging.getLogger("cms")
log.setLevel(logging.INFO)
_fh = RotatingFileHandler(os.path.join(DATA, "logs", "cms.log"), maxBytes=2_000_000, backupCount=5, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_fh)

# ---------------------------------------------------------------- static asset versioning (no stale CSS/JS after an update)
def asset_version():
    h = hashlib.md5()
    for f in ("static/css/app.css", "static/js/app.js", "index.html"):
        h.update(str(os.path.getmtime(os.path.join(ROOT, f))).encode())
    return h.hexdigest()[:10]


@app.get("/")
def index():
    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    html = html.replace("__V__", asset_version()).replace("__DEMO__", "true" if DEMO else "false")
    r = Response(html, mimetype="text/html")
    r.headers["Cache-Control"] = "no-cache"
    return r


# ---------------------------------------------------------------- request guards
LOGIN_FAILS = {}            # (ip, username) -> [timestamps]
_lock = threading.Lock()
MAX_FAILS, WINDOW = 5, 10 * 60


@app.before_request
def guards():
    g.t0 = time.time()
    if request.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        # CSRF protection: browsers cannot add this header to a cross-site request without permission
        if request.headers.get("X-Requested-With") != "SFC-CMS":
            return jsonify(error="Request blocked (missing security header). Reload the page and try again."), 403


@app.after_request
def headers(r):
    h = r.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "same-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    h["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                    "script-src 'self' 'unsafe-eval'; connect-src 'self'; frame-ancestors 'none'; "
                                    "base-uri 'self'; form-action 'self'")
    if request.path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
    elif request.path.startswith("/static/") and request.args.get("v"):
        h["Cache-Control"] = "public, max-age=31536000, immutable"
    # gzip text responses (about 75% smaller over the clinic network)
    if (r.status_code == 200 and "gzip" in request.headers.get("Accept-Encoding", "") and "Content-Encoding" not in h
            and (r.mimetype or "").split("/")[0] in ("text", "application")
            and r.mimetype not in ("application/octet-stream",) and not r.mimetype.startswith("image")):
        r.direct_passthrough = False
        data = r.get_data()
        if len(data) > 1024:
            r.set_data(gzip.compress(data, 6))
            h["Content-Encoding"] = "gzip"
            h["Vary"] = "Accept-Encoding"
            h["Content-Length"] = str(len(r.get_data()))
    if request.path.startswith("/api/") and r.status_code >= 400:
        log.warning("%s %s %s -> %s", request.remote_addr, request.method, request.path, r.status_code)
    return r


# ---------------------------------------------------------------- auth endpoints
@app.post("/api/login")
def login():
    d = body()
    user = d.get("username") if isinstance(d.get("username"), str) else ""
    pw = d.get("password") if isinstance(d.get("password"), str) else ""
    key = (request.remote_addr, user.strip().lower())
    now = time.time()
    with _lock:
        fails = [t for t in LOGIN_FAILS.get(key, []) if now - t < WINDOW]
        LOGIN_FAILS[key] = fails
    if len(fails) >= MAX_FAILS:
        wait = int((WINDOW - (now - fails[0])) / 60) + 1
        return jsonify(error=f"Too many failed attempts. Try again in {wait} minute(s) or ask the administrator."), 429
    u, err = auth.login(user.strip(), pw)
    if err:
        with _lock:
            LOGIN_FAILS.setdefault(key, []).append(now)
        log.warning("failed login for %r from %s", user[:40], request.remote_addr)
        return jsonify(error=err), 401
    with _lock:
        LOGIN_FAILS.pop(key, None)
    session.permanent = True
    return jsonify(ok=True, user=current(), must_change_password=bool(u["must_change_password"]))


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
@requires("8.0")
def me():
    u = one("SELECT must_change_password FROM user_account WHERE user_id=?", current()["user_id"])
    return jsonify(user=current(), must_change_password=bool(u and u["must_change_password"]))


@app.post("/api/password")
@requires("8.0")
def change_password():
    """Any signed-in user changes their own password (required after an administrator reset)."""
    from werkzeug.security import check_password_hash, generate_password_hash
    from backend.db import audit, db
    d = body()
    cur, new = d.get("current"), d.get("new")
    u = one("SELECT * FROM user_account WHERE user_id=?", current()["user_id"])
    if not isinstance(cur, str) or not check_password_hash(u["password"], cur):
        return jsonify(error="Your current password is not correct."), 422
    if not p9_users.strong(new):
        return jsonify(error="New password: at least 8 characters with letters and numbers."), 422
    if new == cur:
        return jsonify(error="Choose a password different from the current one."), 422
    db().execute("UPDATE user_account SET password=?, must_change_password=0 WHERE user_id=?",
                 (generate_password_hash(new), u["user_id"]))
    audit("CHANGE password", "user_account", u["user_id"])
    db().commit()
    return jsonify(ok=True, message="Password changed.")


@app.get("/api/ref")
@requires("8.0")
def ref():
    """Reference lists used by the input forms (drop-downs, not free text)."""
    return jsonify(branches=rows("SELECT branch_id, branch_name, city FROM branch ORDER BY branch_id"),
                   providers=rows("SELECT provider_id, provider_name, copay_rate FROM panel_provider ORDER BY provider_name"),
                   doctors=rows("""SELECT staff_id, full_name, specialisation, branch_id FROM staff
                                   WHERE role IN ('doctor','dentist') AND status='Active' ORDER BY full_name"""))


@app.get("/api/health")
def health():
    try:
        one("SELECT 1 AS ok")
        return jsonify(ok=True, version=asset_version())
    except Exception:
        return jsonify(ok=False), 503


# ---------------------------------------------------------------- errors
@app.errorhandler(Invalid)
def invalid(e):
    out = {"error": str(e)}
    if e.fields:
        out["fields"] = e.fields
    return jsonify(out), e.status


@app.errorhandler(404)
def nf(_):
    if not request.path.startswith("/api/"):
        return "Page not found", 404
    return jsonify(error="Not found"), 404


@app.errorhandler(405)
def bad_method(_):
    return jsonify(error="Method not allowed"), 405


@app.errorhandler(413)
def too_big(_):
    return jsonify(error="Request too large."), 413


@app.errorhandler(sqlite3.IntegrityError)
def integrity(e):
    log.warning("integrity error on %s: %s", request.path, e)
    return jsonify(error="That change conflicts with existing records (it may already have been saved). Refresh and try again."), 409


@app.errorhandler(Exception)
def server_error(e):
    if hasattr(e, "code") and isinstance(getattr(e, "code"), int) and e.code < 500:
        return jsonify(error=getattr(e, "description", "Request error")), e.code
    log.exception("unhandled error on %s %s", request.method, request.path)
    return jsonify(error="Something went wrong on the server. Please try again; if it keeps happening, tell the administrator."), 500


def prepare():
    if not os.path.exists(DB_PATH):
        from backend.seed import build
        build()
        print("Demo data created. Password for every demo account: Sfc@2026")
    from backend.db import migrate
    migrate()
    backup.start_daily()


if __name__ == "__main__":
    prepare()
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", 5000))
    try:
        from waitress import serve
        print(f"\n  Sunrise Family Clinics CMS (production server) running at  http://{'127.0.0.1' if host == '127.0.0.1' else host}:{port}")
        print("  Keep this window open. Press Ctrl+C to stop.\n")
        log.info("server start on %s:%s", host, port)
        serve(app, host=host, port=port, threads=8, ident="SFC-CMS")
    except ImportError:
        print("\n  waitress is not installed (pip install waitress); using the development server.\n")
        app.run(host=host, port=port, debug=False, threaded=True)
