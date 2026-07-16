"""Feature 3: Posting streak with loss-aversion framing + grace recovery.

Psychological lever: Self reward + goal-gradient (Duolingo effect). Streaks
boost engagement, but a *broken* streak causes churn (Nikzad 2021: 22%
next-day drop unless a grace/freeze mechanism lets recovery). We implement a
1-day grace window so a single missed day doesn't reset to zero.
"""
import pytest
from datetime import datetime, timezone, timedelta
from tests.helpers import register_and_login
from app import create_app, get_db, init_db


def _now_iso(offset_days=0):
    return (datetime.now(timezone.utc) + timedelta(days=offset_days)).isoformat()


def _seed_post_at(client, day_offset):
    # Use the DB directly to set created_at to a specific day, then read streak.
    app = client.application
    with app.app_context():
        conn = get_db()
        uid = conn.execute(
            "SELECT id FROM users WHERE handle='streak1'").fetchone()["id"]
        conn.execute(
            "INSERT INTO rumors (user_id, text, created_at) VALUES (?,?,?)",
            (uid, "seeded", _now_iso(day_offset)))
        conn.commit()
        conn.close()


def test_new_user_has_zero_streak(client):
    register_and_login(client, handle="streak1", email="s@x.com")
    j = client.get("/api/me").get_json()
    assert j["streak"] == 0


def test_posting_today_starts_streak(client):
    register_and_login(client, handle="streak1", email="s@x.com")
    client.post("/api/rumors", json={"text": "day1"})
    j = client.get("/api/me").get_json()
    assert j["streak"] == 1
    assert j["streak_at_risk_today"] is False  # just started today


def test_consecutive_days_increment(client, tmp_path):
    app = create_app({"TESTING": True, "DB_PATH": str(tmp_path / "s.db")})
    with app.app_context():
        conn = get_db(); conn.execute("DROP TABLE IF EXISTS rumors")
        conn.execute("DROP TABLE IF EXISTS users"); conn.commit(); conn.close()
        init_db()
    c = app.test_client()
    register_and_login(c, handle="streak1", email="s@x.com")
    _seed_post_at(c, -2)  # 2 days ago
    _seed_post_at(c, -1)  # 1 day ago
    j = c.get("/api/me").get_json()
    assert j["streak"] == 2


def test_missing_day_but_grace_keeps_streak(client, tmp_path):
    app = create_app({"TESTING": True, "DB_PATH": str(tmp_path / "s.db")})
    with app.app_context():
        conn = get_db(); conn.execute("DROP TABLE IF EXISTS rumors")
        conn.execute("DROP TABLE IF EXISTS users"); conn.commit(); conn.close()
        init_db()
    c = app.test_client()
    register_and_login(c, handle="streak1", email="s@x.com")
    _seed_post_at(c, -2)  # 2 days ago
    _seed_post_at(c, -1)  # 1 day ago (yesterday) -> within grace
    # today missed but yesterday posted -> 1-day grace keeps streak at 2
    j = c.get("/api/me").get_json()
    assert j["streak"] == 2
    assert j["streak_at_risk_today"] is True


def test_gap_beyond_grace_resets_streak(client, tmp_path):
    app = create_app({"TESTING": True, "DB_PATH": str(tmp_path / "s.db")})
    with app.app_context():
        conn = get_db(); conn.execute("DROP TABLE IF EXISTS rumors")
        conn.execute("DROP TABLE IF EXISTS users"); conn.commit(); conn.close()
        init_db()
    c = app.test_client()
    register_and_login(c, handle="streak1", email="s@x.com")
    _seed_post_at(c, -5)  # 5 days ago (beyond 1-day grace)
    j = c.get("/api/me").get_json()
    assert j["streak"] == 0


def test_streak_endpoint_requires_login(client):
    anon = client.application.test_client()
    r = anon.get("/api/me")
    assert r.status_code == 401
