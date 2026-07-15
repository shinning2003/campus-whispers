"""Served HTML uses semantic landmarks: header, main, footer."""
import pytest


def test_index_has_semantic_landmarks(client):
    html = client.get("/").data.decode()
    assert "<header" in html
    assert "<main" in html
    assert "<footer" in html


def test_admin_has_semantic_landmarks(client):
    html = client.get("/admin").data.decode()
    assert "<header" in html
    assert "<main" in html
    assert "<footer" in html
