"""
TEST PLAN — AgentEazy Real World Loop
=====================================

SCENARIO: Carlos, a freelance dev in São Paulo, wants to monetize
a simple email validation function via AgentEazy.

The test simulates:
1. Infrastructure health check
2. Registry listing (what's already there)
3. New skill deployment
4. Calling the skill
5. Checking credit flow (payer → payee)

Each step logs PASS/FAIL with details.
"""

import subprocess
import json
import time
import sys

# ============ CONFIG ============
GATEWAY_URL = "https://simondusable--agenteazy-gateway-serve.modal.run"
REGISTRY_URL = "https://simondusable--agenteazy-registry-serve.modal.run"
RESULTS = []

def log(step, status, detail=""):
    entry = {"step": step, "status": status, "detail": detail}
    RESULTS.append(entry)
    icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
    print(f"\n{icon} Step: {step}")
    print(f"   Status: {status}")
    if detail:
        print(f"   Detail: {detail}")

# ============ TESTS ============

def test_1_gateway_health():
    """Can we reach the gateway?"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"{GATEWAY_URL}/"],
            capture_output=True, text=True, timeout=15
        )
        code = result.stdout.strip()
        if code in ["200", "404", "405"]:
            log("1. Gateway Health", "PASS", f"HTTP {code} — gateway is alive")
        else:
            log("1. Gateway Health", "FAIL", f"HTTP {code}")
    except Exception as e:
        log("1. Gateway Health", "FAIL", str(e))

def test_2_registry_list():
    """What agents are registered?"""
    try:
        result = subprocess.run(
            ["curl", "-s", f"{REGISTRY_URL}/agents"],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(result.stdout)
        if isinstance(data, list):
            skills = [a for a in data if a.get("type") == "skill" or "skill" in str(a)]
            agents = [a for a in data if a.get("type") == "agent" or "agent" in str(a)]
            log("2. Registry List", "PASS",
                f"Total: {len(data)} | Names: {[a.get('name','?') for a in data[:10]]}...")
        elif isinstance(data, dict) and "agents" in data:
            agents_list = data["agents"]
            log("2. Registry List", "PASS",
                f"Total: {len(agents_list)} | Names: {[a.get('name','?') for a in agents_list[:10]]}...")
        else:
            log("2. Registry List", "WARN", f"Unexpected format: {str(data)[:200]}")
    except json.JSONDecodeError:
        log("2. Registry List", "FAIL", f"Not JSON: {result.stdout[:200]}")
    except Exception as e:
        log("2. Registry List", "FAIL", str(e))

def test_3_call_existing_skill():
    """Call an existing skill in the registry"""
    test_payloads = [
        ("test-gateway-repo", {"verb": "DO", "payload": {"task": "convert", "data": {"text": "hello world", "uppercase": True}}}),
        ("password-gen", {"verb": "DO", "payload": {"task": "generate", "data": {"length": 16}}}),
        ("slugify", {"verb": "DO", "payload": {"task": "slugify", "data": {"text": "Hello World Test"}}}),
    ]
    for name, payload in test_payloads:
        try:
            result = subprocess.run(
                ["curl", "-s", "-X", "POST",
                 f"{GATEWAY_URL}/agent/{name}/",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps(payload)],
                capture_output=True, text=True, timeout=15
            )
            if result.stdout:
                log(f"3. Call Skill: {name}", "PASS", f"Response: {result.stdout[:200]}")
                return  # One success is enough
            else:
                log(f"3. Call Skill: {name}", "FAIL", "Empty response")
        except Exception as e:
            log(f"3. Call Skill: {name}", "FAIL", str(e))

def test_4_check_tollbooth():
    """Can we check credit balance?"""
    endpoints = [
        f"{REGISTRY_URL}/balance",
        f"{REGISTRY_URL}/credits",
        f"{GATEWAY_URL}/tollbooth/balance",
    ]
    for ep in endpoints:
        try:
            result = subprocess.run(
                ["curl", "-s", ep],
                capture_output=True, text=True, timeout=10
            )
            if result.stdout and "error" not in result.stdout.lower():
                log(f"4. TollBooth Check: {ep}", "PASS", result.stdout[:200])
                return
        except:
            pass
    log("4. TollBooth Check", "WARN",
        "Could not find working balance endpoint. Check docs for auth requirements.")

def test_5_deploy_new_skill():
    """Deploy a brand new skill via CLI"""
    skill_code = '''
def validate_email(email: str) -> dict:
    """Validate if an email address is properly formatted."""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\\\.[a-zA-Z]{2,}$'
    is_valid = bool(re.match(pattern, email))
    return {
        "email": email,
        "valid": is_valid,
        "reason": "valid format" if is_valid else "invalid format"
    }
'''
    import tempfile, os
    tmpdir = tempfile.mkdtemp(prefix="agenteazy-test-")
    skill_path = os.path.join(tmpdir, "main.py")
    with open(skill_path, "w") as f:
        f.write(skill_code)

    log("5a. Skill Written", "PASS", f"Path: {skill_path}")

    # Try agenteazy analyze
    try:
        result = subprocess.run(
            ["agenteazy", "analyze", tmpdir],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            log("5b. Analyze", "PASS", result.stdout[:200])
        else:
            log("5b. Analyze", "FAIL", f"stderr: {result.stderr[:200]}")
            return
    except FileNotFoundError:
        log("5b. Analyze", "FAIL",
            "agenteazy CLI not found. Install from repo: pip install -e .")
        return
    except Exception as e:
        log("5b. Analyze", "FAIL", str(e))
        return

    # Try agenteazy wrap
    try:
        result = subprocess.run(
            ["agenteazy", "wrap", tmpdir],
            capture_output=True, text=True, timeout=30
        )
        log("5c. Wrap", "PASS" if result.returncode == 0 else "FAIL",
            (result.stdout or result.stderr)[:200])
    except Exception as e:
        log("5c. Wrap", "FAIL", str(e))
        return

    # Try agenteazy deploy
    try:
        result = subprocess.run(
            ["agenteazy", "deploy", tmpdir],
            capture_output=True, text=True, timeout=60
        )
        log("5d. Deploy", "PASS" if result.returncode == 0 else "FAIL",
            (result.stdout or result.stderr)[:300])
    except Exception as e:
        log("5d. Deploy", "FAIL", str(e))

def test_6_call_new_skill():
    """Call the newly deployed skill"""
    payload = {
        "verb": "DO",
        "payload": {
            "task": "validate_email",
            "data": {"email": "test@example.com"}
        }
    }
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST",
             f"{GATEWAY_URL}/agent/validate-email/",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=15
        )
        if result.stdout:
            log("6. Call New Skill", "PASS", f"Response: {result.stdout[:200]}")
        else:
            log("6. Call New Skill", "FAIL", "Empty response")
    except Exception as e:
        log("6. Call New Skill", "FAIL", str(e))

# ============ RUN ALL ============

if __name__ == "__main__":
    print("=" * 60)
    print("AGENTEAZY END-TO-END TEST")
    print("=" * 60)

    test_1_gateway_health()
    test_2_registry_list()
    test_3_call_existing_skill()
    test_4_check_tollbooth()
    test_5_deploy_new_skill()
    test_6_call_new_skill()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in RESULTS:
        icon = "✅" if r["status"] == "PASS" else "❌" if r["status"] == "FAIL" else "⚠️"
        print(f"{icon} {r['step']}: {r['status']}")

    fails = [r for r in RESULTS if r["status"] == "FAIL"]
    if fails:
        print(f"\n🚨 {len(fails)} FAILURES — fix these before inviting external devs:")
        for f in fails:
            print(f"   → {f['step']}: {f['detail'][:100]}")
    else:
        print("\n🎉 All tests passed. Ready for external developer test.")
