"""Tests for the registry endpoints."""

import pytest
from fastapi.testclient import TestClient

from agenteazy.registry import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTEAZY_DB_PATH", str(tmp_path / "test.db"))
    # Re-import to pick up the new DB_PATH
    import agenteazy.registry as reg
    reg.DB_PATH = tmp_path / "test.db"
    return TestClient(app)


class TestAgentsByOwner:
    def test_returns_owned_agents(self, client):
        client.post("/registry/register", json={"name": "my-agent", "url": "http://fake", "owner_api_key": "ae_owner1"})
        client.post("/registry/register", json={"name": "other-agent", "url": "http://fake", "owner_api_key": "ae_owner2"})
        resp = client.get("/registry/agents-by-owner/ae_owner1")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        assert resp.json()["agents"][0]["name"] == "my-agent"

    def test_no_agents(self, client):
        resp = client.get("/registry/agents-by-owner/ae_nonexistent")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_key_not_leaked(self, client):
        client.post("/registry/register", json={"name": "secret-test", "url": "http://fake", "owner_api_key": "ae_secret"})
        resp = client.get("/registry/agents-by-owner/ae_secret")
        for agent in resp.json()["agents"]:
            assert "owner_api_key" not in agent
