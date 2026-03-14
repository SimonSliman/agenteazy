# AgentEazy Security Notes

## Current Sandboxing Approach

AgentEazy deploys untrusted agent code inside **Modal containers** — ephemeral, isolated environments that run on Modal's infrastructure. Each agent runs in its own container with the following constraints:

### Resource Limits (enforced via Modal)
- **Timeout**: 30 seconds max execution per request
- **Memory**: 512 MB max RAM
- **CPU**: 1.0 core max
- **Python**: Pinned to 3.11 (explicit version)
- **Environment**: `PYTHONDONTWRITEBYTECODE=1` to prevent bytecode side-effects
- **Working directory**: `/app` (isolated from system paths)

### Dependency Isolation
- Only packages listed in the agent's `requirements.txt` are installed
- No system-level packages are added beyond the base Debian slim image
- FastAPI and uvicorn are the only framework dependencies injected by AgentEazy

### Input Validation
- POST `/do` requests are rejected if the body exceeds 1 MB
- Generated wrappers validate the Content-Length header before processing

### Dangerous Import Detection
- During `agenteazy analyze` and `agenteazy wrap`, all Python files are scanned for potentially dangerous patterns:
  - `os.system`, `subprocess`, `eval()`, `exec()`, `__import__`, `importlib`, `ctypes`, `socket`
- These produce **warnings** (they do not block wrapping) so the operator can make an informed decision

## Known Limitations

### No Network Isolation
Modal does not currently support per-function network policies. Deployed agents have unrestricted outbound network access. When Modal adds network policy support, we should restrict outbound traffic to:
- The agent registry API
- Known safe domains required by the agent's dependencies

### No GPU Restrictions
Agents could theoretically request GPU resources if the Modal deploy script is modified. The generated script does not request GPUs, but a malicious actor who modifies the deploy script could.

### No Request Signing
Requests to deployed agents are not signed or authenticated. Free agents can be called by anyone who knows the URL. Paid agents require an API key via the `auth` field or `x-api-key` header. Future versions should support:
- HMAC-signed requests from the registry
- Mutual agent authentication via AgentPass

### TollBooth Anti-Abuse Protections
The TollBooth billing system includes the following anti-abuse measures:
- **Rate limiting**: Signup endpoint is rate-limited to prevent bulk account creation
- **Velocity limits**: Unusual spending patterns are flagged
- **Transfer limits**: PAY verb transfers are capped at 1,000 credits per transaction
- **API key authentication**: Paid agents require valid API keys for billing
- **Fail-open design**: If the billing service is unreachable, agents default to free access rather than blocking legitimate traffic

## Future Plans

1. **Firecracker microVMs**: Investigate running agents in Firecracker-based microVMs for stronger isolation (when Modal or alternative platforms support this)
2. **Network policies**: Restrict outbound network per-agent as soon as Modal supports it
3. **Input signing**: HMAC-signed requests between registry and agents
4. **Dependency auditing**: Integrate with PyPI advisory databases to flag known-vulnerable packages
5. **Read-only filesystem**: Mount agent code as read-only to prevent runtime self-modification

## Responsible Disclosure

If you discover a security vulnerability in AgentEazy, please report it responsibly:

1. **Do not** open a public GitHub issue
2. Email the maintainers with a description of the vulnerability
3. Allow reasonable time for a fix before public disclosure

Contact: hello@agenteazy.com
