"""Security headers must be present on every response (Helmet equivalent for Flask)."""
import pytest


def test_security_headers_present(client):
    r = client.get("/")
    h = r.headers
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "DENY"
    assert h.get("Referrer-Policy") == "no-referrer"
    assert "Content-Security-Policy" in h


def test_api_also_has_security_headers(client):
    r = client.get("/api/rumors")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
