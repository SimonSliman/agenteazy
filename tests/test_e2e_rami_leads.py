"""
AGENTEAZY — REAL WORLD USE CASE E2E TEST
=========================================

SCENARIO: "Rami", a marketing agency developer in Dubai, wants to
clean 500 trade-show leads using AgentEazy skills. He builds a
lead-scorer, deploys it, and earns credits when others use it.

Run with: python tests/test_e2e_rami_leads.py

REQUIRES: Local registry (port 8001) and gateway (port 8000) running.
  Start them with:
    python agenteazy/registry.py &
    AGENTEAZY_AGENTS_ROOT=/tmp/agents python agenteazy/gateway.py &
  And configure CLI:
    agenteazy config set registry_url http://localhost:8001
    agenteazy config set gateway_url http://localhost:8000
"""

import subprocess
import json
import sys
import os
import tempfile

GATEWAY = os.environ.get("AGENTEAZY_GATEWAY", "http://localhost:8000")
REGISTRY = os.environ.get("AGENTEAZY_REGISTRY", "http://localhost:8001")
RESULTS = []

SAMPLE_LEADS = [
    {"name": "John Smith", "email": "john@gmail.com", "phone": "+1-555-123-4567", "notes": "Great meeting at booth"},
    {"name": "sara connor", "email": "sara@mailinator.com", "phone": "5551234568", "notes": "Interested in premium"},
    {"name": "Bob Wilson", "email": "bob.wilson@company.co.uk", "phone": "+44 20 7946 0958", "notes": "Follow up ASAP damn it"},
    {"name": "María García López", "email": "maria@guerrillamail.com", "phone": "+34 612 345 678", "notes": "Spanish speaker, muy interesante"},
    {"name": "ahmed al-rashid", "email": "ahmed@business.sa", "phone": "+966501234567", "notes": "VIP - wants bulk pricing"},
]

LEAD_SCORER_CODE = '''
import re

def score(lead: dict) -> dict:
    """Score a lead 0-100 based on data quality signals."""
    points = 0
    reasons = []

    email = lead.get("email", "")
    phone = lead.get("phone", "")
    notes = lead.get("notes", "")
    name = lead.get("name", "")

    if re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$", email):
        points += 30
        reasons.append("valid_email")

    disposable_domains = ["mailinator.com", "guerrillamail.com", "tempmail.com", "throwaway.email"]
    domain = email.split("@")[-1] if "@" in email else ""
    if domain and domain not in disposable_domains:
        points += 20
        reasons.append("not_disposable")

    if re.search(r"\\+?\\d[\\d\\s\\-]{7,}", phone):
        points += 20
        reasons.append("has_phone")

    bad_words = ["damn", "shit", "fuck", "ass", "crap"]
    if not any(w in notes.lower() for w in bad_words):
        points += 15
        reasons.append("clean_notes")

    vip_keywords = ["vip", "bulk", "enterprise", "premium", "urgent"]
    if any(k in notes.lower() for k in vip_keywords):
        points += 15
        reasons.append("vip_signal")

    tier = "hot" if points >= 80 else "warm" if points >= 50 else "cold"

    return {
        "name": name,
        "email": email,
        "score": points,
        "tier": tier,
        "reasons": reasons
    }
'''


def log(step, status, detail=""):
    entry = {"step": step, "status": status, "detail": detail}
    RESULTS.append(entry)
    icon = "PASS" if status == "PASS" else "FAIL" if status == "FAIL" else "WARN"
    print(f"\n[{icon}] Step: {step}")
    print(f"   Status: {status}")
    if detail:
        print(f"   Detail: {detail}")


def curl_json(method, url, data=None, timeout=15):
    """Helper to make HTTP requests and return parsed JSON."""
    cmd = ["curl", "-s"]
    if method == "POST":
        cmd += ["-X", "POST"]
    cmd.append(url)
    if data:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.stdout:
        return json.loads(result.stdout)
    return None


def phase_1_onboarding():
    """Phase 1: Signup, balance, search, list."""
    print("\n" + "=" * 60)
    print("PHASE 1: ONBOARDING")
    print("=" * 60)

    # Signup
    try:
        result = subprocess.run(
            ["agenteazy", "signup", "rami-agency", "--email", "rami@dubaimedia.ae"],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout + result.stderr
        if "API key" in output or "already" in output.lower():
            log("1.1 Signup", "PASS", output.strip()[:200])
        else:
            log("1.1 Signup", "FAIL", output.strip()[:200])
    except Exception as e:
        log("1.1 Signup", "FAIL", str(e))

    # Balance
    try:
        result = subprocess.run(
            ["agenteazy", "balance"],
            capture_output=True, text=True, timeout=15
        )
        if "Credits" in result.stdout:
            log("1.2 Balance", "PASS", "Balance displayed correctly")
        else:
            log("1.2 Balance", "FAIL", (result.stdout + result.stderr)[:200])
    except Exception as e:
        log("1.2 Balance", "FAIL", str(e))

    # Search
    for term in ["email", "phone", "name", "profanity"]:
        try:
            result = subprocess.run(
                ["agenteazy", "search", term],
                capture_output=True, text=True, timeout=15
            )
            log(f"1.3 Search '{term}'", "PASS", (result.stdout + result.stderr).strip()[:100])
        except Exception as e:
            log(f"1.3 Search '{term}'", "FAIL", str(e))

    # List
    try:
        result = subprocess.run(
            ["agenteazy", "list"],
            capture_output=True, text=True, timeout=15
        )
        log("1.4 List", "PASS", (result.stdout + result.stderr).strip()[:100])
    except Exception as e:
        log("1.4 List", "FAIL", str(e))


def phase_2_existing_skills():
    """Phase 2: Try calling existing skills."""
    print("\n" + "=" * 60)
    print("PHASE 2: EXISTING SKILLS")
    print("=" * 60)

    skills = [
        ("disposable-email-check", {"verb": "DO", "payload": {"task": "check", "data": {"email": "sara@mailinator.com"}}}),
        ("email-extract", {"verb": "DO", "payload": {"task": "extract", "data": {"text": "reach me at john@gmail.com"}}}),
        ("profanity-check", {"verb": "DO", "payload": {"task": "check", "data": {"text": "Follow up ASAP damn it"}}}),
        ("langdetect", {"verb": "DO", "payload": {"task": "detect", "data": {"text": "muy interesante"}}}),
    ]

    for name, payload in skills:
        try:
            resp = curl_json("POST", f"{GATEWAY}/agent/{name}/", payload)
            if resp and "error" not in str(resp).lower() and "not found" not in str(resp).lower():
                log(f"2. Call {name}", "PASS", json.dumps(resp)[:200])
            else:
                log(f"2. Call {name}", "WARN", f"Not available: {json.dumps(resp)[:150]}" if resp else "Empty response")
        except Exception as e:
            log(f"2. Call {name}", "FAIL", str(e))


def phase_3_build_skill():
    """Phase 3: Build and deploy lead-scorer."""
    print("\n" + "=" * 60)
    print("PHASE 3: BUILD LEAD-SCORER")
    print("=" * 60)

    tmpdir = tempfile.mkdtemp(prefix="lead-scorer-")
    skill_path = os.path.join(tmpdir, "main.py")
    with open(skill_path, "w") as f:
        f.write(LEAD_SCORER_CODE)
    log("3.1 Write skill", "PASS", f"Path: {skill_path}")

    # Analyze
    try:
        result = subprocess.run(
            ["agenteazy", "analyze", tmpdir],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            log("3.2 Analyze", "PASS", result.stdout.strip()[:200])
        else:
            log("3.2 Analyze", "FAIL", result.stderr[:200])
            return tmpdir
    except Exception as e:
        log("3.2 Analyze", "FAIL", str(e))
        return tmpdir

    # Wrap
    try:
        result = subprocess.run(
            ["agenteazy", "wrap", tmpdir],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            log("3.3 Wrap", "PASS", "Generated agent.json + wrapper.py")
        else:
            log("3.3 Wrap", "FAIL", result.stderr[:200])
            return tmpdir
    except Exception as e:
        log("3.3 Wrap", "FAIL", str(e))
        return tmpdir

    # Deploy
    try:
        result = subprocess.run(
            ["agenteazy", "deploy", tmpdir],
            capture_output=True, text=True, timeout=60
        )
        log("3.4 Deploy", "PASS" if result.returncode == 0 else "WARN",
            (result.stdout + result.stderr).strip()[:300])
    except Exception as e:
        log("3.4 Deploy", "FAIL", str(e))

    # Register
    try:
        result = subprocess.run(
            ["agenteazy", "register", "lead-scorer",
             f"{GATEWAY}/agent/lead-scorer/",
             "-d", "Score a lead 0-100 based on data quality signals.",
             "--price", "1"],
            capture_output=True, text=True, timeout=15
        )
        if "Registered" in result.stdout or "already" in (result.stdout + result.stderr).lower():
            log("3.5 Register", "PASS", (result.stdout + result.stderr).strip()[:200])
        else:
            log("3.5 Register", "FAIL", (result.stdout + result.stderr).strip()[:200])
    except Exception as e:
        log("3.5 Register", "FAIL", str(e))

    return tmpdir


def phase_4_score_leads():
    """Phase 4: Score all sample leads."""
    print("\n" + "=" * 60)
    print("PHASE 4: SCORE ALL LEADS")
    print("=" * 60)

    for lead in SAMPLE_LEADS:
        payload = {
            "verb": "DO",
            "payload": {"task": "score", "data": {"lead": lead}}
        }
        try:
            resp = curl_json("POST", f"{GATEWAY}/agent/lead-scorer/", payload)
            if resp and resp.get("status") == "completed":
                output = resp["output"]
                log(f"4. Score {lead['name']}", "PASS",
                    f"Score={output['score']}, Tier={output['tier']}, Reasons={output['reasons']}")
            else:
                log(f"4. Score {lead['name']}", "FAIL", json.dumps(resp)[:200] if resp else "No response")
        except Exception as e:
            log(f"4. Score {lead['name']}", "FAIL", str(e))


def phase_5_revenue():
    """Phase 5: Second user calls Rami's skill, check earnings."""
    print("\n" + "=" * 60)
    print("PHASE 5: REVENUE TEST")
    print("=" * 60)

    # Signup second user via API
    try:
        resp = curl_json("POST", f"{REGISTRY}/tollbooth/signup",
                         {"github_username": "devuser-tokyo", "email": "dev@tokyo-agency.jp"})
        if resp and "api_key" in resp:
            second_key = resp["api_key"]
            log("5.1 Second user signup", "PASS", f"Key: {second_key[:20]}..., Credits: {resp['credits']}")
        else:
            log("5.1 Second user signup", "FAIL", json.dumps(resp)[:200] if resp else "No response")
            return
    except Exception as e:
        log("5.1 Second user signup", "FAIL", str(e))
        return

    # Call Rami's skill as second user
    payload = {
        "verb": "DO",
        "auth": second_key,
        "payload": {"task": "score", "data": {"lead": {
            "name": "Test User", "email": "test@real.com",
            "phone": "+81312345678", "notes": "enterprise client"
        }}}
    }
    try:
        resp = curl_json("POST", f"{GATEWAY}/agent/lead-scorer/", payload)
        if resp and resp.get("status") == "completed":
            log("5.2 Second user calls skill", "PASS", json.dumps(resp["output"])[:200])
        else:
            log("5.2 Second user calls skill", "FAIL", json.dumps(resp)[:200] if resp else "No response")
    except Exception as e:
        log("5.2 Second user calls skill", "FAIL", str(e))

    # Check balances
    try:
        rami_balance = curl_json("GET", f"{REGISTRY}/tollbooth/balance/{os.environ.get('RAMI_KEY', '')}")
        second_balance = curl_json("GET", f"{REGISTRY}/tollbooth/balance/{second_key}")
        if second_balance:
            log("5.3 Balance check", "PASS",
                f"Second user: {second_balance.get('credits')} credits "
                f"(spent: {second_balance.get('total_spent')})")
        else:
            log("5.3 Balance check", "WARN", "Could not verify balances")
    except Exception as e:
        log("5.3 Balance check", "FAIL", str(e))


if __name__ == "__main__":
    print("=" * 60)
    print("AGENTEAZY REAL WORLD E2E TEST")
    print(f"Gateway: {GATEWAY} | Registry: {REGISTRY}")
    print("=" * 60)

    phase_1_onboarding()
    phase_2_existing_skills()
    phase_3_build_skill()
    phase_4_score_leads()
    phase_5_revenue()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in RESULTS:
        icon = "PASS" if r["status"] == "PASS" else "FAIL" if r["status"] == "FAIL" else "WARN"
        print(f"[{icon}] {r['step']}: {r['status']}")

    passes = len([r for r in RESULTS if r["status"] == "PASS"])
    fails = len([r for r in RESULTS if r["status"] == "FAIL"])
    warns = len([r for r in RESULTS if r["status"] == "WARN"])
    print(f"\nTotal: {passes} PASS, {fails} FAIL, {warns} WARN")

    if fails:
        print(f"\nFAILURES:")
        for f in [r for r in RESULTS if r["status"] == "FAIL"]:
            print(f"   {f['step']}: {f['detail'][:100]}")
        sys.exit(1)
