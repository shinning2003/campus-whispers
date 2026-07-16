"""Feature 1: Reactions (😂🔥💯😮) + 'Me too' counter.

Psychological lever: Tribe reward (social validation) + "I am not alone"
identification — the #1 driver of posting on anonymous boards (Whisper/YikYak
studies). Reactions give readers a low-effort way to validate a poster.
"""
import pytest
from tests.helpers import register_and_login


VALID_KINDS = {"laugh", "fire", "hundred", "shock"}


def _post(client, handle, email, text):
    register_and_login(client, handle=handle, email=email)
    r = client.post("/api/rumors", json={"text": text})
    return r.get_json()["id"]


def test_react_requires_login(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    anon = client.application.test_client()  # no session -> not logged in
    r = anon.post(f"/api/rumors/{rid}/react", json={"kind": "fire"})
    assert r.status_code == 401


def test_react_unknown_kind_rejected(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    r = client.post(f"/api/rumors/{rid}/react", json={"kind": "bogus"})
    assert r.status_code == 400
    assert "reaction" in r.get_json()["error"].lower()


def test_react_toggles_on_and_off(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    r = client.post(f"/api/rumors/{rid}/react", json={"kind": "fire"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["reacted"] is True
    assert body["count"] == 1  # live count returned for instant UI update
    # toggle off
    r = client.post(f"/api/rumors/{rid}/react", json={"kind": "fire"})
    body = r.get_json()
    assert body["reacted"] is False
    assert body["count"] == 0


def test_react_counts_aggregate_per_kind(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    # three different users react fire
    client.post(f"/api/rumors/{rid}/react", json={"kind": "fire"})
    register_and_login(client, handle="bbb", email="b@x.com")
    client.post(f"/api/rumors/{rid}/react", json={"kind": "fire"})
    register_and_login(client, handle="ccc", email="c@x.com")
    client.post(f"/api/rumors/{rid}/react", json={"kind": "laugh"})
    feed = client.get("/api/rumors").get_json()["rumors"][0]
    assert feed["reactions"]["fire"] == 2
    assert feed["reactions"]["laugh"] == 1
    assert feed["reactions"]["hundred"] == 0
    assert feed["reactions"]["shock"] == 0


def test_metoo_toggle_and_count(client):
    rid = _post(client, "aaa", "a@x.com", "I failed my exam")
    r = client.post(f"/api/rumors/{rid}/metoo")
    body = r.get_json()
    assert body["active"] is True
    assert body["count"] == 1  # live count for instant UI update
    register_and_login(client, handle="bbb", email="b@x.com")
    r = client.post(f"/api/rumors/{rid}/metoo")
    assert r.get_json()["count"] == 2
    feed = client.get("/api/rumors").get_json()["rumors"][0]
    assert feed["me_too_count"] == 2


def test_reactions_hidden_from_public_no_real_identity(client):
    rid = _post(client, "aaa", "a@x.com", "hi")
    client.post(f"/api/rumors/{rid}/react", json={"kind": "fire"})
    feed = client.get("/api/rumors").get_json()["rumors"][0]
    assert "real_name" not in feed
    assert "email" not in feed
    # reactions dict present and well-formed
    assert set(feed["reactions"].keys()) == VALID_KINDS
