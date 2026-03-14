"""AgentEazy Registry — central directory for wrapped agents."""

import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

DB_PATH = Path(os.environ.get("AGENTEAZY_DB_PATH", "./agenteazy-registry.db"))

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


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for field in ("verbs", "tags"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
        else:
            d[field] = []
    return d


# ── Endpoints ────────────────────────────────────────────────────────

@app.post("/registry/register")
def register_agent(req: RegisterRequest):
    db = _get_db()
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
    db.close()
    return {"registered": True, "name": req.name}


@app.get("/registry/search")
def search_agents(q: str = Query(..., min_length=1)):
    db = _get_db()
    pattern = f"%{q}%"
    rows = db.execute(
        """
        SELECT * FROM agents
        WHERE name LIKE ? OR description LIKE ? OR tags LIKE ?
        """,
        (pattern, pattern, pattern),
    ).fetchall()
    db.close()
    return [_row_to_dict(r) for r in rows]


@app.get("/registry/agent/{name}")
def get_agent(name: str):
    db = _get_db()
    row = db.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return _row_to_dict(row)


@app.get("/registry/agent/{name}/owner")
def get_agent_owner(name: str):
    db = _get_db()
    row = db.execute("SELECT owner_api_key FROM agents WHERE name = ?", (name,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return {"owner_api_key": row["owner_api_key"]}


@app.get("/registry/all")
def list_agents(limit: int = Query(50, ge=1), offset: int = Query(0, ge=0)):
    db = _get_db()
    rows = db.execute(
        "SELECT * FROM agents ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    db.close()
    return [_row_to_dict(r) for r in rows]


@app.delete("/registry/agent/{name}")
def delete_agent(name: str):
    db = _get_db()
    cur = db.execute("DELETE FROM agents WHERE name = ?", (name,))
    db.commit()
    db.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return {"deleted": True}


@app.get("/registry/stats")
def stats():
    db = _get_db()
    total = db.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    active = db.execute(
        "SELECT COUNT(*) FROM agents WHERE status = 'active'"
    ).fetchone()[0]
    lang_rows = db.execute(
        "SELECT language, COUNT(*) as cnt FROM agents WHERE language IS NOT NULL GROUP BY language"
    ).fetchall()
    db.close()
    languages = {r["language"]: r["cnt"] for r in lang_rows}
    return {"total_agents": total, "active": active, "languages": languages}


@app.post("/registry/heartbeat/{name}")
def heartbeat(name: str):
    db = _get_db()
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        "UPDATE agents SET last_seen = ? WHERE name = ?", (now, name)
    )
    db.commit()
    db.close()
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


# ── Tollbooth Endpoints ─────────────────────────────────────────────

@app.post("/tollbooth/signup")
def tollbooth_signup(req: SignupRequest):
    db = _get_db()
    existing = db.execute(
        "SELECT api_key FROM balances WHERE github_username = ?",
        (req.github_username,),
    ).fetchone()
    if existing:
        db.close()
        return JSONResponse(status_code=409, content={"error": "Account already exists"})

    api_key = "ae_" + secrets.token_hex(16)
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        """INSERT INTO balances (api_key, github_username, email, credits, total_earned, total_spent, bonus_claimed, created_at)
           VALUES (?, ?, ?, 50, 0, 0, 0, ?)""",
        (api_key, req.github_username, req.email, now),
    )
    db.execute(
        """INSERT INTO transactions (from_key, to_key, agent_name, credits, platform_fee, developer_credit, type, verb, timestamp)
           VALUES (NULL, ?, NULL, 50, 0, 0, 'signup_bonus', NULL, ?)""",
        (api_key, now),
    )
    db.commit()
    db.close()
    return {"api_key": api_key, "credits": 50, "github_username": req.github_username}


@app.get("/tollbooth/balance/{api_key}")
def tollbooth_balance(api_key: str):
    db = _get_db()
    row = db.execute("SELECT * FROM balances WHERE api_key = ?", (api_key,)).fetchone()
    db.close()
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
    db = _get_db()
    row = db.execute("SELECT * FROM balances WHERE api_key = ?", (req.api_key,)).fetchone()
    if not row:
        db.close()
        return JSONResponse(status_code=404, content={"error": "Invalid API key"})
    if row["credits"] < req.amount:
        balance = row["credits"]
        db.close()
        return JSONResponse(
            status_code=400,
            content={"error": "Insufficient credits", "balance": balance, "cost": req.amount},
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
    db.close()
    return {"success": True, "remaining": new_balance}


@app.post("/tollbooth/earn")
def tollbooth_earn(req: EarnRequest):
    db = _get_db()
    row = db.execute("SELECT * FROM balances WHERE api_key = ?", (req.api_key,)).fetchone()
    if not row:
        db.close()
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
    db.close()
    return {"success": True, "credits": new_balance}


@app.get("/tollbooth/transactions/{api_key}")
def tollbooth_transactions(api_key: str, limit: int = Query(50, ge=1)):
    db = _get_db()
    row = db.execute("SELECT api_key FROM balances WHERE api_key = ?", (api_key,)).fetchone()
    if not row:
        db.close()
        return JSONResponse(status_code=404, content={"error": "Invalid API key"})
    rows = db.execute(
        "SELECT * FROM transactions WHERE from_key = ? OR to_key = ? ORDER BY timestamp DESC LIMIT ?",
        (api_key, api_key, limit),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


@app.get("/tollbooth/stats")
def tollbooth_stats():
    db = _get_db()
    total_accounts = db.execute("SELECT COUNT(*) FROM balances").fetchone()[0]
    total_credits = db.execute("SELECT COALESCE(SUM(credits), 0) FROM balances").fetchone()[0]
    total_transactions = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    db.close()
    return {
        "total_accounts": total_accounts,
        "total_credits_in_circulation": total_credits,
        "total_transactions": total_transactions,
    }


if __name__ == "__main__":
    port = int(os.environ.get("REGISTRY_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
