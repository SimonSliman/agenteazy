"""Gateway Deployer — deploy agenteazy/gateway.py to Modal as ONE web endpoint.

This creates a single Modal app 'agenteazy-gateway' that serves all agents.
Agent code is stored on a shared Modal Volume at /agents/{agent_name}/.
"""

import os
import re
import subprocess
import sys
import tempfile
import time

from agenteazy.config import DEFAULT_REGISTRY_URL
from agenteazy.modal_deployer import check_modal_auth

MODAL_APP_NAME = "agenteazy-gateway"
VOLUME_NAME = "agenteazy-agents-vol"


def deploy_gateway() -> str:
    """Deploy the gateway FastAPI app to Modal with the shared agents volume.

    Returns the live URL of the deployed gateway.
    """
    if not check_modal_auth():
        raise RuntimeError(
            "Modal not authenticated.\n"
            "  Fix: Run 'modal setup' to configure your token."
        )

    gateway_src = os.path.join(os.path.dirname(__file__), "gateway.py")
    if not os.path.isfile(gateway_src):
        raise FileNotFoundError("gateway.py not found in agenteazy package")

    deploy_script = _generate_deploy_script(gateway_src)

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix="_gateway_deploy.py", delete=False
    )
    tmp.write(deploy_script)
    tmp.close()

    try:
        print(f"\nDeploying '{MODAL_APP_NAME}' to Modal...")

        result = None
        for attempt in range(2):
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "modal", "deploy", tmp.name],
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
            error_msg = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"Modal deploy failed:\n{error_msg}")

        url = _parse_modal_url(result.stdout + result.stderr)
        return url
    finally:
        os.unlink(tmp.name)


def _generate_deploy_script(gateway_src: str) -> str:
    """Generate the Modal deployment script for the gateway."""
    gateway_src_repr = repr(gateway_src)

    return f'''"""Auto-generated Modal deployment script for agenteazy-gateway."""

import modal

app = modal.App("{MODAL_APP_NAME}")

volume = modal.Volume.from_name("{VOLUME_NAME}", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install([
        "fastapi>=0.100.0", "uvicorn>=0.23.0",
        # Current skill deps
        "phonenumbers", "faker", "dnspython", "disposable-email-domains",
        # Batch 2 — text analysis
        "textstat", "textblob", "yake", "better-profanity",
        # Batch 3 — data conversion
        "pyyaml", "toml", "beautifulsoup4", "croniter",
        # Batch 4 — security
        "scrubadub", "bcrypt", "pyjwt",
        # Batch 5 — web utilities
        "ua-parser", "tldextract", "pytz",
        # Batch 6 — remaining
        "babel", "pint", "sumy", "nltk",
    ])
    .add_local_file({gateway_src_repr}, remote_path="/app/gateway.py", copy=True)
    .env({{"PYTHONDONTWRITEBYTECODE": "1", "AGENTEAZY_AGENTS_ROOT": "/agents", "AGENTEAZY_REGISTRY_URL": "{DEFAULT_REGISTRY_URL}"}})
    .run_commands("python -c "import nltk; nltk.download('punkt_tab'); nltk.download('punkt')"")
    .run_commands("python -c \"import nltk; nltk.download('punkt_tab'); nltk.download('punkt')\"")
    .workdir("/app")
)


@app.function(
    image=image,
    timeout=300,
    memory=512,
    cpu=1.0,
    volumes={{"/agents": volume}},
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def serve():
    import importlib.util
    import sys as _sys

    spec = importlib.util.spec_from_file_location("gateway", "/app/gateway.py")
    mod = importlib.util.module_from_spec(spec)
    _sys.modules["gateway"] = mod
    spec.loader.exec_module(mod)
    return mod.app
'''


def _parse_modal_url(output: str) -> str:
    """Extract the deployed URL from modal deploy output."""
    urls = re.findall(r"https://[^\s]+\.modal\.run[^\s]*", output)
    if urls:
        for url in urls:
            if MODAL_APP_NAME in url or "gateway" in url:
                return url.rstrip(".")
        return urls[0].rstrip(".")
    return f"https://<workspace>--{MODAL_APP_NAME}-serve.modal.run (check Modal dashboard for exact URL)"
