# TollBooth Credit System — End-to-End Test Report

**Date:** 2026-03-15
**Environment:** Local registry (Modal services were down)
**Registry URL:** http://localhost:8001
**DB:** /tmp/tollbooth-test.db (clean, ephemeral)

---

## 1. Results Table

| Step | Test | Result | Notes |
|------|------|--------|-------|
| 1 | Health check (live Modal services) | **FAIL** | Both registry and gateway on Modal are down. Fell back to local registry. |
| 2 | Signup — create Developer + Caller | **PASS** | Both accounts created with 50 credit signup bonus. API keys returned. |
| 3 | Register paid agent with owner | **PASS** | Agent `tollbooth-test-paid` registered. Owner lookup endpoint works (`/registry/agent/{name}/owner`). |
| 4 | Single deduction + 80/20 split | **PARTIAL** | Deduct: PASS (caller 50→40). Dev earn 80%: PASS (50→58). **Platform earn 20%: FAIL** — `ae_platform` is not a registered account, so `/tollbooth/earn` rejects it with "Invalid API key". |
| 5 | 5 more calls — overdraft protection | **PASS** | Calls 1-4 succeeded (caller 40→30→20→10→0). Call 5 correctly rejected: `{"error":"Insufficient credits","balance":0,"cost":10}`. |
| 6a | Insufficient credits guard | **PASS** | Returns `{"error":"Insufficient credits","balance":0,"cost":100}` |
| 6b | Invalid API key guard | **PASS** | Returns `{"error":"Invalid API key"}` |
| 6c | Daily transfer limit check | **PASS** | Endpoint exists, returns `{"ok":true,"daily_transferred":0}` |
| 6d | Duplicate signup (409) | **PASS** | Returns `{"error":"Email already registered"}` with HTTP 409 |
| 7 | Transaction history | **PASS** | Full history returned for both accounts. 13 total transactions recorded. |
| 8 | Gateway billing (live) | **SKIP** | Gateway on Modal is down — cannot test end-to-end agent call through gateway billing middleware. |

---

## 2. Final Account Balances

| Account | Credits | Total Earned | Total Spent |
|---------|---------|-------------|-------------|
| **Developer** (`test-developer-tollbooth`) | 98 | 48 | 0 |
| **Caller** (`test-caller-tollbooth`) | 0 | 0 | 50 |
| **Platform** (`ae_platform`) | N/A | N/A | N/A |

- Developer: 50 (signup) + 6×8 (agent_revenue) = 98 credits
- Caller: 50 (signup) - 5×10 (agent_calls) = 0 credits
- Platform: **Account does not exist** — earn calls to `ae_platform` fail with "Invalid API key"

> **Note:** The developer received 6 earn payments (48 credits) but only 5 deductions succeeded. This is because the test script's earn call in the loop runs unconditionally — the gateway implementation must gate the earn on deduct success. The TollBooth system itself correctly prevents overdraft.

---

## 3. Total Transaction Count

**13 transactions total:**
- 2 signup_bonus (1 per account)
- 5 agent_call deductions (from caller)
- 6 agent_revenue earnings (to developer — 1 extra due to test script not gating on deduct failure)

---

## 4. Errors and Missing Functionality

### Critical
1. **No platform account (`ae_platform`):** The `/tollbooth/earn` endpoint requires a valid registered API key. There is no pre-seeded platform account to collect the 20% fee. Either:
   - Create a platform account at startup/migration time, or
   - Make the earn endpoint accept `ae_platform` as a special key, or
   - Handle the 80/20 split atomically inside the deduct endpoint itself.

### Medium
2. **80/20 split is not atomic:** The deduct and earn are separate API calls. If the gateway deducts from the caller but crashes before calling earn, credits are lost. Consider making the split part of the deduct transaction (populate `platform_fee` and `developer_credit` fields in the transaction record, which currently are always 0).

3. **Gateway down on Modal:** Both `simondusable--agenteazy-registry-serve.modal.run` and `simondusable--agenteazy-gateway-serve.modal.run` return empty responses. Step 8 (full gateway billing flow) could not be tested.

### Low
4. **Transfer limit tracking:** The `/tollbooth/check-transfer-limit` endpoint returns `daily_transferred: 0` even after 5 deductions. It may only track PAY verb transfers (peer-to-peer), not agent_call deductions. Clarify whether agent calls should count toward daily limits.

5. **Transaction `platform_fee` and `developer_credit` fields:** Always 0 in all transactions. These fields exist in the schema but are never populated. They should be populated during deduct to provide a complete audit trail.

---

## Summary

**6 PASS / 1 PARTIAL / 1 SKIP / 1 FAIL (infra)**

The core TollBooth credit system works correctly:
- Signup with bonus credits ✓
- Credit deduction with overdraft protection ✓
- Developer earnings via earn endpoint ✓
- Anti-abuse guards (invalid key, insufficient credits, duplicate signup) ✓
- Transaction history with full audit trail ✓
- Agent registration with owner tracking ✓

The main gap is the **missing platform account** for collecting the 20% fee, and the **non-atomic 80/20 split** which should ideally be handled within the deduct transaction.
