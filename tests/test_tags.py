"""Feature 5: Tags/categories + follow-a-tag.

Psychological lever: Investment (following a tag stores a preference and
loads the next trigger) + builds an internal trigger ("what's new in #exam?").
Tags are a shared vocabulary; posting assigns tags, feed filters by tag, and
users follow tags to curate their view.
"""
import pytest
from tests.helpers import register_and_login


def _post_with_tags(client, handle, email, text, tags):
    register_and_login(client, handle=handle, email=email)
    r = client.post("/api/rumors", json={"text": text, "tags": tags})
    return r.get_json()["id"]


def test_post_accepts_tags(client):
    rid = _post_with_tags(client, "aaa", "a@x.com", "exam was tough", ["exam"])
    feed = client.get("/api/rumors").get_json()["rumors"][0]
    assert "exam" in feed["tags"]


def test_tag_feed_filters(client):
    _post_with_tags(client, "aaa", "a@x.com", "exam leak", ["exam"])
    _post_with_tags(client, "bbb", "b@x.com", "canteen food", ["food"])
    exam_feed = client.get("/api/rumors?tag=exam").get_json()["rumors"]
    assert len(exam_feed) == 1
    assert "exam" in exam_feed[0]["tags"]


def test_follow_tag_records_preference(client):
    register_and_login(client, handle="aaa", email="a@x.com")
    r = client.post("/api/tags/exam/follow", json={})
    assert r.status_code == 200
    mine = client.get("/api/me/tags").get_json()
    assert "exam" in mine["followed_tags"]


def test_unfollow_tag(client):
    register_and_login(client, handle="aaa", email="a@x.com")
    client.post("/api/tags/exam/follow", json={})
    client.delete("/api/tags/exam/follow")
    mine = client.get("/api/me/tags").get_json()
    assert "exam" not in mine["followed_tags"]


def test_followed_feed_only_shows_followed_tags(client):
    _post_with_tags(client, "aaa", "a@x.com", "exam leak", ["exam"])
    _post_with_tags(client, "bbb", "b@x.com", "sports win", ["sports"])
    register_and_login(client, handle="ccc", email="c@x.com")
    client.post("/api/tags/exam/follow", json={})
    feed = client.get("/api/rumors?filter=followed").get_json()["rumors"]
    assert len(feed) == 1
    assert "exam" in feed[0]["tags"]


def test_tag_listing(client):
    _post_with_tags(client, "aaa", "a@x.com", "x", ["exam"])
    _post_with_tags(client, "bbb", "b@x.com", "y", ["sports"])
    tags = client.get("/api/tags").get_json()["tags"]
    names = {t["name"] for t in tags}
    assert {"exam", "sports"} <= names
