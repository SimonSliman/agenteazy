"""Modal Deployer - Deploy wrapped agents to Modal as serverless web endpoints."""

import json
import os
import re
import subprocess
import sys
import tempfile


def deploy_to_modal(output_dir: str, agent_name: str) -> str:
    """
    Deploy a wrapped agent to Modal as a serverless ASGI endpoint.

    Args:
        output_dir: Path to agenteazy-output/<name>/ containing wrapper.py, agent.json, repo/
        agent_name: Name for the Modal app (used in the URL)

    Returns:
        The live URL of the deployed agent.
    """
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

    # Sanitize app name for Modal (lowercase, alphanumeric + hyphens)
    modal_app_name = re.sub(r"[^a-z0-9-]", "-", agent_name.lower()).strip("-")

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
        result = subprocess.run(
            [sys.executable, "-m", "modal", "deploy", deploy_script_path],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Modal deploy failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
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
)


@app.function(image=image)
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
