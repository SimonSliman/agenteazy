"""Deployer - Local deployment and testing for wrapped agents."""

import json
import os
import signal
import subprocess
import sys
import urllib.error
import urllib.request


def deploy_local(output_dir: str, port: int = 8000) -> None:
    """
    Deploy a wrapped agent locally by running its wrapper.py.

    Checks that output_dir contains wrapper.py and agent.json,
    prints endpoint URLs, then starts the server and blocks until Ctrl+C.
    """
    output_dir = os.path.abspath(output_dir)
    wrapper_path = os.path.join(output_dir, "wrapper.py")
    agent_json_path = os.path.join(output_dir, "agent.json")

    if not os.path.isfile(wrapper_path):
        raise FileNotFoundError(f"wrapper.py not found in {output_dir}")
    if not os.path.isfile(agent_json_path):
        raise FileNotFoundError(f"agent.json not found in {output_dir}")

    base_url = f"http://localhost:{port}"
    print(f"\nStarting agent server on {base_url}")
    print(f"  GET  {base_url}/")
    print(f"  GET  {base_url}/health")
    print(f"  POST {base_url}/ask")
    print(f"  POST {base_url}/do")
    print(f"  GET  {base_url}/.well-known/agent.json")
    print(f"\nPress Ctrl+C to stop.\n")

    env = os.environ.copy()
    env["AGENTEAZY_PORT"] = str(port)

    proc = subprocess.Popen(
        [sys.executable, "wrapper.py"],
        cwd=output_dir,
        env=env,
    )

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        print("Server stopped.")


def test_agent(base_url: str = "http://localhost:8000") -> dict:
    """
    Test all 5 endpoints of a deployed agent.

    Uses only urllib (no extra deps). Returns a dict of results per endpoint.
    """
    base_url = base_url.rstrip("/")
    results = {}

    # Helper for GET requests
    def _get(path: str) -> dict:
        url = f"{base_url}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    # Helper for POST requests
    def _post(path: str, data: dict) -> dict:
        url = f"{base_url}{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    # 1. GET / - check status is "active" or has name
    print(f"\nTesting {base_url} endpoints:\n")
    try:
        data = _get("/")
        has_name = "name" in data
        has_verbs = "verbs" in data
        passed = has_name and has_verbs
        results["GET /"] = {"passed": passed, "data": data}
        status = "PASS" if passed else "FAIL"
        print(f"  {status}  GET /  — name={data.get('name')}, verbs={data.get('verbs')}")
    except Exception as e:
        results["GET /"] = {"passed": False, "error": str(e)}
        print(f"  FAIL  GET /  — {e}")

    # 2. GET /health - check healthy
    try:
        data = _get("/health")
        passed = data.get("status") == "ok"
        results["GET /health"] = {"passed": passed, "data": data}
        status = "PASS" if passed else "FAIL"
        print(f"  {status}  GET /health  — status={data.get('status')}")
    except Exception as e:
        results["GET /health"] = {"passed": False, "error": str(e)}
        print(f"  FAIL  GET /health  — {e}")

    # 3. POST /ask - check it returns verbs
    try:
        data = _post("/ask", {})
        has_verbs = "capabilities" in data and "verbs" in data.get("capabilities", {})
        results["POST /ask"] = {"passed": has_verbs, "data": data}
        status = "PASS" if has_verbs else "FAIL"
        print(f"  {status}  POST /ask  — capabilities={list(data.get('capabilities', {}).keys())}")
    except Exception as e:
        results["POST /ask"] = {"passed": False, "error": str(e)}
        print(f"  FAIL  POST /ask  — {e}")

    # 4. POST /do - send a test task
    try:
        data = _post("/do", {"task": "test"})
        has_status = "status" in data
        results["POST /do"] = {"passed": has_status, "data": data}
        status = "PASS" if has_status else "FAIL"
        print(f"  {status}  POST /do  — status={data.get('status')}")
    except Exception as e:
        results["POST /do"] = {"passed": False, "error": str(e)}
        print(f"  FAIL  POST /do  — {e}")

    # 5. GET /.well-known/agent.json - check name and entry
    try:
        data = _get("/.well-known/agent.json")
        has_name = "name" in data
        has_entry = "entry" in data
        passed = has_name and has_entry
        results["GET /.well-known/agent.json"] = {"passed": passed, "data": data}
        status = "PASS" if passed else "FAIL"
        print(f"  {status}  GET /.well-known/agent.json  — name={data.get('name')}")
    except Exception as e:
        results["GET /.well-known/agent.json"] = {"passed": False, "error": str(e)}
        print(f"  FAIL  GET /.well-known/agent.json  — {e}")

    # Summary
    total = len(results)
    passed_count = sum(1 for r in results.values() if r["passed"])
    print(f"\n  {passed_count}/{total} endpoints passed.\n")

    return results
