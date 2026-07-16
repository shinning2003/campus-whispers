"""Campus Whispers — accountability board for a class.

Posters register a REAL NAME + EMAIL + PASSWORD, choose a public HANDLE.
The handle is shown publicly; only the admin (owner) can see the real
identity behind a handle, and can ban/delete anyone who misbehaves.
"""
import os
import re
import sqlite3
from datetime import datetime, timezone

from flask import Flask, jsonify, request, session, current_app
from werkzeug.security import generate_password_hash, check_password_hash


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DB_PATH=os.environ.get("DB_PATH", "campus_whispers.db"),
        DATABASE_URL=os.environ.get("DATABASE_URL"),
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
        conn = get_db()
        if exec(conn, "SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            conn.close()
            return jsonify({"error": "Email already registered."}), 400
        if exec(conn, "SELECT 1 FROM users WHERE handle=?", (handle,)).fetchone():
            conn.close()
            return jsonify({"error": "Handle taken."}), 400
        exec(conn, 
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
        conn = get_db()
        row = exec(conn, 
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
        conn = get_db()
        import psycopg
        is_pg = isinstance(conn, psycopg.Connection)
        if is_pg:
            cur = exec(conn,
                "INSERT INTO rumors (user_id, text, created_at) VALUES (?,?,?) "
                "RETURNING id",
                (session["user_id"], text, created_at),
            )
            conn.commit()
            rid = cur.fetchone()["id"]
        else:
            cur = exec(conn,
                "INSERT INTO rumors (user_id, text, created_at) VALUES (?,?,?)",
                (session["user_id"], text, created_at),
            )
            conn.commit()
            rid = cur.lastrowid
        row = exec(conn,
            "SELECT r.id, r.text, r.created_at, u.handle FROM rumors r "
            "JOIN users u ON u.id = r.user_id WHERE r.id = ?", (rid,)
        ).fetchone()
        conn.close()
        return jsonify(rumor_public(row)), 201

    @app.get("/api/rumors")
    def list_rumors():
        conn = get_db()
        rows = exec(conn, 
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
        conn = get_db()
        rows = exec(conn, 
            "SELECT r.id, r.text, r.created_at, u.handle, u.real_name, u.email "
            "FROM rumors r JOIN users u ON u.id = r.user_id ORDER BY r.id DESC"
        ).fetchall()
        conn.close()
        return jsonify({"rumors": [rumor_admin(r) for r in rows]})

    @app.delete("/api/admin/rumors/<int:rid>")
    def admin_delete_rumor(rid):
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db()
        exec(conn, "DELETE FROM rumors WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "deleted": rid})

    @app.get("/api/admin/users")
    def admin_users():
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db()
        rows = exec(conn, 
            "SELECT id, real_name, email, handle, banned FROM users ORDER BY id"
        ).fetchall()
        conn.close()
        return jsonify({"users": [dict(r) for r in rows]})

    @app.delete("/api/admin/users/<int:uid>")
    def admin_ban_user(uid):
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db()
        exec(conn, "UPDATE users SET banned = 1 WHERE id=?", (uid,))
        exec(conn, "DELETE FROM rumors WHERE user_id=?", (uid,))
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

    # Ensure schema exists on startup. Render runs `gunicorn "app:create_app()"`
    # (create_app is called directly, not run.py), so we must init the DB here
    # — otherwise tables are never created and every API call 500s.
    # Tolerate a temporarily-unavailable DB at import time: log and continue
    # rather than crashing the whole app; per-request calls will surface errors.
    try:
        with app.app_context():
            init_db()
            if app.config.get("DATABASE_URL"):
                app.logger.info("Campus Whispers: using Postgres (DATABASE_URL set)")
            else:
                app.logger.warning(
                    "Campus Whispers: DATABASE_URL not set — using SQLite. "
                    "On Render this is EPHEMERAL and data will be lost on restart."
                )
    except Exception as exc:  # pragma: no cover - defensive startup guard
        app.logger.error("Campus Whispers: DB init failed at startup: %s", exc)

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


def get_db(db_path=None):
    """Return a connection to whichever DB is configured.

    If DATABASE_URL (Supabase Postgres) is set, use psycopg; otherwise
    fall back to the local SQLite file. Both expose a sqlite3.Row-like
    dict interface via the adapters below.
    """
    url = db_path or current_app.config.get("DATABASE_URL")
    if url:
        try:
            import psycopg
            from psycopg.rows import dict_row
            conn = psycopg.connect(url, row_factory=dict_row)
            return conn
        except ImportError:
            pass  # psycopg not installed -> fall through to sqlite
    # SQLite (local dev)
    conn = sqlite3.connect(
        current_app.config["DB_PATH"], timeout=30
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def exec(conn, sql, params=()):
    """Run a query, transparently adapting `?` placeholders to `%s` for Postgres."""
    import psycopg
    if isinstance(conn, psycopg.Connection):
        sql = sql.replace("?", "%s")
    return conn.execute(sql, params)


def init_db(db_path=None):
    conn = get_db(db_path)
    if isinstance(conn, sqlite3.Connection):
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
    else:  # Postgres (Supabase)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                real_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                handle TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                banned INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS rumors (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
    conn.commit()
    conn.close()


def hash_password(pw):
    return generate_password_hash(pw)
