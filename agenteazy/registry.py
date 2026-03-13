"""AgentEazy Registry — central directory for wrapped agents."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
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
                            entry_function, entry_file, tags, created_at, last_seen, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        ON CONFLICT(name) DO UPDATE SET
            description    = excluded.description,
            url            = excluded.url,
            language       = excluded.language,
            verbs          = excluded.verbs,
            entry_function = excluded.entry_function,
            entry_file     = excluded.entry_file,
            tags           = excluded.tags,
            last_seen      = excluded.last_seen,
            status         = 'active'
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


if __name__ == "__main__":
    port = int(os.environ.get("REGISTRY_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
