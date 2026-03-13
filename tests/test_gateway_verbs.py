"""Test all verb handlers in gateway.py without Modal or HTTP server.

We mock Modal dependencies and create a fake agent on disk, then call
_handle_verb directly for each verb to verify no crashes.
"""

import json
import os
import sys
import tempfile
import textwrap
from unittest import mock

# Patch modal before importing gateway
sys.modules.setdefault("modal", mock.MagicMock())

import pytest

# Now safe to import gateway
from agenteazy.gateway import (
    VALID_VERBS,
    _handle_verb,
    _agent_configs,
    _agent_modules,
    _agent_context,
    _call_log,
    _load_agent_config,
    _load_agent_func,
    validate_verb,
    app,
)


@pytest.fixture(autouse=True)
def fake_agent(tmp_path, monkeypatch):
    """Create a minimal agent on disk and point gateway at it."""
    import agenteazy.gateway as gw

    agent_dir = tmp_path / "test-agent"
    repo_dir = agent_dir / "repo"
    repo_dir.mkdir(parents=True)

    # agent.json
    config = {
        "name": "test-agent",
        "description": "A test agent",
        "version": "0.1.0",
        "verbs": ["ASK", "DO"],
        "entry": {
            "file": "main.py",
            "function": "convert",
            "args": ["text", "uppercase"],
        },
    }
    (agent_dir / "agent.json").write_text(json.dumps(config))

    # main.py with a simple function
    (repo_dir / "main.py").write_text(
        textwrap.dedent("""\
        def convert(text="hello", uppercase=False):
            \"\"\"Convert text.\"\"\"
            if uppercase:
                return text.upper()
            return text
        """)
    )

    monkeypatch.setattr(gw, "AGENTS_ROOT", str(tmp_path))

    # Clear caches between tests
    _agent_configs.clear()
    _agent_modules.clear()
    _agent_context.clear()
    _call_log.clear()

    yield


class TestValidateVerb:
    def test_all_valid(self):
        for v in VALID_VERBS:
            assert validate_verb(v)

    def test_lowercase(self):
        assert validate_verb("do")

    def test_invalid(self):
        assert not validate_verb("EXPLODE")


class TestDO:
    def test_do_with_data_key(self):
        result = _handle_verb("test-agent", "DO", {
            "task": "convert",
            "data": {"text": "hello", "uppercase": True},
        })
        assert result["status"] == "completed"
        assert result["output"] == "HELLO"

    def test_do_with_input_key(self):
        result = _handle_verb("test-agent", "DO", {
            "task": "convert",
            "input": {"text": "world", "uppercase": True},
        })
        assert result["status"] == "completed"
        assert result["output"] == "WORLD"

    def test_do_empty_payload(self):
        result = _handle_verb("test-agent", "DO", {})
        assert result["status"] == "completed"
        # default args: text="hello", uppercase=False => "hello"

    def test_do_data_takes_priority_over_input(self):
        result = _handle_verb("test-agent", "DO", {
            "data": {"text": "from_data", "uppercase": False},
            "input": {"text": "from_input", "uppercase": False},
        })
        assert result["status"] == "completed"
        assert result["output"] == "from_data"


class TestASK:
    def test_ask_returns_capabilities(self):
        result = _handle_verb("test-agent", "ASK", {})
        assert result["name"] == "test-agent"
        assert "capabilities" in result
        assert result["capabilities"]["args"] == ["text", "uppercase"]
        assert result["capabilities"]["docstring"] is not None


class TestFIND:
    def test_find_no_registry(self, monkeypatch):
        monkeypatch.delenv("AGENTEAZY_REGISTRY_URL", raising=False)
        result = _handle_verb("test-agent", "FIND", {"data": "something"})
        assert result["status"] == "failed"
        assert "registry" in result["error"].lower()


class TestSHARE:
    def test_share_stores_context(self):
        result = _handle_verb("test-agent", "SHARE", {
            "data": {"key1": "value1", "key2": "value2"},
        })
        assert result["status"] == "received"
        assert "key1" in result["context_keys"]
        assert "key2" in result["context_keys"]
        assert _agent_context["test-agent"]["key1"] == "value1"

    def test_share_with_input_key(self):
        result = _handle_verb("test-agent", "SHARE", {
            "input": {"foo": "bar"},
        })
        assert result["status"] == "received"
        assert "foo" in result["context_keys"]


class TestREPORT:
    def test_report_returns_log(self):
        # Generate some log entries first
        _handle_verb("test-agent", "ASK", {})
        from agenteazy.gateway import _log_call
        _log_call("test-agent", "ASK", "success")

        result = _handle_verb("test-agent", "REPORT", {})
        assert result["status"] == "completed"
        assert "recent_calls" in result
        assert "config" in result


class TestPlaceholderVerbs:
    @pytest.mark.parametrize("verb", ["PAY", "WATCH", "STOP", "TRUST", "LEARN"])
    def test_placeholder_verbs(self, verb):
        result = _handle_verb("test-agent", verb, {})
        assert result["status"] == "acknowledged"
        assert "message" in result


class TestInvalidVerb:
    def test_invalid_verb_caught_by_validate(self):
        assert not validate_verb("INVALID")


class TestUniversalEndpoint:
    """Test the full endpoint via TestClient."""

    def test_invalid_verb_returns_400(self):
        from starlette.testclient import TestClient
        # Patch _refresh_volume to no-op
        with mock.patch("agenteazy.gateway._refresh_volume"):
            client = TestClient(app)
            resp = client.post("/agent/test-agent/", json={"verb": "INVALID"})
            assert resp.status_code == 400
            data = resp.json()
            assert "valid_verbs" in data
            assert data["valid_verbs"] == VALID_VERBS

    def test_do_via_endpoint(self):
        from starlette.testclient import TestClient
        with mock.patch("agenteazy.gateway._refresh_volume"):
            client = TestClient(app)
            resp = client.post("/agent/test-agent/", json={
                "verb": "DO",
                "payload": {"task": "convert", "data": {"text": "hi", "uppercase": True}},
            })
            assert resp.status_code == 200
            assert resp.json()["output"] == "HI"

    def test_do_via_endpoint_input_format(self):
        from starlette.testclient import TestClient
        with mock.patch("agenteazy.gateway._refresh_volume"):
            client = TestClient(app)
            resp = client.post("/agent/test-agent/", json={
                "verb": "DO",
                "payload": {"task": "convert", "input": {"text": "hey", "uppercase": True}},
            })
            assert resp.status_code == 200
            assert resp.json()["output"] == "HEY"
