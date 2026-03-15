"""AgentLang — the 10-verb protocol for agent communication."""

VALID_VERBS = [
    "ASK", "DO", "FIND", "PAY", "WATCH",
    "STOP", "TRUST", "SHARE", "LEARN", "REPORT",
]

VERB_DESCRIPTIONS = {
    "DO": "Execute a task",
    "ASK": "Query capabilities",
    "FIND": "Search the registry",
    "PAY": "Transfer credits between agents",
    "SHARE": "Pass context to an agent",
    "REPORT": "Get audit log and recent calls",
    "STOP": "Halt a running task",
    "WATCH": "Subscribe to events (coming soon)",
    "TRUST": "Establish authenticated session (coming soon)",
    "LEARN": "Ingest new knowledge (coming soon)",
}

IMPLEMENTED_VERBS = ["ASK", "DO", "FIND", "PAY", "SHARE", "REPORT", "STOP"]
STUB_VERBS = ["WATCH", "TRUST", "LEARN"]


def validate_verb(verb: str) -> bool:
    """Check whether the given verb is one of the 10 AgentLang verbs."""
    return verb.upper() in VALID_VERBS


def get_verb_info(verb: str) -> dict:
    """Return description for a verb, or empty dict if unknown."""
    desc = VERB_DESCRIPTIONS.get(verb.upper())
    if desc:
        return {"description": desc}
    return {}
