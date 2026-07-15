"""Tests for the Campus Whispers anonymous rumor board."""
import json
import pytest
from app import create_app, init_db


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"
    app = create_app({"TESTING": True, "DB_PATH": str(db_path)})
    init_db(str(db_path))
    with app.test_client() as client:
        yield client


def test_post_rumor_anonymously_returns_id_and_text(client):
    """A poster can submit a rumor without any identity; it gets stored."""
    resp = client.post("/api/rumors", json={"text": "Rahul fell asleep in class again."})
    assert resp.status_code == 201
    data = resp.get_json()
    assert "id" in data
    assert data["text"] == "Rahul fell asleep in class again."
    assert data["created_at"]


def test_posted_rumor_appears_in_public_list(client):
    """The public feed shows rumors that were posted."""
    client.post("/api/rumors", json={"text": "Someone ate my lunch from the fridge."})
    resp = client.get("/api/rumors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["rumors"]) == 1
    assert data["rumors"][0]["text"] == "Someone ate my lunch from the fridge."
    # Anonymous: no author identity is ever exposed
    assert "author" not in data["rumors"][0]
    assert "ip" not in data["rumors"][0]


def test_empty_rumor_is_rejected(client):
    """Refuse blank/submissions with no real content."""
    resp = client.post("/api/rumors", json={"text": "   "})
    assert resp.status_code == 400
