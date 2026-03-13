"""AgentLang — universal 10-verb protocol for agent communication."""

VERBS = {
    "ASK": {"description": "Query without changing state", "http_equiv": "GET", "requires_auth": False},
    "DO": {"description": "Execute a task, may change state", "http_equiv": "POST", "requires_auth": False},
    "FIND": {"description": "Search for agents or data", "http_equiv": "GET", "requires_auth": False},
    "PAY": {"description": "Transfer credits for service", "http_equiv": "POST", "requires_auth": True},
    "WATCH": {"description": "Subscribe to changes", "http_equiv": "POST", "requires_auth": False},
    "STOP": {"description": "Halt current task", "http_equiv": "DELETE", "requires_auth": False},
    "TRUST": {"description": "Establish authenticated session", "http_equiv": "POST", "requires_auth": False},
    "SHARE": {"description": "Pass context between agents", "http_equiv": "POST", "requires_auth": False},
    "LEARN": {"description": "Ingest new knowledge", "http_equiv": "POST", "requires_auth": True},
    "REPORT": {"description": "Get audit log of actions", "http_equiv": "GET", "requires_auth": False},
}

VALID_VERBS = list(VERBS.keys())


def validate_verb(verb: str) -> bool:
    """Check whether the given verb is one of the 10 AgentLang verbs."""
    return verb.upper() in VERBS


def get_verb_info(verb: str) -> dict:
    """Return metadata for a verb, or empty dict if unknown."""
    return VERBS.get(verb.upper(), {})
