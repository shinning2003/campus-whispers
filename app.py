"""Campus Whispers — accountability board for a class.

Posters register a REAL NAME + EMAIL + PASSWORD, choose a public HANDLE.
The handle is shown publicly; only the admin (owner) can see the real
identity behind a handle, and can ban/delete anyone who misbehaves.
"""
import os
import re
import sqlite3
from datetime import datetime, timezone

from flask import Flask, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DB_PATH=os.environ.get("DB_PATH", "campus_whispers.db"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "admin123"),
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
    )
    if config:
        app.config.update(config)

    @app.post("/api/register")
    def register():
        p = request.get_json(silent=True) or {}
        real_name = (p.get("real_name") or "").strip()
        email = (p.get("email") or "").strip().lower()
        password = p.get("password") or ""
        handle = (p.get("handle") or "").strip()
        if not (real_name and email and password and handle):
            return jsonify({"error": "All fields are required."}), 400
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return jsonify({"error": "Invalid email."}), 400
        if len(password) < 4:
            return jsonify({"error": "Password too short (min 4)."}), 400
        if not re.match(r"^[A-Za-z0-9_]{3,20}$", handle):
            return jsonify({"error": "Handle: 3-20 chars, letters/numbers/_."}), 400
        conn = get_db(app.config["DB_PATH"])
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            conn.close()
            return jsonify({"error": "Email already registered."}), 400
        if conn.execute("SELECT 1 FROM users WHERE handle=?", (handle,)).fetchone():
            conn.close()
            return jsonify({"error": "Handle taken."}), 400
        conn.execute(
            "INSERT INTO users (real_name, email, handle, password_hash) VALUES (?,?,?,?)",
            (real_name, email, handle, generate_password_hash(password)),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "handle": handle}), 201

    @app.post("/api/login")
    def login():
        p = request.get_json(silent=True) or {}
        identifier = (p.get("identifier") or "").strip().lower()
        password = p.get("password") or ""
        conn = get_db(app.config["DB_PATH"])
        row = conn.execute(
            "SELECT * FROM users WHERE email=? OR handle=?",
            (identifier, identifier),
        ).fetchone()
        conn.close()
        if not row or not check_password_hash(row["password_hash"], password):
            return jsonify({"error": "Invalid credentials."}), 401
        if row["banned"]:
            return jsonify({"error": "This account has been removed."}), 403
        session["user_id"] = row["id"]
        return jsonify({"ok": True, "handle": row["handle"]})

    @app.post("/api/rumors")
    def post_rumor():
        if not session.get("user_id"):
            return jsonify({"error": "Login required."}), 401
        p = request.get_json(silent=True) or {}
        text = (p.get("text") or "").strip()
        if not text:
            return jsonify({"error": "Rumor text is required."}), 400
        created_at = datetime.now(timezone.utc).isoformat()
        conn = get_db(app.config["DB_PATH"])
        cur = conn.execute(
            "INSERT INTO rumors (user_id, text, created_at) VALUES (?,?,?)",
            (session["user_id"], text, created_at),
        )
        conn.commit()
        rid = cur.lastrowid
        row = conn.execute(
            "SELECT r.id, r.text, r.created_at, u.handle FROM rumors r "
            "JOIN users u ON u.id = r.user_id WHERE r.id = ?", (rid,)
        ).fetchone()
        conn.close()
        return jsonify(rumor_public(row)), 201

    @app.get("/api/rumors")
    def list_rumors():
        conn = get_db(app.config["DB_PATH"])
        rows = conn.execute(
            "SELECT r.id, r.text, r.created_at, u.handle FROM rumors r "
            "JOIN users u ON u.id = r.user_id "
            "WHERE u.banned = 0 ORDER BY r.id DESC"
        ).fetchall()
        conn.close()
        return jsonify({"rumors": [rumor_public(r) for r in rows]})

    @app.post("/api/admin/login")
    def admin_login():
        p = request.get_json(silent=True) or {}
        if p.get("password") != app.config["ADMIN_PASSWORD"]:
            return jsonify({"error": "Unauthorized."}), 401
        session["admin"] = True
        return jsonify({"ok": True})

    @app.get("/api/admin/rumors")
    def admin_rumors():
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db(app.config["DB_PATH"])
        rows = conn.execute(
            "SELECT r.id, r.text, r.created_at, u.handle, u.real_name, u.email "
            "FROM rumors r JOIN users u ON u.id = r.user_id ORDER BY r.id DESC"
        ).fetchall()
        conn.close()
        return jsonify({"rumors": [rumor_admin(r) for r in rows]})

    @app.delete("/api/admin/rumors/<int:rid>")
    def admin_delete_rumor(rid):
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db(app.config["DB_PATH"])
        conn.execute("DELETE FROM rumors WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "deleted": rid})

    @app.get("/api/admin/users")
    def admin_users():
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db(app.config["DB_PATH"])
        rows = conn.execute(
            "SELECT id, real_name, email, handle, banned FROM users ORDER BY id"
        ).fetchall()
        conn.close()
        return jsonify({"users": [dict(r) for r in rows]})

    @app.delete("/api/admin/users/<int:uid>")
    def admin_ban_user(uid):
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db(app.config["DB_PATH"])
        conn.execute("UPDATE users SET banned = 1 WHERE id=?", (uid,))
        conn.execute("DELETE FROM rumors WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "banned": uid})

    @app.get("/")
    def index():
        return serve_page("index.html")

    @app.get("/admin")
    def admin_page():
        return serve_page("admin.html")

    @app.after_request
    def security_headers(resp):
        # Helmet equivalent for Flask (spec: security headers)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'"
        )
        return resp

    return app


def rumor_public(row):
    return {"id": row["id"], "text": row["text"],
            "created_at": row["created_at"], "handle": row["handle"]}


def rumor_admin(row):
    return {"id": row["id"], "text": row["text"],
            "created_at": row["created_at"], "handle": row["handle"],
            "real_name": row["real_name"], "email": row["email"]}


def serve_page(name):
    path = os.path.join(os.path.dirname(__file__), "static", name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_db(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL lets readers and writers coexist without "database is locked"
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path):
    conn = get_db(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            real_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            handle TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            banned INTEGER NOT NULL DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rumors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )"""
    )
    conn.commit()
    conn.close()


def hash_password(pw):
    return generate_password_hash(pw)
