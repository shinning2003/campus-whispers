"""Shared pytest fixtures for Campus Whispers tests."""
import pytest
from app import create_app, init_db, get_db


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"
    app = create_app({"TESTING": True, "DB_PATH": str(db_path)})
    # Make a known admin password for tests
    app.config["ADMIN_PASSWORD"] = "admin123"
    with app.app_context():
        # Clean-slate schema each test so runs against a shared Postgres
        # (Supabase) don't collide on UNIQUE email/handle from prior runs.
        conn = get_db()
        conn.execute("DROP TABLE IF EXISTS rumors")
        conn.execute("DROP TABLE IF EXISTS users")
        conn.commit()
        conn.close()
        init_db()
    with app.test_client() as client:
        yield client
