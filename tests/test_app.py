"""Public feed behavior under the account model."""
import pytest
from tests.helpers import register_and_login


def test_public_feed_shows_handle_not_real_name(client):
    register_and_login(client, handle="ghost42", email="r@x.com", real_name="Rahul K")
    client.post("/api/rumors", json={"text": "Slept in class."})
    r = client.get("/api/rumors")
    assert r.status_code == 200
    rumor = r.get_json()["rumors"][0]
    assert rumor["handle"] == "ghost42"
    assert "real_name" not in rumor          # hidden from public
    assert "email" not in rumor
    assert rumor["text"] == "Slept in class."


def test_empty_rumor_rejected(client):
    register_and_login(client, handle="usr1", email="e@x.com")
    r = client.post("/api/rumors", json={"text": "   "})
    assert r.status_code == 400


def test_public_feed_orders_newest_first(client):
    register_and_login(client, handle="usr1", email="e@x.com")
    client.post("/api/rumors", json={"text": "first"})
    client.post("/api/rumors", json={"text": "second"})
    r = client.get("/api/rumors").get_json()
    assert r["rumors"][0]["text"] == "second"
