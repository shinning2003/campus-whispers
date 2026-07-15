"""Static page routes: public board + admin dashboard HTML."""
import pytest


def test_public_index_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Campus Whispers" in resp.data


def test_admin_page_loads(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert b"Admin" in resp.data
