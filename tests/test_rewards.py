"""Reward system: points, badges, weekly challenges, anonymized leaderboard,
variable-reward 'featured' surprise, and the rising-star gentle floor.

Research grounding (see engagement-feature-design skill):
- Points correlate with all engagement types (Springer 2024, N=440); badges
  mostly with participation and can raise cognitive load if used alone (RCT
  2025) -> points are the engine, badges are decoration.
- Leaderboards are the strongest single element (PLOS One review) BUT must be
  anonymized on an anonymous board (privacy prerequisite).
- Variable-ratio reward schedules drive dopamine/re-checking (Lindstrom 2021,
  Nature Comms) -> random 'featured' surprise.
- Youth are highly sensitive to absence of feedback (Science Advances) ->
  rising-star floor so new posts never publicly read as '0 = failure'.
"""
import pytest
from app import create_app
from tests.helpers import register_and_login

ADMIN_EMAIL = create_app().config["ADMIN_EMAIL"]


def _login_fresh(client, handle, email):
    register_and_login(client, handle=handle, email=email)


def _post(client, text, tags=None):
    r = client.post("/api/rumors", json={"text": text, "tags": tags or []})
    return r.get_json()["id"]


# ---------------- Points ----------------

def test_points_awarded_for_activity(client):
    register_and_login(client, handle="pt1", email="pt1@x.com")
    # posting earns points
    rid = _post(client, "my first whisper")
    me = client.get("/api/me").get_json()
    assert me["points"] >= 10  # post = 10 pts (base)
    # commenting earns points
    client.post(f"/api/rumors/{rid}/comments", json={"text": "a comment"})
    me2 = client.get("/api/me").get_json()
    assert me2["points"] > me["points"]


def test_points_for_reactions_given_and_received(client):
    register_and_login(client, handle="author", email="author@x.com")
    rid = _post(client, "react to me")
    base = client.get("/api/me").get_json()["points"]
    # a second user reacts -> author gains "received reaction" points
    register_and_login(client, handle="reactor", email="reactor@x.com")
    client.post(f"/api/rumors/{rid}/react", json={"kind": "fire"})
    reactor_pts = client.get("/api/me").get_json()["points"]
    assert reactor_pts > 0  # reacting earns the reactor points too
    # log back in as author, points should have increased from received reaction
    client.post("/api/login", json={"identifier": "author@x.com", "password": "pw123"})
    after = client.get("/api/me").get_json()["points"]
    assert after > base


# ---------------- Badges ----------------

def test_badges_unlock_on_milestones(client):
    register_and_login(client, handle="badger", email="badger@x.com")
    me = client.get("/api/me").get_json()
    assert me["badges"] == [] or "first_whisper" not in [b["key"] for b in me["badges"]]
    _post(client, "first post")
    me2 = client.get("/api/me").get_json()
    keys = [b["key"] for b in me2["badges"]]
    assert "first_whisper" in keys  # 1 post unlocks first_whisper badge


# ---------------- Weekly challenges ----------------

def test_challenges_listed_with_progress(client):
    register_and_login(client, handle="ch1", email="ch1@x.com")
    r = client.get("/api/challenges")
    assert r.status_code == 200
    data = r.get_json()
    assert "challenges" in data and len(data["challenges"]) >= 1
    ch = data["challenges"][0]
    assert "key" in ch and "goal" in ch and "progress" in ch and "reward" in ch


def test_challenge_progress_increases_with_activity(client):
    register_and_login(client, handle="ch2", email="ch2@x.com")
    before = client.get("/api/challenges").get_json()["challenges"]
    post_ch = [c for c in before if c["key"] == "post_3"][0]
    assert post_ch["progress"] == 0
    _post(client, "one")
    _post(client, "two")
    after = client.get("/api/challenges").get_json()["challenges"]
    post_ch2 = [c for c in after if c["key"] == "post_3"][0]
    assert post_ch2["progress"] == 2
    assert post_ch2["completed"] is False
    _post(client, "three")
    done = client.get("/api/challenges").get_json()["challenges"]
    post_ch3 = [c for c in done if c["key"] == "post_3"][0]
    assert post_ch3["progress"] == 3
    assert post_ch3["completed"] is True


def test_challenge_claim_awards_points_once(client):
    register_and_login(client, handle="ch3", email="ch3@x.com")
    _post(client, "a"); _post(client, "b"); _post(client, "c")
    before_pts = client.get("/api/me").get_json()["points"]
    r = client.post("/api/challenges/post_3/claim")
    assert r.status_code == 200
    after_pts = client.get("/api/me").get_json()["points"]
    assert after_pts > before_pts
    # second claim rejected (already claimed this week)
    r2 = client.post("/api/challenges/post_3/claim")
    assert r2.status_code == 400


def test_challenge_claim_rejected_if_incomplete(client):
    register_and_login(client, handle="ch4", email="ch4@x.com")
    _post(client, "only one")
    r = client.post("/api/challenges/post_3/claim")
    assert r.status_code == 400


# ---------------- Anonymized leaderboard ----------------

def test_leaderboard_is_anonymized(client):
    register_and_login(client, handle="realhandle", email="lb1@x.com")
    _post(client, "post for points")
    r = client.get("/api/leaderboard")
    assert r.status_code == 200
    data = r.get_json()
    assert "leaderboard" in data
    top = data["leaderboard"][0]
    assert "points" in top and "rank" in top
    # never leak the real handle, email, or real_name
    assert "handle" not in top or top["handle"] != "realhandle"
    assert "email" not in top
    assert "real_name" not in top


def test_leaderboard_shows_own_rank_privately(client):
    register_and_login(client, handle="me_lb", email="lb2@x.com")
    _post(client, "hi")
    me = client.get("/api/me").get_json()
    assert "rank" in me  # my own rank surfaced privately on /api/me


# ---------------- Variable-reward surprise (featured) ----------------

def test_post_can_be_featured_flag_present(client):
    register_and_login(client, handle="feat", email="feat@x.com")
    rid = _post(client, "maybe featured")
    feed = client.get("/api/rumors").get_json()["rumors"]
    row = [x for x in feed if x["id"] == rid][0]
    assert "featured" in row  # feed exposes featured flag for UI badge


def test_admin_can_feature_a_post(client):
    register_and_login(client, handle="feat2", email="feat2@x.com")
    rid = _post(client, "feature me")
    client.post("/api/admin/login", json={"email": ADMIN_EMAIL, "password": "admin123"})
    r = client.post(f"/api/admin/rumors/{rid}/feature")
    assert r.status_code == 200
    feed = client.get("/api/rumors").get_json()["rumors"]
    row = [x for x in feed if x["id"] == rid][0]
    assert row["featured"] == 1


# ---------------- Rising-star gentle floor ----------------

def test_new_post_has_rising_star_window(client):
    register_and_login(client, handle="rising", email="rs@x.com")
    rid = _post(client, "brand new")
    feed = client.get("/api/rumors").get_json()["rumors"]
    row = [x for x in feed if x["id"] == rid][0]
    # a freshly posted whisper is flagged 'is_new' so UI can soften 0-counts
    assert row.get("is_new") is True
