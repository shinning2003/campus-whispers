"""Feature 4: Hot/Rising feed + mystery teaser.

Psychological lever: Hunt reward (variable reward — you never know what
secret you'll find next) + Information-Gap Theory (Loewenstein) — a teaser
that hides the text opens a knowledge gap that pulls a click.
"""
import pytest
from tests.helpers import register_and_login


def _post(client, handle, email, text):
    register_and_login(client, handle=handle, email=email)
    r = client.post("/api/rumors", json={"text": text})
    return r.get_json()["id"]


def _react_all(client, rid, kinds):
    for k in kinds:
        client.post(f"/api/rumors/{rid}/react", json={"kind": k})


def test_hot_feed_orders_by_engagement(client):
    a = _post(client, "aaa", "a@x.com", "hot rumor")
    # give 'a' lots of engagement via fresh users
    for i in range(3):
        register_and_login(client, handle=f"usr{i}", email=f"u{i}@x.com")
        _react_all(client, a, ["fire", "laugh"])
        client.post(f"/api/rumors/{a}/metoo")
    b = _post(client, "zzz", "z@x.com", "cold rumor")
    hot = client.get("/api/rumors?sort=hot").get_json()["rumors"]
    assert hot[0]["id"] == a


def test_rising_feed_orders_newest_first(client):
    old = _post(client, "aaa", "a@x.com", "old one")
    new = _post(client, "bbb", "b@x.com", "new one")
    rising = client.get("/api/rumors?sort=rising").get_json()["rumors"]
    assert rising[0]["id"] == new


def test_mystery_teaser_hides_text(client):
    rid = _post(client, "aaa", "a@x.com", "Someone in CSE batch cheated")
    r = client.get(f"/api/rumors/{rid}/teaser").get_json()
    assert "text" not in r
    assert r["handle"] == "aaa"
    assert "…" in r["teaser"]
    assert r["reactions"]  # present


def test_default_feed_is_newest(client):
    _post(client, "aaa", "a@x.com", "first")
    _post(client, "bbb", "b@x.com", "second")
    feed = client.get("/api/rumors").get_json()["rumors"]
    assert feed[0]["text"] == "second"
