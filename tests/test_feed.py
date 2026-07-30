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


def test_hot_feed_orders_by_engagement(client):
    """Hot defaults to newest now that reactions/comments are removed."""
    a = _post(client, "aaa", "a@x.com", "old rumor")
    b = _post(client, "zzz", "z@x.com", "new rumor")
    hot = client.get("/api/rumors?sort=hot").get_json()["rumors"]
    assert hot[0]["id"] == b  # newest first


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


def test_bump_updates_feed_order(client):
    register_and_login(client, handle="aaa", email="a@x.com")
    first = client.post("/api/rumors", json={"text": "old rumor"}).get_json()["id"]
    second = client.post("/api/rumors", json={"text": "new rumor"}).get_json()["id"]
    # grant enough points and buy bump for the older whisper
    client.post("/api/admin/login", json={"password": "admin123"})
    users = client.get("/api/admin/users").get_json()["users"]
    uid = next(u["id"] for u in users if u["handle"] == "aaa")
    client.post(f"/api/admin/users/{uid}/grant-points", json={"amount": 100})
    r = client.post("/api/shop/buy", json={"kind": "bump", "rumor_id": first})
    assert r.status_code == 200
    payload = r.get_json()
    # bump returns points
    assert "points" in payload
    feed = client.get("/api/rumors").get_json()["rumors"]
    assert feed[0]["id"] == first
    assert feed[1]["id"] == second
    # bumped flag is present
    bumped_rumor = next(f for f in feed if f["id"] == first)
    assert bumped_rumor.get("bumped") is True
    # /api/me includes recent_bumped
    me = client.get("/api/me").get_json()
    assert len(me["recent_bumped"]) >= 1
    assert me["recent_bumped"][0]["id"] == first
    # second bump on same whisper triggers cooldown
    r2 = client.post("/api/shop/buy", json={"kind": "bump", "rumor_id": first})
    assert r2.status_code == 400


def test_shop_catalog_omits_custom_alias_and_includes_featured(client):
    shop = client.get("/api/shop").get_json()["items"]
    # alias is now a purchasable item
    assert shop["alias"]["label"] == "✏️ Custom Alias"
    assert shop["featured"]["label"] == "👑 Featured Spot"
    assert "highlight" in shop and "bump" in shop and "incognito" in shop
