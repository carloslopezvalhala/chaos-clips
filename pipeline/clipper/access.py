"""Password protection for the panel when it's reachable from the internet (Cloudflare tunnel).

Requests arriving through the tunnel carry Cloudflare headers; those always need a login.
Requests made on the PC itself (no Cloudflare headers, from 127.0.0.1) are trusted."""
import json
import secrets
import time
from datetime import timedelta

from flask import jsonify, redirect, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .common import ROOT

ACCESS = ROOT / "acceso.json"
SECRET = ROOT / "secreto.key"
OPEN_PATHS = {"/login", "/api/login", "/manifest.json"}
MAX_FAILS, LOCK_SECONDS = 8, 15 * 60
_fails = {}  # ip -> [count, first_fail_time]


def setup(app):
    if not SECRET.exists():
        SECRET.write_text(secrets.token_hex(32))
    app.secret_key = SECRET.read_text().strip()
    app.permanent_session_lifetime = timedelta(days=30)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    app.before_request(_guard)


def is_local():
    return (request.remote_addr in ("127.0.0.1", "::1")
            and not request.headers.get("Cf-Connecting-Ip") and not request.headers.get("Cf-Ray"))


def client_ip():
    return request.headers.get("Cf-Connecting-Ip") or request.remote_addr


def password_set():
    return ACCESS.exists()


def set_password(pw):
    ACCESS.write_text(json.dumps({"hash": generate_password_hash(pw)}))


def _guard():
    if is_local() or request.path in OPEN_PATHS or session.get("ok"):
        return None
    if request.path.startswith(("/api/", "/video/", "/pvideo/")):
        return jsonify({"ok": False, "error": "Sesión caducada. Vuelve a entrar."}), 401
    return redirect("/login")


def login():
    """POST /api/login {password}. Returns a JSON response."""
    ip = client_ip()
    count, first = _fails.get(ip, [0, time.time()])
    if count >= MAX_FAILS and time.time() - first < LOCK_SECONDS:
        return jsonify({"ok": False, "error": "Demasiados intentos. Espera 15 minutos."}), 429
    if not password_set():
        return jsonify({"ok": False, "error": "Aún no hay contraseña. Créala desde el panel en tu PC."}), 403
    pw = (request.get_json(silent=True) or {}).get("password", "")
    if check_password_hash(json.loads(ACCESS.read_text())["hash"], pw):
        _fails.pop(ip, None)
        session.permanent = True
        session["ok"] = True
        return jsonify({"ok": True})
    if time.time() - first >= LOCK_SECONDS:
        count, first = 0, time.time()
    _fails[ip] = [count + 1, first]
    return jsonify({"ok": False, "error": "Contraseña incorrecta."}), 401
