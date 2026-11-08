"""Process 9.0 Manage Users, Roles (DFD L0)
In : Administrator -> Account & Role Details     Out: Administrator <- Access & Audit Reports
Store: D7 User Account & System Log (USER_ACCOUNT, AUDIT_LOG; STAFF holds the role)."""
import re
import secrets

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

from .auth import body, current, requires
from .db import audit, db, next_id, one, rows
from .validate import must_exist, text

bp = Blueprint("p9", __name__, url_prefix="/api")
ROLES = ["admin", "doctor", "dentist", "nurse", "pharmacy", "receptionist", "branch_manager", "head_office"]


def strong(pw):
    return isinstance(pw, str) and len(pw) >= 8 and re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)


@bp.get("/users")
@requires("9.0")
def users():
    return jsonify(users=rows("""SELECT u.user_id, u.username, u.account_status, u.last_login, s.* , b.branch_name
                                 FROM user_account u JOIN staff s USING(staff_id) JOIN branch b ON b.branch_id=s.branch_id
                                 ORDER BY b.branch_id, s.role, s.full_name"""),
                   roles=ROLES, branches=rows("SELECT branch_id, branch_name FROM branch"))


@bp.post("/users")
@requires("9.0")
def create():
    d = body()
    need = ["full_name", "role", "branch_id", "username", "password"]
    if any(not text(d.get(k)) for k in need) or d["role"] not in ROLES:
        return jsonify(error="Name, role, branch, username and password are required."), 422
    must_exist("branch", "branch_id", d["branch_id"], "Branch", 422)
    d["username"] = text(d["username"]).lower()
    if not d["username"].replace(".", "").replace("_", "").isalnum():
        return jsonify(error="Username may contain letters, numbers, dots and underscores only."), 422
    if not strong(d["password"]):
        return jsonify(error="Password policy: at least 8 characters with letters and numbers."), 422
    if one("SELECT 1 FROM user_account WHERE username=?", d["username"]):
        return jsonify(error="That username is taken."), 409
    sid, uid = next_id("staff"), next_id("user_account")
    db().execute("INSERT INTO staff VALUES (?,?,?,?,?,?,?,?)", (sid, d["branch_id"], text(d["full_name"]), d["role"],
                 text(d.get("specialisation")) or None, text(d.get("phone")) or None, text(d.get("email")) or None, "Active"))
    db().execute("INSERT INTO user_account(user_id, staff_id, username, password, account_status, must_change_password) "
                 "VALUES (?,?,?,?,?,1)", (uid, sid, d["username"], generate_password_hash(d["password"]), "Active"))
    audit("CREATE account", "user_account", uid)
    db().commit()
    return jsonify(ok=True, message=f"Account {d['username']} created.")


@bp.put("/users/<uid>")
@requires("9.0")
def edit(uid):
    d = body()
    u = must_exist("user_account", "user_id", uid, "User")
    if not isinstance(d.get("role"), str) or d["role"] not in ROLES or not text(d.get("full_name")) or not text(d.get("branch_id")):
        return jsonify(error="Name, role and branch are required."), 422
    must_exist("branch", "branch_id", d["branch_id"], "Branch", 422)
    if uid == current()["user_id"] and (d["role"] != "admin" or d.get("account_status", "Active") != "Active"):
        return jsonify(error="You cannot remove your own administrator access."), 422
    db().execute("UPDATE staff SET role=?, branch_id=?, specialisation=?, full_name=? WHERE staff_id=?",
                 (d["role"], d["branch_id"], text(d.get("specialisation")) or None, text(d["full_name"]), u["staff_id"]))
    st = "Active" if d.get("account_status", "Active") == "Active" else "Deactivated"
    db().execute("UPDATE user_account SET account_status=? WHERE user_id=?", (st, uid))
    db().execute("UPDATE staff SET status=? WHERE staff_id=?", ("Active" if st == "Active" else "Inactive", u["staff_id"]))
    audit(f"EDIT account ({d['role']}, {st})", "user_account", uid)
    db().commit()
    return jsonify(ok=True, message="Account updated.")


@bp.post("/users/<uid>/reset")
@requires("9.0")
def reset(uid):
    must_exist("user_account", "user_id", uid, "User")
    temp = "Sfc" + secrets.token_hex(3) + "9"
    db().execute("UPDATE user_account SET password=?, must_change_password=1 WHERE user_id=?", (generate_password_hash(temp), uid))
    audit("RESET password", "user_account", uid)
    db().commit()
    return jsonify(ok=True, message=f"Temporary password: {temp}  (they must choose a new one when they sign in)")


@bp.get("/audit")
@requires("9.0")
def audit_report():
    a = request.args
    sql = """SELECT l.*, u.username, s.full_name, s.role FROM audit_log l LEFT JOIN user_account u USING(user_id)
             LEFT JOIN staff s ON s.staff_id=u.staff_id WHERE 1=1"""
    args = []
    if a.get("q", "").strip():
        sql += """ AND (u.username LIKE ? OR s.full_name LIKE ? OR l.action LIKE ? OR l.table_affected LIKE ? OR l.record_id LIKE ?
                   OR l.record_id IN (SELECT user_id FROM user_account WHERE username LIKE ?))"""
        args += [f"%{a['q'].strip()}%"] * 6
    return jsonify(log=rows(sql + " ORDER BY l.log_id DESC LIMIT 200", *args))
