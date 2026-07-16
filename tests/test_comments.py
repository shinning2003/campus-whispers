"""Feature 2: Anonymous comments/replies on rumors.

Psychological lever: Investment (contributing to the product increases the
odds of another hook pass) + Tribe (peer interaction). Comments are anonymous
like rumors — handle shown, real identity hidden.
"""
import pytest
from tests.helpers import register_and_login


def _post(client, handle, email, text):
    register_and_login(client, handle=handle, email=email)
    r = client.post("/api/rumors", json={"text": text})
    return r.get_json()["id"]


def test_comment_requires_login(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    anon = client.application.test_client()
    r = anon.post(f"/api/rumors/{rid}/comments", json={"text": "same"})
    assert r.status_code == 401


def test_comment_empty_rejected(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    r = client.post(f"/api/rumors/{rid}/comments", json={"text": "   "})
    assert r.status_code == 400


def test_comment_posted_and_listed_with_handle(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    client.post(f"/api/rumors/{rid}/comments", json={"text": "me too!"})
    j = client.get(f"/api/rumors/{rid}/comments").get_json()
    assert j["comments"][0]["text"] == "me too!"
    assert j["comments"][0]["handle"] == "aaa"
    assert "real_name" not in j["comments"][0]
    assert "email" not in j["comments"][0]


def test_comment_feed_count_exposed(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    client.post(f"/api/rumors/{rid}/comments", json={"text": "c1"})
    client.post(f"/api/rumors/{rid}/comments", json={"text": "c2"})
    feed = client.get("/api/rumors").get_json()["rumors"][0]
    assert feed["comment_count"] == 2


def test_commenter_can_delete_own(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    cid = client.post(f"/api/rumors/{rid}/comments",
                      json={"text": "delete me"}).get_json()["id"]
    r = client.delete(f"/api/comments/{cid}")
    assert r.status_code == 200
    assert client.get(f"/api/rumors/{rid}/comments").get_json()["comments"] == []


def test_cannot_delete_others_comment(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    cid = client.post(f"/api/rumors/{rid}/comments",
                      json={"text": "mine"}).get_json()["id"]
    register_and_login(client, handle="bbb", email="b@x.com")
    r = client.delete(f"/api/comments/{cid}")
    assert r.status_code == 403


def test_banned_user_comments_hidden(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    register_and_login(client, handle="bbb", email="b@x.com")
    client.post(f"/api/rumors/{rid}/comments", json={"text": "spam"})
    # admin bans bbb -> their comment must disappear
    client.post("/api/admin/login", json={"password": "admin123"})
    users = client.get("/api/admin/users").get_json()["users"]
    bbb = [u for u in users if u["handle"] == "bbb"][0]
    client.delete(f"/api/admin/users/{bbb['id']}")
    comments = client.get(f"/api/rumors/{rid}/comments").get_json()["comments"]
    assert all(c["handle"] != "bbb" for c in comments)
