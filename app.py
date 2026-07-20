"""Campus Whispers — accountability board for a class.

Posters register a REAL NAME + EMAIL + PASSWORD, choose a public HANDLE.
The handle is shown publicly; only the admin (owner) can see the real
identity behind a handle, and can ban/delete anyone who misbehaves.
"""
import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta

from flask import Flask, jsonify, request, session, current_app
from werkzeug.security import generate_password_hash, check_password_hash


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DB_PATH=os.environ.get("DB_PATH", "campus_whispers.db"),
        DATABASE_URL=os.environ.get("DATABASE_URL"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "admin123"),
        ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL", "11surendiran2003@gmail.com"),
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
    )
    if config:
        app.config.update(config)

    @app.post("/api/register")
    def register():
        p = request.get_json(silent=True) or {}
        real_name = (p.get("real_name") or "").strip()
        # Email login removed: users authenticate by handle + password only.
        handle = (p.get("handle") or "").strip()
        password = p.get("password") or ""
        if not (real_name and handle and password):
            return jsonify({"error": "real_name, handle and password required."}), 400
        if len(password) < 4:
            return jsonify({"error": "Password too short (min 4)."}), 400
        if not re.match(r"^[A-Za-z0-9_]{3,20}$", handle):
            return jsonify({"error": "Handle: 3-20 chars, letters/numbers/_."}), 400
        conn = get_db()
        if exec(conn, "SELECT 1 FROM users WHERE handle=?", (handle,)).fetchone():
            conn.close()
            return jsonify({"error": "Handle taken."}), 400
        exec(conn,
            "INSERT INTO users (real_name, handle, password_hash) VALUES (?,?,?)",
            (real_name, handle, generate_password_hash(password)),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "handle": handle}), 201

    @app.post("/api/login")
    def login():
        p = request.get_json(silent=True) or {}
        # Email login removed: authenticate by handle (username) + password.
        handle = (p.get("handle") or p.get("identifier") or "").strip()
        password = p.get("password") or ""
        conn = get_db()
        row = exec(conn,
            "SELECT * FROM users WHERE handle=?",
            (handle,),
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
        raw_tags = p.get("tags") or []
        # sanitize: list of 1-20 char slug-ish names, max 5 tags
        tags = []
        for t in raw_tags:
            name = str(t).strip().lower()[:20]
            if name and name not in tags:
                tags.append(name)
        tags = tags[:5]
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
        for name in tags:
            tid = _upsert_tag(conn, name)
            exists = exec(conn,
                "SELECT 1 FROM rumor_tags WHERE rumor_id=? AND tag_id=?",
                (rid, tid)).fetchone()
            if not exists:
                exec(conn,
                    "INSERT INTO rumor_tags (rumor_id, tag_id) VALUES (?,?)",
                    (rid, tid))
        conn.commit()
        row = exec(conn,
            "SELECT r.id, r.text, r.created_at, u.handle FROM rumors r "
            "JOIN users u ON u.id = r.user_id WHERE r.id = ?", (rid,)
        ).fetchone()
        out = rumor_public(row, conn)
        conn.close()
        return jsonify(out), 201

    @app.get("/api/rumors")
    def list_rumors():
        sort = (request.args.get("sort") or "new").strip().lower()
        tag = (request.args.get("tag") or "").strip().lower()
        filt = (request.args.get("filter") or "").strip().lower()
        conn = get_db()
        base = ("SELECT r.id, r.text, r.created_at, u.handle "
                "FROM rumors r JOIN users u ON u.id = r.user_id "
                "WHERE u.banned = 0")
        params = ()
        if tag:
            base = ("SELECT r.id, r.text, r.created_at, u.handle "
                    "FROM rumors r JOIN users u ON u.id = r.user_id "
                    "JOIN rumor_tags rt ON rt.rumor_id = r.id "
                    "JOIN tags t ON t.id = rt.tag_id "
                    "WHERE u.banned = 0 AND t.name = ?")
            params = (tag,)
        elif filt == "followed" and session.get("user_id"):
            base = ("SELECT r.id, r.text, r.created_at, u.handle "
                    "FROM rumors r JOIN users u ON u.id = r.user_id "
                    "JOIN rumor_tags rt ON rt.rumor_id = r.id "
                    "WHERE u.banned = 0 AND rt.tag_id IN ("
                    "SELECT tag_id FROM tag_follows WHERE user_id = ?)")
            params = (session["user_id"],)
        order_clause = "ORDER BY r.id DESC"
        if sort == "hot":
            order_clause = ("ORDER BY (SELECT COUNT(*) FROM reactions "
                            "WHERE rumor_id=r.id) "
                            "+ (SELECT COUNT(*) FROM me_too WHERE rumor_id=r.id)*2 "
                            "+ (SELECT COUNT(*) FROM comments c JOIN users cu "
                            "ON cu.id=c.user_id WHERE c.rumor_id=r.id "
                            "AND cu.banned=0)*3 DESC, r.id DESC")
        rows = exec(conn, base + " " + order_clause, params).fetchall()
        out = [rumor_public(r, conn) for r in rows]
        conn.close()
        return jsonify({"rumors": out})

    @app.get("/api/rumors/<int:rid>/teaser")
    def rumor_teaser(rid):
        # Information-gap trigger: hide the text, show a curiosity teaser.
        conn = get_db()
        row = exec(conn,
            "SELECT r.id, r.text, r.created_at, u.handle FROM rumors r "
            "JOIN users u ON u.id = r.user_id "
            "WHERE r.id=? AND u.banned=0", (rid,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Rumor not found."}), 404
        teaser = _make_teaser(row["text"])
        data = {
            "id": row["id"],
            "handle": row["handle"],
            "teaser": teaser,
            "created_at": row["created_at"],
            "reactions": _reaction_counts(conn, row["id"]),
            "me_too_count": _me_too_count(conn, row["id"]),
            "comment_count": _comment_count(conn, row["id"]),
        }
        conn.close()
        return jsonify(data)

    # --- Feature 1: Reactions + "Me too" ---
    # Tribe reward (social validation) + "I am not alone" identification.
    VALID_REACTIONS = {"laugh", "fire", "hundred", "shock"}

    @app.post("/api/rumors/<int:rid>/react")
    def react(rid):
        if not session.get("user_id"):
            return jsonify({"error": "Login required."}), 401
        p = request.get_json(silent=True) or {}
        kind = (p.get("kind") or "").strip()
        if kind not in VALID_REACTIONS:
            return jsonify({"error": "Invalid reaction kind."}), 400
        conn = get_db()
        if not exec(conn, "SELECT 1 FROM rumors WHERE id=?", (rid,)).fetchone():
            conn.close()
            return jsonify({"error": "Rumor not found."}), 404
        existing = exec(conn,
            "SELECT 1 FROM reactions WHERE user_id=? AND rumor_id=? AND kind=?",
            (session["user_id"], rid, kind),
        ).fetchone()
        if existing:
            exec(conn,
                "DELETE FROM reactions WHERE user_id=? AND rumor_id=? AND kind=?",
                (session["user_id"], rid, kind),
            )
            reacted = False
        else:
            exec(conn,
                "INSERT INTO reactions (user_id, rumor_id, kind) VALUES (?,?,?)",
                (session["user_id"], rid, kind),
            )
            reacted = True
        conn.commit()
        counts = _reaction_counts(conn, rid)
        conn.close()
        return jsonify({"ok": True, "reacted": reacted, "kind": kind,
                        "count": counts.get(kind, 0), "reactions": counts})

    @app.post("/api/rumors/<int:rid>/metoo")
    def metoo(rid):
        if not session.get("user_id"):
            return jsonify({"error": "Login required."}), 401
        conn = get_db()
        if not exec(conn, "SELECT 1 FROM rumors WHERE id=?", (rid,)).fetchone():
            conn.close()
            return jsonify({"error": "Rumor not found."}), 404
        existing = exec(conn,
            "SELECT 1 FROM me_too WHERE user_id=? AND rumor_id=?",
            (session["user_id"], rid),
        ).fetchone()
        if existing:
            exec(conn,
                "DELETE FROM me_too WHERE user_id=? AND rumor_id=?",
                (session["user_id"], rid),
            )
            active = False
        else:
            exec(conn,
                "INSERT INTO me_too (user_id, rumor_id) VALUES (?,?)",
                (session["user_id"], rid),
            )
            active = True
        conn.commit()
        count = _me_too_count(conn, rid)
        conn.close()
        return jsonify({"ok": True, "active": active, "count": count})


    # --- Feature 2: Anonymous comments ---
    # Investment (contributing) + Tribe (peer interaction). Handle shown,
    # real identity hidden; commenter can delete their own.
    @app.post("/api/rumors/<int:rid>/comments")
    def post_comment(rid):
        if not session.get("user_id"):
            return jsonify({"error": "Login required."}), 401
        p = request.get_json(silent=True) or {}
        text = (p.get("text") or "").strip()
        if not text:
            return jsonify({"error": "Comment text is required."}), 400
        conn = get_db()
        if not exec(conn, "SELECT 1 FROM rumors WHERE id=? AND "
                          "user_id IN (SELECT id FROM users WHERE banned=0)",
                          (rid,)).fetchone():
            conn.close()
            return jsonify({"error": "Rumor not found."}), 404
        created_at = datetime.now(timezone.utc).isoformat()
        is_pg = _conn_is_pg(conn)
        if is_pg:
            cur = exec(conn,
                "INSERT INTO comments (user_id, rumor_id, text, created_at) "
                "VALUES (?,?,?,?) RETURNING id",
                (session["user_id"], rid, text, created_at))
            conn.commit()
            cid = cur.fetchone()["id"]
        else:
            cur = exec(conn,
                "INSERT INTO comments (user_id, rumor_id, text, created_at) "
                "VALUES (?,?,?,?)",
                (session["user_id"], rid, text, created_at))
            conn.commit()
            cid = cur.lastrowid
        row = exec(conn,
            "SELECT c.id, c.text, c.created_at, u.handle FROM comments c "
            "JOIN users u ON u.id = c.user_id WHERE c.id = ?", (cid,)).fetchone()
        conn.close()
        return jsonify(comment_public(row)), 201

    @app.get("/api/rumors/<int:rid>/comments")
    def list_comments(rid):
        conn = get_db()
        rows = exec(conn,
            "SELECT c.id, c.text, c.created_at, u.handle FROM comments c "
            "JOIN users u ON u.id = c.user_id "
            "WHERE c.rumor_id = ? AND u.banned = 0 ORDER BY c.id ASC",
            (rid,)).fetchall()
        conn.close()
        return jsonify({"comments": [comment_public(r) for r in rows]})

    @app.delete("/api/comments/<int:cid>")
    def delete_comment(cid):
        if not session.get("user_id"):
            return jsonify({"error": "Login required."}), 401
        conn = get_db()
        row = exec(conn, "SELECT user_id FROM comments WHERE id=?",
                   (cid,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Comment not found."}), 404
        if row["user_id"] != session["user_id"]:
            conn.close()
            return jsonify({"error": "Not your comment."}), 403
        exec(conn, "DELETE FROM comments WHERE id=?", (cid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "deleted": cid})


    # --- Feature 3: Posting streak (Self reward + loss aversion) ---
    @app.get("/api/me")
    def me():
        if not session.get("user_id"):
            return jsonify({"error": "Login required."}), 401
        conn = get_db()
        uid = session["user_id"]
        row = exec(conn, "SELECT handle FROM users WHERE id=?",
                   (uid,)).fetchone()
        streak, at_risk = _compute_streak(conn, uid)
        points = _compute_points(conn, uid)
        badges = _compute_badges(conn, uid)
        rank = _user_rank(conn, uid)
        conn.close()
        return jsonify({"handle": row["handle"], "streak": streak,
                        "streak_at_risk_today": at_risk,
                        "points": points, "badges": badges, "rank": rank})

    # --- Reward system: challenges, leaderboard (anonymized) ---
    @app.get("/api/challenges")
    def list_challenges():
        if not session.get("user_id"):
            return jsonify({"error": "Login required."}), 401
        conn = get_db()
        uid = session["user_id"]
        week = _current_week()
        claimed = set()
        for r in exec(conn,
                "SELECT challenge_key FROM challenge_claims WHERE user_id=? AND week=?",
                (uid, week)).fetchall():
            claimed.add(r[0] if not hasattr(r, "keys") else r["challenge_key"])
        out = []
        for key, label, goal, reward, kind in CHALLENGE_DEFS:
            progress = _challenge_progress(conn, uid, kind)
            out.append({
                "key": key, "label": label, "goal": goal, "reward": reward,
                "progress": min(progress, goal),
                "completed": progress >= goal,
                "claimed": key in claimed,
            })
        conn.close()
        return jsonify({"week": week, "challenges": out})

    @app.post("/api/challenges/<key>/claim")
    def claim_challenge(key):
        if not session.get("user_id"):
            return jsonify({"error": "Login required."}), 401
        cdef = next((c for c in CHALLENGE_DEFS if c[0] == key), None)
        if not cdef:
            return jsonify({"error": "Unknown challenge."}), 404
        _k, _label, goal, _reward, kind = cdef
        conn = get_db()
        uid = session["user_id"]
        week = _current_week()
        if _challenge_progress(conn, uid, kind) < goal:
            conn.close()
            return jsonify({"error": "Challenge not complete yet."}), 400
        already = exec(conn,
            "SELECT 1 FROM challenge_claims WHERE user_id=? AND challenge_key=? AND week=?",
            (uid, key, week)).fetchone()
        if already:
            conn.close()
            return jsonify({"error": "Already claimed this week."}), 400
        exec(conn,
            "INSERT INTO challenge_claims (user_id, challenge_key, week, claimed_at) "
            "VALUES (?,?,?,?)",
            (uid, key, week, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        points = _compute_points(conn, uid)
        conn.close()
        return jsonify({"ok": True, "claimed": key, "points": points})

    @app.get("/api/leaderboard")
    def leaderboard():
        conn = get_db()
        ids = [r[0] if not hasattr(r, "keys") else r["id"]
               for r in exec(conn, "SELECT id FROM users WHERE banned=0", ()).fetchall()]
        scored = sorted(((uid, _compute_points(conn, uid)) for uid in ids),
                        key=lambda t: t[1], reverse=True)
        conn.close()
        # Anonymized: alias only (Player #N), never the handle/email/real_name.
        out = []
        for i, (uid, pts) in enumerate(scored[:10], start=1):
            out.append({"rank": i, "alias": f"Player #{i}", "points": pts})
        return jsonify({"leaderboard": out})


    # --- Feature 5: Tags + follow-a-tag (Investment / internal trigger) ---
    @app.get("/api/tags")
    def list_tags():
        conn = get_db()
        rows = exec(conn,
            "SELECT t.name, COUNT(rt.rumor_id) AS count FROM tags t "
            "LEFT JOIN rumor_tags rt ON rt.tag_id = t.id "
            "GROUP BY t.id ORDER BY count DESC, t.name"
        ).fetchall()
        conn.close()
        return jsonify({"tags": [dict(r) for r in rows]})

    @app.post("/api/tags/<name>/follow")
    def follow_tag(name):
        if not session.get("user_id"):
            return jsonify({"error": "Login required."}), 401
        name = name.strip().lower()[:20]
        if not name:
            return jsonify({"error": "Tag name required."}), 400
        conn = get_db()
        tid = _upsert_tag(conn, name)
        exists = exec(conn,
            "SELECT 1 FROM tag_follows WHERE user_id=? AND tag_id=?",
            (session["user_id"], tid)).fetchone()
        if not exists:
            exec(conn,
                "INSERT INTO tag_follows (user_id, tag_id) VALUES (?,?)",
                (session["user_id"], tid))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "following": name})

    @app.delete("/api/tags/<name>/follow")
    def unfollow_tag(name):
        if not session.get("user_id"):
            return jsonify({"error": "Login required."}), 401
        name = name.strip().lower()[:20]
        conn = get_db()
        row = exec(conn, "SELECT id FROM tags WHERE name=?",
                   (name,)).fetchone()
        if row:
            exec(conn,
                "DELETE FROM tag_follows WHERE user_id=? AND tag_id=?",
                (session["user_id"], row["id"]))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "unfollowed": name})

    @app.get("/api/me/tags")
    def my_tags():
        if not session.get("user_id"):
            return jsonify({"error": "Login required."}), 401
        conn = get_db()
        rows = exec(conn,
            "SELECT t.name FROM tag_follows tf JOIN tags t ON t.id=tf.tag_id "
            "WHERE tf.user_id=?", (session["user_id"],)).fetchall()
        conn.close()
        return jsonify({"followed_tags": [r["name"] for r in rows]})


    @app.post("/api/admin/login")
    def admin_login():
        # Admin access is password-only (the owner's secret). No email gate.
        p = request.get_json(silent=True) or {}
        if p.get("password") != app.config["ADMIN_PASSWORD"]:
            return jsonify({"error": "Unauthorized."}), 401
        session["admin"] = True
        return jsonify({"ok": True})

    @app.post("/api/forgot-password")
    def forgot_password():
        # Privacy-safe: never confirms whether a handle exists. The admin is
        # notified (log) so they can reset it manually via the admin panel.
        p = request.get_json(silent=True) or {}
        handle = (p.get("handle") or "").strip()
        if not handle:
            return jsonify({"error": "Handle required."}), 400
        conn = get_db()
        row = exec(conn, "SELECT id, handle FROM users WHERE handle=?",
                   (handle,)).fetchone()
        conn.close()
        if row:
            app.logger.info(
                "Campus Whispers: password-reset requested for user %s",
                row["handle"])
        # Always return the same neutral message (no account enumeration).
        return jsonify({
            "ok": True,
            "message": "If that handle is registered, the admin has been "
                       "notified and will reset your password."
        }), 200

    @app.post("/api/admin/users/<int:uid>/reset-password")
    def admin_reset_password(uid):
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        p = request.get_json(silent=True) or {}
        new_pw = p.get("new_password") or ""
        if len(new_pw) < 4:
            return jsonify({"error": "Password too short (min 4)."}), 400
        conn = get_db()
        row = exec(conn, "SELECT id FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "User not found."}), 404
        exec(conn, "UPDATE users SET password_hash=? WHERE id=?",
             (generate_password_hash(new_pw), uid))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "reset": uid})


    @app.post("/api/admin/digest/send")
    def admin_digest_send():
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        p = request.get_json(silent=True) or {}
        window_hours = int(p.get("window_hours") or 24)
        conn = get_db()
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(hours=window_hours)).isoformat()
        rows = exec(conn,
            "SELECT r.id, r.text, r.created_at, u.handle "
            "FROM rumors r JOIN users u ON u.id = r.user_id "
            "WHERE u.banned = 0 AND r.created_at >= ? "
            "ORDER BY (SELECT COUNT(*) FROM reactions WHERE rumor_id=r.id) "
            "+ (SELECT COUNT(*) FROM me_too WHERE rumor_id=r.id)*2 "
            "+ (SELECT COUNT(*) FROM comments c JOIN users cu "
            "ON cu.id=c.user_id WHERE c.rumor_id=r.id AND cu.banned=0)*3 DESC, "
            "r.id DESC",
            (cutoff,)).fetchall()
        users = exec(conn,
            "SELECT handle FROM users WHERE banned=0").fetchall()
        conn.close()
        if not rows:
            return jsonify({"ok": True, "sent": 0, "note": "no recent rumors"})
        body = _render_digest(rows)
        # Email delivery disabled: account emails were removed from the schema.
        # `users` is retained so a future in-app notification path can use it.
        sent = 0
        return jsonify({"ok": True, "sent": sent, "rumors": len(rows)})


    @app.get("/api/admin/rumors")
    def admin_rumors():
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db()
        rows = exec(conn, 
            "SELECT r.id, r.text, r.created_at, u.handle, u.real_name "
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

    @app.post("/api/admin/rumors/<int:rid>/feature")
    def admin_feature_rumor(rid):
        # Variable-reward surprise: admin (or a future random job) marks a
        # whisper 'featured' — an unpredictable bonus that drives re-checking.
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db()
        if not exec(conn, "SELECT 1 FROM rumors WHERE id=?", (rid,)).fetchone():
            conn.close()
            return jsonify({"error": "Rumor not found."}), 404
        exec(conn, "UPDATE rumors SET featured=1 WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "featured": rid})

    @app.get("/api/admin/users")
    def admin_users():
        if not session.get("admin"):
            return jsonify({"error": "Unauthorized."}), 401
        conn = get_db()
        rows = exec(conn, 
            "SELECT id, real_name, handle, banned FROM users ORDER BY id"
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


def _render_digest(rows):
    """Plain-text digest of top rumors (external trigger email body)."""
    lines = ["Campus Whispers — today's top whispers", "=" * 36, ""]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. @{r['handle']}: {r['text']}")
    lines.append("")
    lines.append("What's the latest secret? Open Campus Whispers.")
    return "\n".join(lines)


def _send_digest_smtp(app, to_addrs, body):
    """Real SMTP send via smtplib. Config via env: DIGEST_SMTP_HOST,
    DIGEST_SMTP_PORT, DIGEST_SMTP_USER, DIGEST_SMTP_PASS, DIGEST_FROM.
    Returns count sent; returns 0 (and logs) if not configured."""
    import smtplib
    from email.message import EmailMessage
    host = app.config.get("DIGEST_SMTP_HOST") or os.environ.get("DIGEST_SMTP_HOST")
    if not host:
        app.logger.warning("Campus Whispers: digest SMTP not configured; "
                           "no emails sent.")
        return 0
    port = int(app.config.get("DIGEST_SMTP_PORT")
               or os.environ.get("DIGEST_SMTP_PORT") or 587)
    user = app.config.get("DIGEST_SMTP_USER") or os.environ.get("DIGEST_SMTP_USER")
    pwd = app.config.get("DIGEST_SMTP_PASS") or os.environ.get("DIGEST_SMTP_PASS")
    frm = app.config.get("DIGEST_FROM") or os.environ.get("DIGEST_FROM") \
        or (user or "noreply@campus-whispers.app")
    sent = 0
    try:
        with smtplib.SMTP(host, port) as s:
            if user:
                s.starttls()
                s.login(user, pwd)
            for to in to_addrs:
                msg = EmailMessage()
                msg["Subject"] = "Campus Whispers — today's top whispers"
                msg["From"] = frm
                msg["To"] = to
                msg.set_content(body)
                s.send_message(msg)
                sent += 1
    except Exception as exc:  # pragma: no cover - network path
        app.logger.error("Campus Whispers: digest SMTP failed: %s", exc)
    return sent


def rumor_public(row, conn=None):
    data = {"id": row["id"], "text": row["text"],
            "created_at": row["created_at"], "handle": row["handle"]}
    if conn is not None:
        data["reactions"] = _reaction_counts(conn, row["id"])
        data["me_too_count"] = _me_too_count(conn, row["id"])
        data["comment_count"] = _comment_count(conn, row["id"])
        data["tags"] = _rumor_tags(conn, row["id"])
        # Variable-reward surprise: is this post featured?
        frow = exec(conn, "SELECT featured FROM rumors WHERE id=?",
                    (row["id"],)).fetchone()
        data["featured"] = int(frow["featured"]) if frow and frow["featured"] is not None else 0
    # Rising-star gentle floor: flag posts < 24h old so the UI can soften
    # 0-reaction "failure" (research: youth are sensitive to absent feedback).
    data["is_new"] = _is_new(row["created_at"])
    return data


def _is_new(created_at):
    """True if the post is less than 24h old."""
    from datetime import datetime, timezone, timedelta
    try:
        ts = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts) < timedelta(hours=24)
    except Exception:
        return False


def _rumor_tags(conn, rumor_id):
    rows = exec(conn,
        "SELECT t.name FROM rumor_tags rt JOIN tags t ON t.id = rt.tag_id "
        "WHERE rt.rumor_id=?", (rumor_id,)).fetchall()
    return [r["name"] for r in rows]


def _upsert_tag(conn, name):
    """Insert a tag if absent; return its id (cross-DB safe)."""
    if _conn_is_pg(conn):
        cur = exec(conn,
            "INSERT INTO tags (name) VALUES (?) "
            "ON CONFLICT (name) DO NOTHING RETURNING id", (name,))
        row = cur.fetchone()
        if row:
            return row["id"]
        return exec(conn, "SELECT id FROM tags WHERE name=?",
                    (name,)).fetchone()["id"]
    exec(conn, "INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
    return exec(conn, "SELECT id FROM tags WHERE name=?",
               (name,)).fetchone()["id"]


def _reaction_counts(conn, rumor_id):
    kinds = ["laugh", "fire", "hundred", "shock"]
    rows = exec(conn,
        "SELECT kind, COUNT(*) AS c FROM reactions WHERE rumor_id=? GROUP BY kind",
        (rumor_id,),
    ).fetchall()
    counts = {k: 0 for k in kinds}
    for r in rows:
        counts[r["kind"]] = r["c"]
    return counts


def _me_too_count(conn, rumor_id):
    row = exec(conn, "SELECT COUNT(*) AS c FROM me_too WHERE rumor_id=?",
               (rumor_id,)).fetchone()
    return row["c"]


def _make_teaser(text):
    """Information-gap teaser: open a curiosity gap without revealing text.

    Shows a short masked fragment + ellipsis so readers feel a knowledge
    gap (Loewenstein) that pulls them to open the full rumor.
    """
    words = text.split()
    if len(words) <= 4:
        return "🤫 " + "•" * len(text) + "…"
    frag = " ".join(words[:4])
    return f"🤫 {frag}…"


def _comment_count(conn, rumor_id):
    row = exec(conn, "SELECT COUNT(*) AS c FROM comments WHERE rumor_id=?",
               (rumor_id,)).fetchone()
    return row["c"]


def _conn_is_pg(conn):
    import psycopg
    return isinstance(conn, psycopg.Connection)


def _compute_streak(conn, user_id):
    """Return (streak, at_risk_today).

    Streak = consecutive distinct UTC calendar days with >=1 post, ending
    today or yesterday (1-day grace window so a single missed day doesn't
    shatter the streak — recovery prevents churn per Nikzad 2021).
    at_risk_today is True when the last post was yesterday: today is the
    final grace day to keep the streak alive (loss-aversion trigger).
    """
    from datetime import datetime, timezone, date, timedelta
    rows = exec(conn,
        "SELECT DISTINCT substr(created_at,1,10) AS d FROM rumors "
        "WHERE user_id=? ORDER BY d DESC", (user_id,)).fetchall()
    if not rows:
        return 0, False
    dates = [r["d"] for r in rows]
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    # group into consecutive-day runs from most recent backward
    streak = 1
    for prev, cur in zip(dates, dates[1:]):
        d_prev = date.fromisoformat(prev)
        d_cur = date.fromisoformat(cur)
        if (d_prev - d_cur).days == 1:
            streak += 1
        else:
            break
    most_recent = date.fromisoformat(dates[0])
    at_risk = False
    if most_recent == today:
        at_risk = False
    elif most_recent == yesterday:
        at_risk = True
    else:
        streak = 0
    return streak, at_risk


def comment_public(row):
    return {"id": row["id"], "text": row["text"],
            "created_at": row["created_at"], "handle": row["handle"]}



def rumor_admin(row):
    return {"id": row["id"], "text": row["text"],
            "created_at": row["created_at"], "handle": row["handle"],
            "real_name": row["real_name"]}


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
            import socket
            from urllib.parse import urlparse, urlunparse

            # Force IPv4: Render's free tier cannot route to Supabase's IPv6
            # address, so connecting to db.<ref>.supabase.co yields
            # "Network is unreachable". We pre-resolve to an A record with
            # socket.gethostbyname() (IPv4-only by definition — more reliable
            # here than getaddrinfo(..., AF_INET), which Render's resolver
            # returns empty for) and pin the literal IPv4 address directly
            # into the connection URL so libpq never does an AAAA lookup.
            parsed = urlparse(url)
            host = parsed.hostname
            if host and not _looks_like_ip(host):
                try:
                    ipv4 = socket.gethostbyname(host)
                    if ipv4 and not ipv4.startswith(":"):
                        auth = ""
                        if parsed.username is not None:
                            auth = parsed.username
                            if parsed.password is not None:
                                auth += ":" + parsed.password
                        netloc = (auth + "@") if auth else ""
                        netloc += ipv4
                        if parsed.port:
                            netloc += ":" + str(parsed.port)
                        parsed = parsed._replace(netloc=netloc)
                        url = urlunparse(parsed)
                except Exception:
                    pass  # keep original URL if resolution fails

            conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
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


def _looks_like_ip(host):
    import socket
    try:
        socket.inet_aton(host)
        return True
    except OSError:
        return False


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
                handle TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                banned INTEGER NOT NULL DEFAULT 0
            )"""
        )
        # Self-heal: drop the removed email column from any pre-existing DB.
        try:
            conn.execute("ALTER TABLE users DROP COLUMN email")
        except Exception:
            pass  # column already gone (or SQLite < 3.35)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS rumors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                rumor_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                UNIQUE(user_id, rumor_id, kind),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (rumor_id) REFERENCES rumors(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS me_too (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                rumor_id INTEGER NOT NULL,
                UNIQUE(user_id, rumor_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (rumor_id) REFERENCES rumors(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                rumor_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (rumor_id) REFERENCES rumors(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS rumor_tags (
                rumor_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (rumor_id, tag_id),
                FOREIGN KEY (rumor_id) REFERENCES rumors(id),
                FOREIGN KEY (tag_id) REFERENCES tags(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tag_follows (
                user_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, tag_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (tag_id) REFERENCES tags(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS challenge_claims (
                user_id INTEGER NOT NULL,
                challenge_key TEXT NOT NULL,
                week TEXT NOT NULL,
                claimed_at TEXT NOT NULL,
                PRIMARY KEY (user_id, challenge_key, week),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )"""
        )
        # Variable-reward surprise: a post can be randomly "featured".
        try:
            conn.execute("ALTER TABLE rumors ADD COLUMN featured INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass  # column already exists
    else:  # Postgres (Supabase)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                real_name TEXT NOT NULL,
                handle TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                banned INTEGER NOT NULL DEFAULT 0
            )"""
        )
        # Self-heal: drop the removed email column if it still exists.
        try:
            conn.execute("ALTER TABLE users DROP COLUMN IF EXISTS email")
        except Exception:
            pass
        conn.execute(
            """CREATE TABLE IF NOT EXISTS rumors (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                rumor_id INTEGER NOT NULL REFERENCES rumors(id),
                kind TEXT NOT NULL,
                UNIQUE(user_id, rumor_id, kind)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS me_too (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                rumor_id INTEGER NOT NULL REFERENCES rumors(id),
                UNIQUE(user_id, rumor_id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS comments (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                rumor_id INTEGER NOT NULL REFERENCES rumors(id),
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS rumor_tags (
                rumor_id INTEGER NOT NULL REFERENCES rumors(id),
                tag_id INTEGER NOT NULL REFERENCES tags(id),
                PRIMARY KEY (rumor_id, tag_id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tag_follows (
                user_id INTEGER NOT NULL REFERENCES users(id),
                tag_id INTEGER NOT NULL REFERENCES tags(id),
                PRIMARY KEY (user_id, tag_id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS challenge_claims (
                user_id INTEGER NOT NULL REFERENCES users(id),
                challenge_key TEXT NOT NULL,
                week TEXT NOT NULL,
                claimed_at TEXT NOT NULL,
                PRIMARY KEY (user_id, challenge_key, week)
            )"""
        )
        conn.execute(
            "ALTER TABLE rumors ADD COLUMN IF NOT EXISTS featured INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    conn.close()


def hash_password(pw):
    return generate_password_hash(pw)


def _generate_handle(conn):
    """Create a unique random handle (privacy: user doesn't pick/see it)."""
    import random, string
    while True:
        slug = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        handle = f"anon_{slug}"
        exists = exec(conn, "SELECT 1 FROM users WHERE handle=?",
                     (handle,)).fetchone()
        if not exists:
            return handle


# ============================================================
# Reward system (research-grounded — see engagement-feature-design skill)
# Points are the engine (correlate with all engagement types); badges are
# decoration; challenges refresh weekly (beat novelty wear-off); leaderboard
# is anonymized (privacy prerequisite for an anon board).
# ============================================================

# Points economy (kept small + legible).
PTS_POST = 10
PTS_COMMENT = 3
PTS_REACT_GIVEN = 1
PTS_REACT_RECEIVED = 2
PTS_METOO_RECEIVED = 2

# Milestone badges: key -> (label, threshold on post count) or custom.
BADGE_DEFS = [
    ("first_whisper", "First Whisper", 1),
    ("ten_whispers", "10 Whispers", 10),
    ("fifty_whispers", "50 Whispers", 50),
    ("hundred_whispers", "Century Club", 100),
]

# Weekly challenges: key -> (label, goal, reward points, kind).
CHALLENGE_DEFS = [
    ("post_3", "Post 3 whispers this week", 3, 30, "post"),
    ("comment_5", "Leave 5 comments this week", 5, 25, "comment"),
    ("react_10", "React to 10 whispers this week", 10, 20, "react"),
]


def _current_week():
    """ISO year-week string, e.g. '2026-W29' — used to scope challenges."""
    from datetime import datetime, timezone
    iso = datetime.now(timezone.utc).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _week_start_iso():
    """UTC midnight of Monday this week, ISO string for created_at compares."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.isoformat()


def _count(conn, sql, params):
    row = exec(conn, sql, params).fetchone()
    if not row:
        return 0
    # row may be a dict-like or tuple depending on driver
    try:
        return int(row[0]) if not hasattr(row, "keys") else int(list(row)[0])
    except Exception:
        return int(row["c"]) if "c" in getattr(row, "keys", lambda: [])() else 0


def _compute_points(conn, user_id):
    """Sum a user's points from their activity across existing tables."""
    posts = _count(conn, "SELECT COUNT(*) FROM rumors WHERE user_id=?", (user_id,))
    comments = _count(conn, "SELECT COUNT(*) FROM comments WHERE user_id=?", (user_id,))
    react_given = _count(conn, "SELECT COUNT(*) FROM reactions WHERE user_id=?", (user_id,))
    react_recv = _count(conn,
        "SELECT COUNT(*) FROM reactions rx JOIN rumors r ON r.id=rx.rumor_id "
        "WHERE r.user_id=?", (user_id,))
    metoo_recv = _count(conn,
        "SELECT COUNT(*) FROM me_too m JOIN rumors r ON r.id=m.rumor_id "
        "WHERE r.user_id=?", (user_id,))
    # claimed challenge rewards
    claim_pts = 0
    rows = exec(conn,
        "SELECT challenge_key FROM challenge_claims WHERE user_id=?",
        (user_id,)).fetchall()
    reward_by_key = {c[0]: c[3] for c in CHALLENGE_DEFS}
    for r in rows:
        key = r[0] if not hasattr(r, "keys") else r["challenge_key"]
        claim_pts += reward_by_key.get(key, 0)
    return (posts * PTS_POST + comments * PTS_COMMENT +
            react_given * PTS_REACT_GIVEN + react_recv * PTS_REACT_RECEIVED +
            metoo_recv * PTS_METOO_RECEIVED + claim_pts)


def _compute_badges(conn, user_id):
    """Return unlocked badges (list of {key,label}) based on post count."""
    posts = _count(conn, "SELECT COUNT(*) FROM rumors WHERE user_id=?", (user_id,))
    out = []
    for key, label, threshold in BADGE_DEFS:
        if posts >= threshold:
            out.append({"key": key, "label": label})
    return out


def _challenge_progress(conn, user_id, kind):
    """Count this-week activity for a challenge kind."""
    ws = _week_start_iso()
    if kind == "post":
        return _count(conn,
            "SELECT COUNT(*) FROM rumors WHERE user_id=? AND created_at>=?",
            (user_id, ws))
    if kind == "comment":
        return _count(conn,
            "SELECT COUNT(*) FROM comments WHERE user_id=? AND created_at>=?",
            (user_id, ws))
    if kind == "react":
        # reactions table has no created_at; count all this user's reactions
        return _count(conn, "SELECT COUNT(*) FROM reactions WHERE user_id=?",
                      (user_id,))
    return 0


def _user_rank(conn, user_id):
    """1-based rank of a user by points (higher points = better rank)."""
    ids = [r[0] if not hasattr(r, "keys") else r["id"]
           for r in exec(conn, "SELECT id FROM users WHERE banned=0", ()).fetchall()]
    scored = sorted(((uid, _compute_points(conn, uid)) for uid in ids),
                    key=lambda t: t[1], reverse=True)
    for i, (uid, _pts) in enumerate(scored, start=1):
        if uid == user_id:
            return i
    return None
