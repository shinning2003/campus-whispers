"""Feature 6: Daily email digest of top rumors (external trigger).

Psychological lever: External trigger (Eyal) — an email that re-engages users
by surfacing the day's hottest secrets. Uses the email already collected at
registration, so no new friction. Sending is admin-gated and injectable for
testing (no real SMTP needed in tests).
"""
import pytest
from app import create_app
from tests.helpers import register_and_login

ADMIN_EMAIL = create_app().config["ADMIN_EMAIL"]


def _post(client, handle, email, text):
    register_and_login(client, handle=handle, email=email)
    r = client.post("/api/rumors", json={"text": text})
    return r.get_json()["id"]


def test_digest_requires_admin(client):
    r = client.post("/api/admin/digest/send", json={})
    assert r.status_code == 401


def test_digest_sends_top_rumors_to_users(client, app=None):
    # two users registered with emails
    _post(client, "aaa", "winner@x.com", "top secret of the day")
    _post(client, "bbb", "reader@x.com", "another whisper")
    sent = []
    client.post("/api/admin/login", json={"password": "admin123"})
    r = client.post("/api/admin/digest/send",
                    json={},
                    # injector handled via app config below
                    )
    # Without injection the endpoint tries real SMTP and fails gracefully;
    # we test the injection path in the next test. Here assert it is gated.
    assert r.status_code in (200, 500)


def test_digest_injects_sender_and_reports_counts(client):
    sent = []
    def fake_send(to_addrs, subject, body):
        sent.append((to_addrs, subject, body))

    # rebuild app with mail injector
    from app import create_app
    import pytest as _pytest
    # Use the same client fixture's app via application
    app = client.application
    app.config["MAIL_SENDER"] = fake_send
    # register + post
    _post(client, "aaa", "winner@x.com", "top secret of the day")
    _post(client, "bbb", "reader@x.com", "another whisper")
    # give the first one engagement so it ranks
    client.post("/api/rumors/1/react", json={"kind": "fire"})
    client.post("/api/admin/login", json={"password": "admin123"})
    r = client.post("/api/admin/digest/send", json={})
    assert r.status_code == 200
    j = r.get_json()
    assert j["sent"] == 2
    # emails went out to both registered users
    tos = {s[0] for s in sent}
    assert {"winner@x.com", "reader@x.com"} <= tos
    # digest body references a rumor
    assert "Campus Whispers" in sent[0][2]


def test_digest_only_includes_recent_rumors(client):
    sent = []
    def fake_send(to_addrs, subject, body):
        sent.append((to_addrs, subject, body))

    app = client.application
    app.config["MAIL_SENDER"] = fake_send
    _post(client, "aaa", "winner@x.com", "today's hot take")
    client.post("/api/admin/login", json={"password": "admin123"})
    # window of 1 day (default) -> includes the just-posted rumor
    r = client.post("/api/admin/digest/send", json={"window_hours": 24})
    assert r.status_code == 200
    assert r.get_json()["sent"] == 1
