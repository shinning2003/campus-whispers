"""Admin access: only the owner can log in and see/delete all rumors."""
import pytest


def _login(client, password):
    return client.post("/api/admin/login", json={"password": password})


def test_admin_login_wrong_password_rejected(client):
    resp = _login(client, "wrong-password")
    assert resp.status_code == 401


def test_admin_dashboard_requires_login(client):
    # Not logged in -> forbidden
    resp = client.get("/api/admin/rumors")
    assert resp.status_code == 401


def test_admin_login_then_access_dashboard(client):
    resp = _login(client, "admin123")
    assert resp.status_code == 200
    # Logged in -> can see the full list
    client.post("/api/rumors", json={"text": "Secret rumor only admin sees count."})
    resp = client.get("/api/admin/rumors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["rumors"]) == 1


def test_admin_can_delete_a_rumor(client):
    client.post("/api/rumors", json={"text": "To be deleted."})
    _login(client, "admin123")
    # grab its id from the dashboard
    dash = client.get("/api/admin/rumors").get_json()
    rid = dash["rumors"][0]["id"]
    del_resp = client.delete(f"/api/admin/rumors/{rid}")
    assert del_resp.status_code == 200
    # public feed now empty
    assert client.get("/api/rumors").get_json()["rumors"] == []


def test_delete_requires_login(client):
    client.post("/api/rumors", json={"text": "Cannot be deleted by stranger."})
    rid = client.get("/api/rumors").get_json()["rumors"][0]["id"]
    resp = client.delete(f"/api/admin/rumors/{rid}")
    assert resp.status_code == 401
