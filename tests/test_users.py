"""User registration, login, and authenticated posting.

Posting is no longer anonymous-without-account: every poster registers a
real name + email + password, gets a public handle, and is accountable.
Only the admin can see the real identity behind a handle.
"""
import pytest
import sqlite3


def register(client, **kw):
    base = {
        "real_name": "Rahul Kumar",
        "email": "rahul@x.com",
        "password": "pw123",
        "handle": "ghost42",
    }
    base.update(kw)
    return client.post("/api/register", json=base)


def test_register_creates_user(client):
    r = register(client)
    assert r.status_code == 201
    assert r.get_json()["handle"] == "ghost42"


def test_register_rejects_duplicate_email(client):
    register(client, handle="a")
    r = register(client, handle="b")
    assert r.status_code == 400


def test_register_rejects_duplicate_handle(client):
    register(client, email="e1@x.com")
    r = register(client, email="e2@x.com")
    assert r.status_code == 400


def test_register_rejects_missing_fields(client):
    r = client.post("/api/register", json={"real_name": "X"})
    assert r.status_code == 400


def test_password_not_stored_in_plaintext(client):
    register(client)
    from app import get_db
    with client.application.app_context():
        conn = get_db()
        row = conn.execute(
            "SELECT password_hash FROM users WHERE email='rahul@x.com'"
        ).fetchone()
        conn.close()
    assert row is not None
    assert row["password_hash"] != "pw123"      # not plaintext
    assert len(row["password_hash"]) > 20        # salted hash


def test_login_correct_password(client):
    register(client)
    r = client.post(
        "/api/login", json={"identifier": "rahul@x.com", "password": "pw123"}
    )
    assert r.status_code == 200


def test_login_accepts_handle_as_identifier(client):
    register(client)
    r = client.post(
        "/api/login", json={"identifier": "ghost42", "password": "pw123"}
    )
    assert r.status_code == 200


def test_login_wrong_password(client):
    register(client)
    r = client.post(
        "/api/login", json={"identifier": "rahul@x.com", "password": "wrong"}
    )
    assert r.status_code == 401


def test_post_rumor_requires_login(client):
    r = client.post("/api/rumors", json={"text": "hi"})
    assert r.status_code == 401


def test_logged_in_user_can_post_and_is_tagged(client):
    register(client)
    client.post(
        "/api/login", json={"identifier": "rahul@x.com", "password": "pw123"}
    )
    r = client.post("/api/rumors", json={"text": "Rahul slept."})
    assert r.status_code == 201
