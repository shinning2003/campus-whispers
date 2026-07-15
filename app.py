"""Campus Whispers — anonymous rumor board for a class.

Posters stay anonymous. Data is stored server-side in SQLite,
accessible only by the admin (owner) via a login.
"""
import os
import sqlite3
from datetime import datetime, timezone

from flask import Flask, jsonify, request, session


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DB_PATH=os.environ.get("DB_PATH", "campus_whispers.db"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "admin123"),
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
    )
    if config:
        app.config.update(config)

    @app.post("/api/rumors")
    def post_rumor():
        payload = request.get_json(silent=True) or {}
        text = (payload.get("text") or "").strip()
        if not text:
            return jsonify({"error": "Rumor text is required."}), 400
        created_at = datetime.now(timezone.utc).isoformat()
        conn = get_db(app.config["DB_PATH"])
        cur = conn.execute(
            "INSERT INTO rumors (text, created_at) VALUES (?, ?)", (text, created_at)
        )
        conn.commit()
        rumor_id = cur.lastrowid
        row = conn.execute("SELECT * FROM rumors WHERE id = ?", (rumor_id,)).fetchone()
        conn.close()
        return jsonify(row_to_dict(row)), 201

    @app.get("/api/rumors")
    def list_rumors():
        conn = get_db(app.config["DB_PATH"])
        rows = conn.execute(
            "SELECT id, text, created_at FROM rumors ORDER BY id DESC"
        ).fetchall()
        conn.close()
        return jsonify({"rumors": [row_to_dict(r) for r in rows]})

    @app.post("/api/admin/login")
    def admin_login():
        payload = request.get_json(silent=True) or {}
        if payload.get("password") != app.config["ADMIN_PASSWORD"]:
            return jsonify({"error": "Unauthorized."}), 401
        session["admin"] = True
        return jsonify({"ok": True})

    @app.get("/api/admin/rumors")
    def admin_list():
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db(app.config["DB_PATH"])
        rows = conn.execute(
            "SELECT id, text, created_at FROM rumors ORDER BY id DESC"
        ).fetchall()
        conn.close()
        return jsonify({"rumors": [row_to_dict(r) for r in rows]})

    @app.delete("/api/admin/rumors/<int:rid>")
    def admin_delete(rid):
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db(app.config["DB_PATH"])
        conn.execute("DELETE FROM rumors WHERE id = ?", (rid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "deleted": rid})

    @app.get("/")
    def index():
        return serve_page("index.html")

    @app.get("/admin")
    def admin_page():
        return serve_page("admin.html")

    return app


def serve_page(name):
    path = os.path.join(os.path.dirname(__file__), "static", name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row):
    return {
        "id": row["id"],
        "text": row["text"],
        "created_at": row["created_at"],
    }


def init_db(db_path):
    conn = get_db(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rumors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
