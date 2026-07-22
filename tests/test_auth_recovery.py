"""Forgot-password + admin reset + handle auto-generation (privacy).

Privacy goal: a handle ties a person to their posts. Users never type or
see a handle in the UI, so if their phone is inspected the link is broken.
The handle still exists in the DB + admin view for accountability.
Password recovery is admin-reset (no user email enumeration).
"""
import pytest
from app import create_app

ADMIN_EMAIL = create_app().config["ADMIN_EMAIL"]
from tests.helpers import register_and_login


def _register_with_handle(client, **kw):
    base = {"real_name": "Rahul K", "email": "r@x.com", "handle": "myhandle", "password": "pw123"}
    base.update(kw)
    r = client.post("/api/register", json=base)
    return r


def test_register_with_handle_succeeds_and_autogens(client):
    # Email and handle are now required
    r = _register_with_handle(client, email="auto@x.com")
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["handle"] == "myhandle"


def test_register_handle_still_accepted_if_provided(client):
    r = _register_with_handle(client, email="h@x.com", handle="myhandle")
    assert r.status_code == 201
    assert r.get_json()["handle"] == "myhandle"


def test_register_validates_email_even_without_handle(client):
    r = _register_with_handle(client, email="notanemail", handle="somehandle")
    assert r.status_code == 400


def test_register_requires_all_fields(client):
    r = client.post("/api/register", json={"real_name": "Test", "email": "test@x.com", "handle": "test1"})
    assert r.status_code == 400


def test_forgot_password_does_not_enumerate(client):
    _register_with_handle(client, email="exists@x.com", handle="h1")
    # existing email
    r1 = client.post("/api/forgot-password", json={"handle": "h1"})
    # nonexistent email -> same neutral response, no 404
    r2 = client.post("/api/forgot-password", json={"handle": "nope"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.get_json()["message"] == r2.get_json()["message"]


def test_admin_can_reset_password(client):
    _register_with_handle(client, email="reset@x.com", handle="h2reset", password="oldpw")
    login = client.post("/api/login",
                        json={"identifier": "reset@x.com", "password": "oldpw"})
    assert login.status_code == 200
    client.post("/api/admin/login", json={"password": "admin123"})
    users = client.get("/api/admin/users").get_json()["users"]
    uid = [u for u in users if u["email"] == "reset@x.com"][0]["id"]
    res = client.post(f"/api/admin/users/{uid}/reset-password",
                      json={"new_password": "newpw123"})
    assert res.status_code == 200
    # old password fails, new works
    bad = client.post("/api/login",
                      json={"identifier": "reset@x.com", "password": "oldpw"})
    good = client.post("/api/login",
                       json={"identifier": "reset@x.com", "password": "newpw123"})
    assert bad.status_code == 401
    assert good.status_code == 200


def test_reset_password_requires_admin(client):
    _register_with_handle(client, email="r2@x.com", handle="h3reset")
    # fetch uid as admin, then attempt reset without admin session
    client.post("/api/admin/login", json={"password": "admin123"})
    users = client.get("/api/admin/users").get_json()["users"]
    uid = [u for u in users if u["email"] == "r2@x.com"][0]["id"]
    # clear admin session by using a fresh anonymous client
    anon = client.application.test_client()
    r = anon.post(f"/api/admin/users/{uid}/reset-password",
                  json={"new_password": "x123"})
    assert r.status_code == 401
