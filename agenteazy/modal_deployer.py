"""Modal Deployer - Deploy wrapped agents to Modal as serverless web endpoints.

Supports two modes:
  1. Legacy: deploy each agent as its own Modal app (deploy_to_modal)
  2. Gateway: upload agent code to a shared Modal Volume (upload_to_volume)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time

VOLUME_NAME = "agenteazy-agents-vol"


def check_modal_auth() -> bool:
    """Check if Modal is authenticated by attempting 'modal app list'.

    Modal CLI stores tokens in ~/.modal.toml after 'modal setup'.
    This function verifies that a valid token exists by making an
    actual authenticated API call.

    Returns True if authenticated, False otherwise.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "modal", "app", "list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # If the command fails with a token error, auth is not set up
        combined = result.stdout + result.stderr
        if "Token missing" in combined or "Could not authenticate" in combined:
            return False
        return result.returncode == 0
    except FileNotFoundError:
        return False
    except subprocess.TimeoutExpired:
        return False


def list_deployed_agents() -> list:
    """Run 'modal app list' and parse the output to show all currently deployed agents.

    Returns a list of dicts with keys: name, app_id, state.
    """
    result = subprocess.run(
        [sys.executable, "-m", "modal", "app", "list"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to list Modal apps: {result.stderr}")

    agents = []
    lines = result.stdout.strip().splitlines()

    for line in lines:
        # Skip header/separator lines
        stripped = line.strip()
        if not stripped or stripped.startswith("│") is False and "─" in stripped:
            continue

        # Parse table rows — Modal outputs a table with columns like:
        # App Name | App ID | State
        # We split on whitespace clusters or pipe characters
        if "│" in line:
            parts = [p.strip() for p in line.split("│") if p.strip()]
            if len(parts) >= 2 and parts[0].lower() not in ("app name", "name", "description"):
                agents.append({
                    "name": parts[0],
                    "app_id": parts[1] if len(parts) > 1 else "",
                    "state": parts[2] if len(parts) > 2 else "unknown",
                })
        else:
            # Fallback: split on whitespace
            parts = stripped.split()
            if len(parts) >= 2 and not any(c in parts[0] for c in ("─", "═", "+")):
                agents.append({
                    "name": parts[0],
                    "app_id": parts[1] if len(parts) > 1 else "",
                    "state": parts[2] if len(parts) > 2 else "unknown",
                })

    return agents


def stop_agent(name: str) -> bool:
    """Run 'modal app stop {name}' to remove a deployed agent.

    Returns True if the stop command succeeded.
    """
    result = subprocess.run(
        [sys.executable, "-m", "modal", "app", "stop", name],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0


def get_agent_logs(name: str) -> str:
    """Run 'modal app logs {name}' to get recent logs.

    Returns the log output as a string.
    """
    result = subprocess.run(
        [sys.executable, "-m", "modal", "app", "logs", name],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get logs for '{name}': {result.stderr}")

    return result.stdout


def sanitize_agent_name(name: str) -> str:
    """Convert any repo/agent name to a valid Modal app name.

    Rules: lowercase, alphanumeric + hyphens only, no leading/trailing hyphens,
    collapse consecutive hyphens.
    """
    sanitized = re.sub(r"[^a-z0-9-]", "-", name.lower())
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    return sanitized.strip("-")


def _find_unique_modal_name(base_name: str, existing_names: list[str]) -> str:
    """Find a unique Modal app name by appending -v2, -v3, etc. if needed."""
    if base_name not in existing_names:
        return base_name

    version = 2
    while f"{base_name}-v{version}" in existing_names:
        version += 1
    return f"{base_name}-v{version}"


def deploy_to_modal(output_dir: str, agent_name: str) -> str:
    """
    Deploy a wrapped agent to Modal as a serverless ASGI endpoint.

    Args:
        output_dir: Path to agenteazy-output/<name>/ containing wrapper.py, agent.json, repo/
        agent_name: Name for the Modal app (used in the URL)

    Returns:
        The live URL of the deployed agent.
    """
    # Check authentication before attempting deploy
    if not check_modal_auth():
        raise RuntimeError(
            "Modal not authenticated.\n"
            "  Fix: Run 'modal setup' to configure your token.\n"
            "  Tokens are stored in ~/.modal.toml"
        )

    output_dir = os.path.abspath(output_dir)

    # Validate required files exist
    agent_json_path = os.path.join(output_dir, "agent.json")
    wrapper_path = os.path.join(output_dir, "wrapper.py")

    if not os.path.isfile(agent_json_path):
        raise FileNotFoundError(f"agent.json not found in {output_dir}")
    if not os.path.isfile(wrapper_path):
        raise FileNotFoundError(f"wrapper.py not found in {output_dir}")

    # Read agent config
    with open(agent_json_path) as f:
        agent_config = json.load(f)

    # Read dependencies from requirements.txt if present
    reqs_path = os.path.join(output_dir, "requirements.txt")
    dependencies = []
    if os.path.isfile(reqs_path):
        with open(reqs_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    dependencies.append(line)

    # Ensure fastapi and uvicorn are in deps
    dep_names = [re.split(r"[>=<!\[]", d)[0].lower() for d in dependencies]
    if "fastapi" not in dep_names:
        dependencies.append("fastapi>=0.100.0")
    if "uvicorn" not in dep_names:
        dependencies.append("uvicorn>=0.23.0")

    # Sanitize and deduplicate app name
    modal_app_name = sanitize_agent_name(agent_name)
    try:
        existing = list_deployed_agents()
        existing_names = [a["name"] for a in existing]
        modal_app_name = _find_unique_modal_name(modal_app_name, existing_names)
    except RuntimeError:
        pass  # If we can't list apps, proceed with the base name

    # Generate the Modal deploy script
    # We use repr() to safely embed the dependencies list and paths
    deploy_script = _generate_modal_script(
        modal_app_name=modal_app_name,
        output_dir=output_dir,
        dependencies=dependencies,
    )

    # Write the deploy script to a temp file and run `modal deploy`
    with tempfile.NamedTemporaryFile(
        mode="w", suffix="_modal_deploy.py", dir=output_dir, delete=False
    ) as f:
        f.write(deploy_script)
        deploy_script_path = f.name

    try:
        print(f"\nDeploying '{modal_app_name}' to Modal...")

        # Try deploy with one retry on network timeout
        result = None
        for attempt in range(2):
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "modal", "deploy", deploy_script_path],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                break
            except subprocess.TimeoutExpired:
                if attempt == 0:
                    print("Deploy timed out, retrying once...")
                    time.sleep(2)
                else:
                    raise RuntimeError(
                        "Modal deploy timed out after 2 attempts.\n"
                        "  Check your network connection and try again."
                    )

        if result.returncode != 0:
            combined = result.stdout + result.stderr
            # Detect rate limiting
            if "rate limit" in combined.lower() or "429" in combined or "limit" in combined.lower() and "free" in combined.lower():
                raise RuntimeError(
                    "Modal free tier limit reached.\n"
                    "  Fix: Stop unused agents with: agenteazy cleanup --all\n"
                    "  Or upgrade your Modal plan at modal.com"
                )
            # Detect auth issues
            if "Token missing" in combined or "Could not authenticate" in combined:
                raise RuntimeError(
                    "Modal authentication failed during deploy.\n"
                    "  Fix: Run 'modal setup' to refresh your token."
                )
            # Generic failure with stderr
            error_msg = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(
                f"Modal deploy failed:\n{error_msg}\n\n"
                f"  Suggestions:\n"
                f"  - Check that 'modal' is installed: pip install modal\n"
                f"  - Verify auth: modal profile current\n"
                f"  - Check Modal status: modal.com/status"
            )

        # Parse the URL from modal deploy output
        url = _parse_modal_url(result.stdout + result.stderr, modal_app_name)
        return url
    finally:
        # Clean up temp file
        os.unlink(deploy_script_path)


def _generate_modal_script(
    modal_app_name: str,
    output_dir: str,
    dependencies: list[str],
) -> str:
    """Generate a Modal deployment Python script."""
    deps_repr = repr(dependencies)
    output_dir_repr = repr(output_dir)

    return f'''"""Auto-generated Modal deployment script for {modal_app_name}."""

import modal

app = modal.App("{modal_app_name}")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install({deps_repr})
    .add_local_dir({output_dir_repr}, remote_path="/app")
    .env({{"PYTHONDONTWRITEBYTECODE": "1"}})
    .workdir("/app")
)


@app.function(image=image, timeout=30, memory=512, cpu=1.0)
@modal.asgi_app()
def serve():
    import importlib.util
    import sys

    # Load wrapper.py from the baked-in directory
    spec = importlib.util.spec_from_file_location("wrapper", "/app/wrapper.py")
    wrapper_mod = importlib.util.module_from_spec(spec)
    sys.modules["wrapper"] = wrapper_mod
    spec.loader.exec_module(wrapper_mod)
    return wrapper_mod.app
'''


def _parse_modal_url(output: str, app_name: str) -> str:
    """Extract the deployed URL from modal deploy output."""
    # Modal typically prints something like:
    #   https://<workspace>--<app-name>-serve.modal.run
    # or View Deployment: https://...
    import re

    # Look for any URL in the output
    urls = re.findall(r"https://[^\s]+\.modal\.run[^\s]*", output)
    if urls:
        # Prefer the one that contains our app name
        for url in urls:
            if app_name in url:
                return url.rstrip(".")
        return urls[0].rstrip(".")

    # Fallback: construct expected URL pattern
    # Modal URL format: https://<workspace>--<app-name>-serve.modal.run
    return f"https://<workspace>--{app_name}-serve.modal.run (check Modal dashboard for exact URL)"


def get_modal_url(agent_name: str) -> str:
    """
    Get the URL where a deployed Modal agent is running.

    Uses `modal app list` to find the app and its URL.
    """
    modal_app_name = re.sub(r"[^a-z0-9-]", "-", agent_name.lower()).strip("-")

    result = subprocess.run(
        [sys.executable, "-m", "modal", "app", "list"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to list Modal apps: {result.stderr}")

    # Look for our app in the output
    for line in result.stdout.splitlines():
        if modal_app_name in line:
            urls = re.findall(r"https://[^\s]+\.modal\.run[^\s]*", line)
            if urls:
                return urls[0]

    # If not found in list, try the expected URL pattern
    return f"https://<workspace>--{modal_app_name}-serve.modal.run"


# ── Gateway mode: upload to shared volume ────────────────────────────


def upload_to_volume(output_dir: str, agent_name: str, gateway_url: str) -> str:
    """Upload agent code to the shared Modal Volume for the gateway.

    Instead of creating a new Modal app, this writes the agent's files
    (wrapper.py, agent.json, repo/, requirements.txt) to the shared volume
    at /agents/{agent_name}/.

    Args:
        output_dir: Path to agenteazy-output/<name>/ containing the agent files.
        agent_name: Sanitized agent name (used as the directory name on the volume).
        gateway_url: The base URL of the deployed gateway.

    Returns:
        The agent's endpoint URL through the gateway.
    """
    if not check_modal_auth():
        raise RuntimeError(
            "Modal not authenticated.\n"
            "  Fix: Run 'modal setup' to configure your token.\n"
            "  Tokens are stored in ~/.modal.toml"
        )

    output_dir = os.path.abspath(output_dir)

    # Validate required files
    for required in ("agent.json", "wrapper.py"):
        path = os.path.join(output_dir, required)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{required} not found in {output_dir}")

    agent_name = sanitize_agent_name(agent_name)

    # Generate a script that uploads the local dir to the volume
    upload_script = _generate_upload_script(output_dir, agent_name)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix="_vol_upload.py", dir=output_dir, delete=False
    ) as f:
        f.write(upload_script)
        script_path = f.name

    try:
        print(f"\nUploading '{agent_name}' to volume '{VOLUME_NAME}'...")

        result = None
        for attempt in range(2):
            try:
                result = subprocess.run(
                    [sys.executable, script_path],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                break
            except subprocess.TimeoutExpired:
                if attempt == 0:
                    print("Upload timed out, retrying once...")
                    time.sleep(2)
                else:
                    raise RuntimeError(
                        "Volume upload timed out after 2 attempts.\n"
                        "  Check your network connection and try again."
                    )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"Volume upload failed:\n{error_msg}")

        # Return the gateway URL for this agent
        gw = gateway_url.rstrip("/")
        return f"{gw}/agent/{agent_name}/do"
    finally:
        os.unlink(script_path)


def _generate_upload_script(output_dir: str, agent_name: str) -> str:
    """Generate a Python script that uploads agent files to the Modal Volume."""
    output_dir_repr = repr(output_dir)
    agent_name_repr = repr(agent_name)
    volume_name_repr = repr(VOLUME_NAME)

    return f'''"""Auto-generated script to upload agent code to Modal Volume."""

import os
import modal

volume = modal.Volume.from_name({volume_name_repr}, create_if_missing=True)
local_dir = {output_dir_repr}
agent_name = {agent_name_repr}
remote_base = f"/{{agent_name}}"

# Upload the entire output directory to the volume under /agent_name/
# We walk the local directory and put each file individually
with volume.batch_upload() as batch:
    batch.put_directory(local_dir, remote_base)

volume.commit()
print(f"Uploaded {{agent_name}} to volume at {{remote_base}}/")
'''
