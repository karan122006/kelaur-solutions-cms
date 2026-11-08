"""Process 9.0 support: login, role-based access, 5-minute inactivity logout.
SRS 5.3.4: unique login, role-based access, auto logout after 5 min, audit log."""
import time
from functools import wraps

from flask import jsonify, request, session
from werkzeug.security import check_password_hash

from .db import audit, now, one, db

IDLE_SECONDS = 5 * 60

# Which roles may use each DFD process (FR-11 "each role receives the access it needs")
ACCESS = {
    "1.0": {"receptionist", "nurse", "doctor", "dentist", "pharmacy", "branch_manager", "admin"},
    "1.0w": {"receptionist"},
    "2.0": {"receptionist", "nurse", "doctor", "dentist", "branch_manager"},
    "2.0w": {"receptionist"},
    "2.1": {"branch_manager"},
    "3.0": {"doctor", "dentist", "nurse"},
    "3.0w": {"doctor", "dentist"},
    "4.0": {"pharmacy", "branch_manager", "head_office"},
    "4.0w": {"pharmacy"},
    "4.0a": {"branch_manager", "head_office"},  # approve transfers
    "5.0": {"receptionist", "branch_manager"},
    "6.0": {"receptionist", "branch_manager", "head_office"},
    "7.0": {"branch_manager", "head_office"},
    "8.0": {"receptionist", "nurse", "doctor", "dentist", "pharmacy", "branch_manager", "head_office", "admin"},
    "9.0": {"admin"},
}


def current():
    return {
        "user_id": session.get("user_id"), "staff_id": session.get("staff_id"),
        "role": session.get("role"), "branch_id": session.get("branch_id"),
        "full_name": session.get("full_name"),
    }


def login(username, password):
    u = one(
        """SELECT u.*, s.role, s.branch_id, s.full_name, s.specialisation FROM user_account u
           JOIN staff s ON s.staff_id = u.staff_id WHERE u.username = ?""", username)
    if not u or not check_password_hash(u["password"], password):
        return None, "Incorrect username or password."
    if u["account_status"] != "Active":
        return None, "This account has been deactivated. Please contact the administrator."
    session.clear()
    session.update(user_id=u["user_id"], staff_id=u["staff_id"], role=u["role"],
                   branch_id=u["branch_id"], full_name=u["full_name"], seen=time.time())
    db().execute("UPDATE user_account SET last_login=? WHERE user_id=?", (now(), u["user_id"]))
    audit("LOGIN", "user_account", u["user_id"])
    db().commit()
    return u, None


def requires(process):
    """Decorator: user must be logged in, active within 5 min, and hold a role for the process."""
    def deco(fn):
        @wraps(fn)
        def inner(*a, **kw):
            if "user_id" not in session:
                return jsonify(error="Please sign in."), 401
            if time.time() - session.get("seen", 0) > IDLE_SECONDS:
                session.clear()
                return jsonify(error="You were signed out after 5 minutes of inactivity."), 401
            session["seen"] = time.time()
            if session["role"] not in ACCESS[process]:
                return jsonify(error="Your role does not have access to this function."), 403
            return fn(*a, **kw)
        return inner
    return deco


def body():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}
