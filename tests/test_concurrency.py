"""Concurrency: parallel reads must not lock out writes (WAL + timeout)."""
import threading

import pytest
from tests.helpers import register_and_login


def test_concurrent_reads_dont_block_a_write(client):
    register_and_login(client, handle="usr1", email="e@x.com")
    # Simulate a long-lived reader holding a connection while a write happens
    stop = False

    def reader():
        while not stop:
            try:
                client.get("/api/rumors")
            except Exception:
                return

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        for _ in range(10):
            r = client.post("/api/rumors", json={"text": "concurrent post"})
            assert r.status_code == 201, r.get_json()
    finally:
        stop = True
        t.join(timeout=2)
