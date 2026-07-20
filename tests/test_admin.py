"""Admin access: only the owner can see real identities and ban/delete."""
import pytest
from tests.helpers import register_and_login


def _login_admin(client, password):
    # Admin is email-based; use the configured owner address.
    from app import create_app
    email = create_app().config["ADMIN_EMAIL"]
    return client.post("/api/admin/login", json={"email": email, "password": password})


def test_admin_login_rejects_non_owner_email(client):
    # Only the owner's Gmail may obtain an admin session.
    r = client.post("/api/admin/login",
                    json={"email": "someoneelse@x.com", "password": "admin123"})
    assert r.status_code == 401
    assert client.get("/api/admin/rumors").status_code == 401


def test_admin_dashboard_requires_login(client):
    assert client.get("/api/admin/rumors").status_code == 401


def test_admin_sees_real_identity_and_email(client):
    register_and_login(
        client, handle="ghost42", email="rahul@x.com", real_name="Rahul Kumar"
    )
    client.post("/api/rumors", json={"text": "misbehaving post"})
    _login_admin(client, "admin123")
    data = client.get("/api/admin/rumors").get_json()
    assert len(data["rumors"]) == 1
    r = data["rumors"][0]
    assert r["real_name"] == "Rahul Kumar"
    assert r["email"] == "rahul@x.com"
    assert r["handle"] == "ghost42"


def test_admin_can_delete_a_rumor(client):
    register_and_login(client, handle="usr1", email="e@x.com")
    client.post("/api/rumors", json={"text": "To be deleted."})
    _login_admin(client, "admin123")
    rid = client.get("/api/admin/rumors").get_json()["rumors"][0]["id"]
    assert client.delete(f"/api/admin/rumors/{rid}").status_code == 200
    assert client.get("/api/rumors").get_json()["rumors"] == []


def test_admin_can_ban_a_user(client):
    register_and_login(client, handle="usr1", email="e@x.com")
    _login_admin(client, "admin123")
    uid = client.get("/api/admin/users").get_json()["users"][0]["id"]
    assert client.delete(f"/api/admin/users/{uid}").status_code == 200
    # banned user can no longer log in
    r = client.post(
        "/api/login", json={"identifier": "e@x.com", "password": "pw123"}
    )
    assert r.status_code == 403


def test_delete_requires_login(client):
    register_and_login(client, handle="usr1", email="e@x.com")
    client.post("/api/rumors", json={"text": "x"})
    rid = client.get("/api/rumors").get_json()["rumors"][0]["id"]
    assert client.delete(f"/api/admin/rumors/{rid}").status_code == 401


def test_ban_requires_login(client):
    register_and_login(client, handle="usr1", email="e@x.com")
    _login_admin(client, "admin123")
    uid = client.get("/api/admin/users").get_json()["users"][0]["id"]
    client.get("/api/admin/rumors")  # refresh nothing; just ensure admin still set
    # logout simulation: new client without admin session
    from app import create_app, init_db
    app2 = create_app({"TESTING": True, "DB_PATH": client.application.config["DB_PATH"]})
    with app2.test_client() as c2:
        assert c2.delete(f"/api/admin/users/{uid}").status_code == 401
