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
    assert r.get_json()["reacted"] is True
    # toggle off
    r = client.post(f"/api/rumors/{rid}/react", json={"kind": "fire"})
    assert r.get_json()["reacted"] is False


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
    client.post(f"/api/rumors/{rid}/metoo")
    register_and_login(client, handle="bbb", email="b@x.com")
    client.post(f"/api/rumors/{rid}/metoo")
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
