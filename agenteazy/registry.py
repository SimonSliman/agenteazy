# force-redeploy
"""AgentEazy Registry — central directory for wrapped agents."""

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

DB_PATH = Path(os.environ.get("AGENTEAZY_DB_PATH", "./agenteazy-registry.db"))
ADMIN_KEY = os.environ.get("AGENTEAZY_ADMIN_KEY")

app = FastAPI(title="AgentEazy Registry", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    description: Optional[str] = None
    url: str
    language: Optional[str] = None
    verbs: Optional[list] = None
    entry_function: Optional[str] = None
    entry_file: Optional[str] = None
    tags: Optional[list] = None
    owner_api_key: Optional[str] = None


# ── DB helpers ───────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            name            TEXT PRIMARY KEY,
            description     TEXT,
            url             TEXT NOT NULL,
            language        TEXT,
            verbs           TEXT,
            entry_function  TEXT,
            entry_file      TEXT,
            tags            TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status          TEXT DEFAULT 'active'
        )
    """)
    # Add owner_api_key column if it doesn't exist yet
    cursor = conn.execute("PRAGMA table_info(agents)")
    columns = [row[1] for row in cursor.fetchall()]
    if "owner_api_key" not in columns:
        conn.execute("ALTER TABLE agents ADD COLUMN owner_api_key TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS balances (
            api_key         TEXT PRIMARY KEY,
            github_username TEXT,
            email           TEXT,
            credits         INTEGER DEFAULT 0,
            total_earned    INTEGER DEFAULT 0,
            total_spent     INTEGER DEFAULT 0,
            bonus_claimed   INTEGER DEFAULT 0,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Add ip_address column if it doesn't exist yet
    bal_cursor = conn.execute("PRAGMA table_info(balances)")
    bal_columns = [row[1] for row in bal_cursor.fetchall()]
    if "ip_address" not in bal_columns:
        conn.execute("ALTER TABLE balances ADD COLUMN ip_address TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            from_key        TEXT,
            to_key          TEXT,
            agent_name      TEXT,
            credits         INTEGER,
            platform_fee    INTEGER,
            developer_credit INTEGER,
            type            TEXT,
            verb            TEXT,
            timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


@contextmanager
def _db():
    """Context manager for database connections. Guarantees close on exit."""
    conn = _get_db()
    try:
        yield conn
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row, include_secrets: bool = False) -> dict:
    d = dict(row)
    for field in ("verbs", "tags"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
        else:
            d[field] = []
    if not include_secrets:
        d.pop("owner_api_key", None)
    return d


# ── Endpoints ────────────────────────────────────────────────────────

@app.post("/registry/register")
def register_agent(req: RegisterRequest, request: Request):
    with _db() as db:
        # Check if agent already exists — if so, require the original owner's key
        existing = db.execute(
            "SELECT owner_api_key FROM agents WHERE name = ?", (req.name,)
        ).fetchone()
        if existing and existing["owner_api_key"]:
            # Agent exists with an owner — caller must prove ownership
            caller_key = req.owner_api_key or request.headers.get("x-api-key")
            if caller_key != existing["owner_api_key"]:
                raise HTTPException(
                    status_code=403,
                    detail=f"Agent '{req.name}' is already registered by another owner",
                )
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """
            INSERT INTO agents (name, description, url, language, verbs,
                                entry_function, entry_file, tags, created_at, last_seen, status, owner_api_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(name) DO UPDATE SET
                description    = excluded.description,
                url            = excluded.url,
                language       = excluded.language,
                verbs          = excluded.verbs,
                entry_function = excluded.entry_function,
                entry_file     = excluded.entry_file,
                tags           = excluded.tags,
                last_seen      = excluded.last_seen,
                status         = 'active',
                owner_api_key  = excluded.owner_api_key
            """,
            (
                req.name,
                req.description,
                req.url,
                req.language,
                json.dumps(req.verbs or []),
                req.entry_function,
                req.entry_file,
                json.dumps(req.tags or []),
                now,
                now,
                req.owner_api_key,
            ),
        )
        db.commit()
        return {"registered": True, "name": req.name}


@app.get("/registry/search")
def search_agents(q: str = Query(..., min_length=1)):
    with _db() as db:
        pattern = f"%{q}%"
        rows = db.execute(
            """
            SELECT * FROM agents
            WHERE name LIKE ? OR description LIKE ? OR tags LIKE ?
            """,
            (pattern, pattern, pattern),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


@app.get("/registry/agent/{name}")
def get_agent(name: str):
    with _db() as db:
        row = db.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return _row_to_dict(row)


@app.get("/registry/agent/{name}/owner")
def get_agent_owner(name: str):
    with _db() as db:
        row = db.execute("SELECT owner_api_key FROM agents WHERE name = ?", (name,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return {"owner_api_key": row["owner_api_key"]}


@app.get("/registry/agents-by-owner/{api_key}")
def agents_by_owner(api_key: str):
    with _db() as db:
        rows = db.execute(
            "SELECT * FROM agents WHERE owner_api_key = ? ORDER BY name",
            (api_key,),
        ).fetchall()
        agents = [_row_to_dict(r, include_secrets=False) for r in rows]
        return {"agents": agents, "count": len(agents)}


@app.get("/registry/all")
def list_agents(limit: int = Query(50, ge=1), offset: int = Query(0, ge=0)):
    with _db() as db:
        rows = db.execute(
            "SELECT * FROM agents ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


@app.delete("/registry/agent/{name}")
def delete_agent(name: str, request: Request):
    api_key = request.headers.get("x-api-key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    with _db() as db:
        row = db.execute("SELECT owner_api_key FROM agents WHERE name = ?", (name,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        if row["owner_api_key"] != api_key:
            raise HTTPException(status_code=403, detail="Not authorized to delete this agent")
        db.execute("DELETE FROM agents WHERE name = ?", (name,))
        db.commit()
        return {"deleted": True}


@app.get("/registry/stats")
def stats():
    with _db() as db:
        total = db.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        active = db.execute(
            "SELECT COUNT(*) FROM agents WHERE status = 'active'"
        ).fetchone()[0]
        lang_rows = db.execute(
            "SELECT language, COUNT(*) as cnt FROM agents WHERE language IS NOT NULL GROUP BY language"
        ).fetchall()
        languages = {r["language"]: r["cnt"] for r in lang_rows}
        return {"total_agents": total, "active": active, "languages": languages}


@app.post("/registry/heartbeat/{name}")
def heartbeat(name: str):
    with _db() as db:
        now = datetime.now(timezone.utc).isoformat()
        cur = db.execute(
            "UPDATE agents SET last_seen = ? WHERE name = ?", (now, name)
        )
        db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return {"alive": True}


# ── Tollbooth Models ─────────────────────────────────────────────────

class SignupRequest(BaseModel):
    github_username: str
    email: str


class DeductRequest(BaseModel):
    api_key: str
    agent_name: str
    amount: int


class EarnRequest(BaseModel):
    api_key: str
    amount: int
    source: str


class CheckTransferLimitRequest(BaseModel):
    api_key: str
    amount: int


# ── Tollbooth Endpoints ─────────────────────────────────────────────

@app.post("/tollbooth/signup")
def tollbooth_signup(req: SignupRequest, request: Request):
    with _db() as db:
        # Duplicate email protection
        if req.email:
            email_exists = db.execute(
                "SELECT api_key FROM balances WHERE email = ?",
                (req.email,),
            ).fetchone()
            if email_exists:
                return JSONResponse(status_code=409, content={"error": "Email already registered"})

        existing = db.execute(
            "SELECT api_key FROM balances WHERE github_username = ?",
            (req.github_username,),
        ).fetchone()
        if existing:
            return JSONResponse(status_code=409, content={"error": "Account already exists"})

        # Rate limit signups: max 5 per IP per hour
        client_ip = request.client.host if request.client else "unknown"
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        signup_count = db.execute(
            "SELECT COUNT(*) FROM balances WHERE ip_address = ? AND created_at >= ?",
            (client_ip, one_hour_ago),
        ).fetchone()[0]
        if signup_count >= 5:
            return JSONResponse(status_code=429, content={"error": "Too many signups. Try again later."})

        api_key = "ae_" + secrets.token_hex(16)
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT INTO balances (api_key, github_username, email, credits, total_earned, total_spent, bonus_claimed, created_at, ip_address)
               VALUES (?, ?, ?, 50, 0, 0, 0, ?, ?)""",
            (api_key, req.github_username, req.email, now, client_ip),
        )
        db.execute(
            """INSERT INTO transactions (from_key, to_key, agent_name, credits, platform_fee, developer_credit, type, verb, timestamp)
               VALUES (NULL, ?, NULL, 50, 0, 0, 'signup_bonus', NULL, ?)""",
            (api_key, now),
        )
        db.commit()
        return {"api_key": api_key, "credits": 50, "github_username": req.github_username}


@app.get("/tollbooth/balance/{api_key}")
def tollbooth_balance(api_key: str):
    with _db() as db:
        row = db.execute("SELECT * FROM balances WHERE api_key = ?", (api_key,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Invalid API key"})
        return {
            "credits": row["credits"],
            "total_earned": row["total_earned"],
            "total_spent": row["total_spent"],
            "github_username": row["github_username"],
        }


@app.post("/tollbooth/deduct")
def tollbooth_deduct(req: DeductRequest):
    with _db() as db:
        row = db.execute("SELECT * FROM balances WHERE api_key = ?", (req.api_key,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Invalid API key"})

        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        # Rate limit: max 200 deductions per API key per hour
        call_count = db.execute(
            "SELECT COUNT(*) FROM transactions WHERE from_key = ? AND type = 'agent_call' AND timestamp >= ?",
            (req.api_key, one_hour_ago),
        ).fetchone()[0]
        if call_count >= 200:
            return JSONResponse(status_code=429, content={"error": "Rate limit exceeded. Max 200 calls per hour."})

        # Velocity limit: max 500 credits spent per hour per API key
        spent_hour = db.execute(
            "SELECT COALESCE(SUM(credits), 0) FROM transactions WHERE from_key = ? AND type = 'agent_call' AND timestamp >= ?",
            (req.api_key, one_hour_ago),
        ).fetchone()[0]
        if spent_hour + req.amount > 500:
            return JSONResponse(status_code=429, content={"error": "Spending limit exceeded. Max 500 credits per hour."})

        if row["credits"] < req.amount:
            return JSONResponse(
                status_code=400,
                content={"error": "Insufficient credits", "balance": row["credits"], "cost": req.amount},
            )
        new_balance = row["credits"] - req.amount
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE balances SET credits = ?, total_spent = total_spent + ? WHERE api_key = ?",
            (new_balance, req.amount, req.api_key),
        )
        db.execute(
            """INSERT INTO transactions (from_key, to_key, agent_name, credits, platform_fee, developer_credit, type, verb, timestamp)
               VALUES (?, NULL, ?, ?, 0, 0, 'agent_call', NULL, ?)""",
            (req.api_key, req.agent_name, req.amount, now),
        )
        db.commit()
        return {"success": True, "remaining": new_balance}


@app.post("/tollbooth/earn")
def tollbooth_earn(req: EarnRequest):
    with _db() as db:
        row = db.execute("SELECT * FROM balances WHERE api_key = ?", (req.api_key,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Invalid API key"})
        new_balance = row["credits"] + req.amount
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE balances SET credits = ?, total_earned = total_earned + ? WHERE api_key = ?",
            (new_balance, req.amount, req.api_key),
        )
        db.execute(
            """INSERT INTO transactions (from_key, to_key, agent_name, credits, platform_fee, developer_credit, type, verb, timestamp)
               VALUES (NULL, ?, NULL, ?, 0, 0, ?, NULL, ?)""",
            (req.api_key, req.amount, req.source, now),
        )
        db.commit()
        return {"success": True, "credits": new_balance}


@app.get("/tollbooth/transactions/{api_key}")
def tollbooth_transactions(api_key: str, limit: int = Query(50, ge=1)):
    with _db() as db:
        row = db.execute("SELECT api_key FROM balances WHERE api_key = ?", (api_key,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Invalid API key"})
        rows = db.execute(
            "SELECT * FROM transactions WHERE from_key = ? OR to_key = ? ORDER BY timestamp DESC LIMIT ?",
            (api_key, api_key, limit),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/tollbooth/stats")
def tollbooth_stats():
    with _db() as db:
        total_accounts = db.execute("SELECT COUNT(*) FROM balances").fetchone()[0]
        total_credits = db.execute("SELECT COALESCE(SUM(credits), 0) FROM balances").fetchone()[0]
        total_transactions = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        return {
            "total_accounts": total_accounts,
            "total_credits_in_circulation": total_credits,
            "total_transactions": total_transactions,
        }


class TransferRequest(BaseModel):
    from_api_key: str
    to_api_key: str
    amount: int
    agent_name: Optional[str] = None


@app.post("/tollbooth/transfer")
def tollbooth_transfer(req: TransferRequest):
    """Atomic credit transfer: deduct from sender and credit recipient in one transaction."""
    if req.amount <= 0:
        return JSONResponse(status_code=400, content={"error": "Amount must be positive"})
    if req.amount > 1000:
        return JSONResponse(status_code=400, content={"error": "Maximum transfer is 1000 credits"})

    with _db() as db:
        sender = db.execute("SELECT credits FROM balances WHERE api_key = ?", (req.from_api_key,)).fetchone()
        if not sender:
            return JSONResponse(status_code=404, content={"error": "Invalid sender API key"})

        recipient = db.execute("SELECT credits FROM balances WHERE api_key = ?", (req.to_api_key,)).fetchone()
        if not recipient:
            return JSONResponse(status_code=404, content={"error": "Invalid recipient API key"})

        if sender["credits"] < req.amount:
            return JSONResponse(status_code=400, content={
                "error": "Insufficient credits",
                "balance": sender["credits"],
                "cost": req.amount,
            })

        now = datetime.now(timezone.utc).isoformat()
        new_sender_balance = sender["credits"] - req.amount
        new_recipient_balance = recipient["credits"] + req.amount

        db.execute(
            "UPDATE balances SET credits = ?, total_spent = total_spent + ? WHERE api_key = ?",
            (new_sender_balance, req.amount, req.from_api_key),
        )
        db.execute(
            "UPDATE balances SET credits = ?, total_earned = total_earned + ? WHERE api_key = ?",
            (new_recipient_balance, req.amount, req.to_api_key),
        )
        db.execute(
            """INSERT INTO transactions (from_key, to_key, agent_name, credits, platform_fee, developer_credit, type, verb, timestamp)
               VALUES (?, ?, ?, ?, 0, 0, 'pay_transfer', 'PAY', ?)""",
            (req.from_api_key, req.to_api_key, req.agent_name, req.amount, now),
        )
        db.commit()
        return {"success": True, "transferred": req.amount, "remaining": new_sender_balance}


@app.post("/tollbooth/check-transfer-limit")
def check_transfer_limit(req: CheckTransferLimitRequest):
    with _db() as db:
        row = db.execute("SELECT api_key FROM balances WHERE api_key = ?", (req.api_key,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Invalid API key"})
        one_day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        daily_transferred = db.execute(
            "SELECT COALESCE(SUM(credits), 0) FROM transactions WHERE from_key = ? AND type = 'pay_transfer' AND timestamp >= ?",
            (req.api_key, one_day_ago),
        ).fetchone()[0]
        if daily_transferred + req.amount > 1000:
            return JSONResponse(status_code=429, content={"error": "Daily transfer limit exceeded. Max 1000 credits per day."})
        return {"ok": True, "daily_transferred": daily_transferred}


# ── Admin helpers ────────────────────────────────────────────────────

def _require_admin(request: Request):
    """Check admin key from header. Raises 401/503."""
    if not ADMIN_KEY:
        raise HTTPException(status_code=503, detail="Admin not configured")
    key = request.headers.get("x-admin-key")
    if key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


class AdminCreditRequest(BaseModel):
    api_key: str
    amount: int  # Positive to credit, negative to debit
    reason: str = "admin_adjustment"


# ── Admin Endpoints ─────────────────────────────────────────────────

@app.get("/admin/accounts")
def admin_list_accounts(request: Request, limit: int = Query(100, ge=1), offset: int = Query(0, ge=0)):
    _require_admin(request)
    with _db() as db:
        rows = db.execute(
            "SELECT api_key, github_username, email, credits, total_earned, total_spent, created_at FROM balances ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = db.execute("SELECT COUNT(*) FROM balances").fetchone()[0]

        accounts = []
        for r in rows:
            accounts.append({
                "api_key_prefix": r["api_key"][:10] + "...",
                "api_key": r["api_key"],
                "github_username": r["github_username"],
                "email": r["email"],
                "credits": r["credits"],
                "total_earned": r["total_earned"],
                "total_spent": r["total_spent"],
                "created_at": r["created_at"],
            })

        return {"accounts": accounts, "total": total}


@app.get("/admin/transactions")
def admin_list_transactions(request: Request, limit: int = Query(100, ge=1), offset: int = Query(0, ge=0), type: str = Query(None)):
    _require_admin(request)
    with _db() as db:
        if type:
            rows = db.execute(
                "SELECT * FROM transactions WHERE type = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (type, limit, offset),
            ).fetchall()
            total = db.execute("SELECT COUNT(*) FROM transactions WHERE type = ?", (type,)).fetchone()[0]
        else:
            rows = db.execute(
                "SELECT * FROM transactions ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

        return {"transactions": [dict(r) for r in rows], "total": total}


@app.get("/admin/platform-summary")
def admin_platform_summary(request: Request):
    _require_admin(request)
    with _db() as db:
        total_accounts = db.execute("SELECT COUNT(*) FROM balances").fetchone()[0]
        total_credits = db.execute("SELECT COALESCE(SUM(credits), 0) FROM balances").fetchone()[0]
        total_earned = db.execute("SELECT COALESCE(SUM(total_earned), 0) FROM balances").fetchone()[0]
        total_spent = db.execute("SELECT COALESCE(SUM(total_spent), 0) FROM balances").fetchone()[0]
        total_transactions = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

        platform = db.execute(
            "SELECT credits, total_earned FROM balances WHERE api_key = 'ae_platform'"
        ).fetchone()

        type_breakdown = db.execute(
            "SELECT type, COUNT(*) as count, COALESCE(SUM(credits), 0) as total_credits FROM transactions GROUP BY type"
        ).fetchall()

        one_day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        recent_calls = db.execute(
            "SELECT COUNT(*) FROM transactions WHERE type = 'agent_call' AND timestamp >= ?",
            (one_day_ago,),
        ).fetchone()[0]
        recent_signups = db.execute(
            "SELECT COUNT(*) FROM transactions WHERE type = 'signup_bonus' AND timestamp >= ?",
            (one_day_ago,),
        ).fetchone()[0]

        return {
            "total_accounts": total_accounts,
            "total_credits_in_circulation": total_credits,
            "total_earned_all_time": total_earned,
            "total_spent_all_time": total_spent,
            "total_transactions": total_transactions,
            "platform_account": {
                "credits": platform["credits"] if platform else None,
                "total_earned": platform["total_earned"] if platform else None,
                "exists": platform is not None,
            },
            "transaction_breakdown": {r["type"]: {"count": r["count"], "credits": r["total_credits"]} for r in type_breakdown},
            "last_24h": {
                "agent_calls": recent_calls,
                "signups": recent_signups,
            },
        }


@app.post("/admin/credit-account")
def admin_credit_account(req: AdminCreditRequest, request: Request):
    _require_admin(request)
    with _db() as db:
        row = db.execute("SELECT credits FROM balances WHERE api_key = ?", (req.api_key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Account not found")

        new_balance = row["credits"] + req.amount
        if new_balance < 0:
            raise HTTPException(status_code=400, detail=f"Would result in negative balance ({new_balance})")

        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE balances SET credits = ? WHERE api_key = ?",
            (new_balance, req.api_key),
        )
        if req.amount > 0:
            db.execute("UPDATE balances SET total_earned = total_earned + ? WHERE api_key = ?", (req.amount, req.api_key))
        else:
            db.execute("UPDATE balances SET total_spent = total_spent + ? WHERE api_key = ?", (abs(req.amount), req.api_key))

        db.execute(
            """INSERT INTO transactions (from_key, to_key, agent_name, credits, platform_fee, developer_credit, type, verb, timestamp)
               VALUES (?, ?, NULL, ?, 0, 0, ?, NULL, ?)""",
            ("admin", req.api_key, abs(req.amount), req.reason, now),
        )
        db.commit()

        return {"success": True, "new_balance": new_balance, "adjustment": req.amount}


@app.post("/admin/seed-platform")
def admin_seed_platform(request: Request):
    _require_admin(request)
    with _db() as db:
        existing = db.execute("SELECT api_key FROM balances WHERE api_key = 'ae_platform'").fetchone()
        now = datetime.now(timezone.utc).isoformat()

        if existing:
            return {"status": "already_exists", "message": "ae_platform account already seeded"}

        db.execute(
            """INSERT INTO balances (api_key, github_username, email, credits, total_earned, total_spent, bonus_claimed, created_at, ip_address)
               VALUES ('ae_platform', 'agenteazy-platform', 'platform@agenteazy.com', 0, 0, 0, 0, ?, 'internal')""",
            (now,),
        )
        db.commit()

        return {"status": "seeded", "message": "ae_platform account created with 0 credits"}


if __name__ == "__main__":
    port = int(os.environ.get("REGISTRY_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
# registry-owner-endpoint 20260316T220046Z
