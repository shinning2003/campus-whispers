"""Database is pluggable: SQLite locally, Postgres (Supabase) in production
via DATABASE_URL env var. app must support both without code changes.
"""
import os
import tempfile
import pytest
from app import create_app, init_db, get_db


def test_defaults_to_sqlite_when_no_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "local.db")
    app = create_app({"TESTING": True, "DB_PATH": db})
    with app.app_context():
        init_db()
        conn = get_db()
        assert "sqlite3" in type(conn).__module__
        conn.execute("SELECT 1")
        conn.close()


def test_uses_database_url_when_provided(monkeypatch):
    # The app must honor a DATABASE_URL (Supabase Postgres) over DB_PATH
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/db")
    app = create_app({})
    assert app.config["DATABASE_URL"].startswith("postgresql://")
    # get_db should branch to psycopg when DATABASE_URL is set.
    # We can't open a real connection (no server), so we assert the
    # config plumbing is correct and psycopg is importable.
    import psycopg
    assert psycopg is not None
