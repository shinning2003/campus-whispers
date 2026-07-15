"""Shared pytest fixtures for Campus Whispers tests."""
import pytest
from app import create_app, init_db, hash_password


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"
    app = create_app({"TESTING": True, "DB_PATH": str(db_path)})
    # Make a known admin password for tests
    app.config["ADMIN_PASSWORD"] = "admin123"
    init_db(str(db_path))
    with app.test_client() as client:
        yield client
