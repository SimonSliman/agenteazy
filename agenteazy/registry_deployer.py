"""Registry Deployer — deploy agenteazy/registry.py to Modal as a public web endpoint."""

import os
import re
import subprocess
import sys
import tempfile
import time

from agenteazy.modal_deployer import check_modal_auth, sanitize_agent_name


MODAL_APP_NAME = "agenteazy-registry"


def deploy_registry() -> str:
    """Deploy the registry FastAPI app to Modal with a persistent Volume for SQLite.

    Returns the live URL of the deployed registry.
    """
    if not check_modal_auth():
        raise RuntimeError(
            "Modal not authenticated.\n"
            "  Fix: Run 'modal setup' to configure your token."
        )

    registry_src = os.path.join(os.path.dirname(__file__), "registry.py")
    if not os.path.isfile(registry_src):
        raise FileNotFoundError("registry.py not found in agenteazy package")

    deploy_script = _generate_deploy_script(registry_src)

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix="_registry_deploy.py", delete=False
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


def _generate_deploy_script(registry_src: str) -> str:
    """Generate the Modal deployment script for the registry."""
    registry_src_repr = repr(registry_src)

    return f'''"""Auto-generated Modal deployment script for agenteazy-registry."""

import modal

app = modal.App("{MODAL_APP_NAME}")

volume = modal.Volume.from_name("agenteazy-registry-vol", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(["fastapi>=0.100.0", "uvicorn>=0.23.0"])
    .add_local_file({registry_src_repr}, remote_path="/app/registry.py")
    .env({{"PYTHONDONTWRITEBYTECODE": "1", "AGENTEAZY_DB_PATH": "/data/agenteazy-registry.db"}})
    .workdir("/app")
)


@app.function(
    image=image,
    timeout=300,
    memory=512,
    cpu=1.0,
    volumes={{"/data": volume}},
    allow_concurrent_inputs=100,
)
@modal.asgi_app()
def serve():
    import importlib.util
    import sys as _sys

    spec = importlib.util.spec_from_file_location("registry", "/app/registry.py")
    mod = importlib.util.module_from_spec(spec)
    _sys.modules["registry"] = mod
    spec.loader.exec_module(mod)
    return mod.app
'''


def _parse_modal_url(output: str) -> str:
    """Extract the deployed URL from modal deploy output."""
    urls = re.findall(r"https://[^\s]+\.modal\.run[^\s]*", output)
    if urls:
        for url in urls:
            if MODAL_APP_NAME in url or "registry" in url:
                return url.rstrip(".")
        return urls[0].rstrip(".")
    return f"https://<workspace>--{MODAL_APP_NAME}-serve.modal.run (check Modal dashboard for exact URL)"
