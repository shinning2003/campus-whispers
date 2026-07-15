"""Shared test helpers for the account model."""
import pytest


def register_and_login(client, **kw):
    base = {
        "real_name": "Rahul Kumar",
        "email": "rahul@x.com",
        "password": "pw123",
        "handle": "ghost42",
    }
    base.update(kw)
    r = client.post("/api/register", json=base)
    assert r.status_code == 201, r.get_json()
    login = client.post(
        "/api/login",
        json={"identifier": base["email"], "password": base["password"]},
    )
    assert login.status_code == 200, login.get_json()
    return r
