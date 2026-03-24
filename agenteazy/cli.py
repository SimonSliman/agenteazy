"""AgentEazy CLI - Turn any GitHub repo into an AI agent in one command."""

import json
import os
import shutil
import subprocess
import sys
import traceback
import urllib.request
import urllib.error
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agenteazy.analyzer import analyze_repo, DetectedFunction
from agenteazy.local_deployer import deploy_local, test_agent
from agenteazy.modal_deployer import (
    check_modal_auth,
    deploy_to_modal,
    get_agent_logs,
    list_deployed_agents,
    sanitize_agent_name,
    stop_agent,
    upload_to_volume,
)
from agenteazy.generator import generate_agent_json, save_agent_json, record_deploy
from agenteazy.wrapper_template import generate_wrapper, validate_wrapper

# Global verbose flag — set via callback
_verbose = False

app = typer.Typer(
    name="agenteazy",
    help="Turn any GitHub repo into an AI agent in one command.",
    add_completion=False,
)
registry_app = typer.Typer(help="Manage the agent registry server.")
app.add_typer(registry_app, name="registry")

gateway_app = typer.Typer(help="Manage the single gateway endpoint.")
app.add_typer(gateway_app, name="gateway")

console = Console()


@app.callback()
def main_callback(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full tracebacks for debugging"),
):
    """AgentEazy CLI."""
    global _verbose
    _verbose = verbose


def _handle_error(e: Exception, context: str = "") -> None:
    """Print a user-friendly error message. Show traceback only with --verbose."""
    prefix = f" during {context}" if context else ""
    error_msg = str(e)

    # Strip RuntimeError wrapper if the message is already descriptive
    if error_msg:
        console.print(f"[bold red]Error{prefix}:[/bold red] {error_msg}")
    else:
        console.print(f"[bold red]Error{prefix}:[/bold red] {type(e).__name__}")

    if _verbose:
        console.print("\n[dim]Full traceback:[/dim]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


# ── Helper: register with registry ──────────────────────────────────

def _register_with_registry(registry_url: str, agent_config: dict, deploy_url: str, analysis) -> bool:
    """POST agent details to the registry. Returns True on success."""
    from agenteazy.config import get_api_key

    entry = agent_config.get("entry", {})
    payload = {
        "name": agent_config.get("name", analysis.repo_name),
        "description": agent_config.get("description", ""),
        "url": deploy_url,
        "language": analysis.language,
        "verbs": agent_config.get("verbs", []),
        "entry_function": entry.get("function", ""),
        "entry_file": entry.get("file", ""),
        "tags": agent_config.get("tags", []),
    }
    api_key = get_api_key()
    if api_key:
        payload["owner_api_key"] = api_key
    data = json.dumps(payload).encode()
    url = f"{registry_url.rstrip('/')}/registry/register"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        console.print(f"[bold green]Registered[/bold green] with registry: {result}")
        return True
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Could not register with registry: {e}")
        return False


def _parse_entry_override(entry_str: str, local_path: str) -> DetectedFunction:
    """
    Parse --entry flag value into a DetectedFunction.

    Formats:
      file.py:function_name          -> top-level function
      file.py:ClassName.method_name  -> class method
    """
    import ast as _ast

    if ":" not in entry_str:
        raise typer.BadParameter(
            f"Invalid --entry format: '{entry_str}'. "
            f"Use 'file.py:function_name' or 'file.py:ClassName.method_name'."
        )

    file_part, func_part = entry_str.split(":", 1)
    class_name = None
    func_name = func_part

    if "." in func_part:
        class_name, func_name = func_part.split(".", 1)

    # Verify file exists
    full_path = os.path.join(local_path, file_part)
    if not os.path.isfile(full_path):
        raise typer.BadParameter(f"File not found: {file_part} (in {local_path})")

    # Verify function/method exists via AST
    try:
        source = open(full_path, encoding="utf-8", errors="ignore").read()
        tree = _ast.parse(source)
    except SyntaxError as e:
        raise typer.BadParameter(f"Syntax error in {file_part}: {e}")

    if class_name:
        # Find the class, then the method
        found_class = False
        found_method = False
        args = []
        docstring = None
        has_return = False
        line_number = 0
        for node in _ast.iter_child_nodes(tree):
            if isinstance(node, _ast.ClassDef) and node.name == class_name:
                found_class = True
                for item in node.body:
                    if isinstance(item, _ast.FunctionDef) and item.name == func_name:
                        found_method = True
                        args = [a.arg for a in item.args.args if a.arg not in ("self", "cls")]
                        has_return = any(
                            isinstance(c, _ast.Return) and c.value is not None
                            for c in _ast.walk(item)
                        )
                        docstring = _ast.get_docstring(item)
                        line_number = item.lineno
                        break
                break
        if not found_class:
            raise typer.BadParameter(f"Class '{class_name}' not found in {file_part}")
        if not found_method:
            raise typer.BadParameter(f"Method '{func_name}' not found in class '{class_name}' in {file_part}")
    else:
        # Find top-level function
        found = False
        args = []
        docstring = None
        has_return = False
        line_number = 0
        for node in _ast.iter_child_nodes(tree):
            if isinstance(node, _ast.FunctionDef) and node.name == func_name:
                found = True
                args = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
                has_return = any(
                    isinstance(c, _ast.Return) and c.value is not None
                    for c in _ast.walk(node)
                )
                docstring = _ast.get_docstring(node)
                line_number = node.lineno
                break
        if not found:
            raise typer.BadParameter(f"Function '{func_name}' not found in {file_part}")

    return DetectedFunction(
        name=func_name,
        file=file_part,
        args=args,
        has_return=has_return,
        docstring=docstring,
        line_number=line_number,
        class_name=class_name,
    )


def _print_curl_example(analysis, base_url, agent_name, prefix=""):
    """Print a ready-to-paste curl command using detected entry point args."""
    entry = analysis.suggested_entry
    deploy_url = f"{base_url}/agent/{agent_name}/"

    if entry and entry.args:
        # Build example data from arg names
        example_data = {}
        for arg in entry.args[:5]:  # Limit to first 5 args
            if arg in ("text", "s", "source", "html", "xml_input", "content"):
                example_data[arg] = "hello world"
            elif arg in ("password", "passwd"):
                example_data[arg] = "test123"
            elif arg in ("url", "uri", "link"):
                example_data[arg] = "https://example.com"
            elif arg in ("number", "num", "n"):
                example_data[arg] = 42
            elif arg in ("items", "values", "list"):
                example_data[arg] = ["item1", "item2"]
            else:
                example_data[arg] = f"your_{arg}_here"

        data_str = json.dumps({"verb": "DO", "payload": {"data": example_data}})

        console.print(f"\n{prefix}[dim]Try it:[/dim]")
        console.print(f"  curl -s -X POST {deploy_url} \\")
        console.print(f"    -H 'Content-Type: application/json' \\")
        console.print(f"    -d '{data_str}' | python3 -m json.tool")
        console.print()
    else:
        console.print(f"\n{prefix}[dim]Try it:[/dim]")
        console.print(f"  curl -s -X POST {deploy_url} \\")
        console.print(f"    -H 'Content-Type: application/json' \\")
        console.print(f"    -d '{{\"verb\":\"DO\",\"payload\":{{\"data\":{{}}}}}}' | python3 -m json.tool")
        console.print()


def _print_fit_warnings(analysis):
    """Check for patterns that suggest the repo may not be a good fit."""
    fit_warnings = []
    if analysis.errors:
        for err in analysis.errors:
            if "subprocess" in err.lower():
                fit_warnings.append("Uses subprocess — may need system dependencies")
            if "flask" in err.lower() or "fastapi" in err.lower():
                fit_warnings.append("This is a web framework — it already has endpoints. Use --entry to specify a utility function.")

    # Check if detected entry looks like an HTTP client function
    if analysis.suggested_entry:
        entry_name = analysis.suggested_entry.name.lower()
        if entry_name in ("get", "post", "put", "delete", "request", "fetch"):
            fit_warnings.append("Detected entry looks like an HTTP client function. This repo may make outbound network calls.")

    if fit_warnings:
        console.print(f"\n[yellow]Repo fit warnings:[/yellow]")
        for w in fit_warnings:
            console.print(f"  [yellow]![/yellow] {w}")
        console.print()


# ── Commands ─────────────────────────────────────────────────────────

@app.command()
def analyze(repo_url: str = typer.Argument(..., help="GitHub repo URL or user/repo shorthand")):
    """Clone and analyze a GitHub repo, showing detected structure."""
    console.print(f"\n[bold blue]Analyzing[/bold blue] {repo_url}...\n")

    try:
        analysis = analyze_repo(repo_url)
    except Exception as e:
        _handle_error(e, "analysis")
        raise typer.Exit(code=1)

    if analysis.errors:
        for err in analysis.errors:
            console.print(f"[yellow]Warning:[/yellow] {err}")
        if not analysis.language:
            console.print("\n[dim]Cannot continue without a supported language.[/dim]")
            raise typer.Exit(code=1)

    _print_fit_warnings(analysis)

    # Summary table
    table = Table(title=f"Analysis: {analysis.repo_name}", show_header=False)
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    table.add_row("Language", analysis.language or "unknown")
    table.add_row("Python files", str(len(analysis.python_files)))
    table.add_row("Total files", str(analysis.total_files))
    table.add_row("Dependencies", str(len(analysis.dependencies)))

    if analysis.dependencies:
        table.add_row("Top deps", ", ".join(analysis.dependencies[:8]))

    table.add_row("Functions found", str(len(analysis.functions)))

    if analysis.suggested_entry:
        entry = analysis.suggested_entry
        table.add_row(
            "Suggested entry",
            f"{entry.name}({', '.join(entry.args)}) in {entry.file}",
        )
    else:
        table.add_row("Suggested entry", "[yellow]none found[/yellow]")

    table.add_row("Has agent.json", "yes" if analysis.has_agent_json else "no")

    console.print(table)
    console.print()


@app.command()
def wrap(
    repo_url: str = typer.Argument(..., help="GitHub repo URL or user/repo shorthand"),
    price: Optional[int] = typer.Option(None, "--price", help="Credits per call (adds pricing to agent.json)"),
    entry: Optional[str] = typer.Option(None, "--entry", help="Override entry point: 'file.py:func' or 'file.py:Class.method'"),
):
    """Analyze a repo, generate agent.json and a FastAPI wrapper."""
    console.print(f"\n[bold blue]Wrapping[/bold blue] {repo_url}...\n")

    # Step 1: Analyze
    console.print("[dim]Step 1/3: Analyzing repo...[/dim]")
    try:
        analysis = analyze_repo(repo_url)
    except Exception as e:
        _handle_error(e, "analysis")
        raise typer.Exit(code=1)

    if analysis.errors:
        for err in analysis.errors:
            console.print(f"[yellow]Warning:[/yellow] {err}")

    _print_fit_warnings(analysis)

    # Apply --entry override if provided
    if entry:
        try:
            override = _parse_entry_override(entry, analysis.local_path)
            analysis.suggested_entry = override
            entry_display = f"{override.file} -> {override.class_name + '.' if override.class_name else ''}{override.name}({', '.join(override.args)})"
            console.print(f"[bold yellow]Using specified entry:[/bold yellow] {entry_display}")
        except typer.BadParameter as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            raise typer.Exit(code=1)
    elif analysis.suggested_entry:
        se = analysis.suggested_entry
        entry_display = f"{se.file} -> {se.class_name + '.' if se.class_name else ''}{se.name}({', '.join(se.args)})"
        console.print(f"[bold yellow]Auto-detected entry:[/bold yellow] {entry_display}")

    if not analysis.suggested_entry:
        console.print(
            "[bold red]Error:[/bold red] No suitable entry point found.\n"
            "[dim]  Ensure your repo has Python files with top-level function definitions.[/dim]"
        )
        raise typer.Exit(code=1)

    # Save everything to ./agenteazy-output/{repo_name}/
    output_dir = os.path.join(".", "agenteazy-output", analysis.repo_name)
    os.makedirs(output_dir, exist_ok=True)

    # Step 2: Generate agent.json (with version auto-increment)
    console.print("[dim]Step 2/3: Generating agent.json...[/dim]")
    agent_config = generate_agent_json(analysis, output_dir=output_dir)

    # Inject pricing if --price flag was provided
    if price and price > 0:
        agent_config["pricing"] = {"model": "per_call", "credits_per_call": price}

    # Step 3: Generate wrapper
    console.print("[dim]Step 3/3: Generating FastAPI wrapper...[/dim]")
    try:
        wrapper_code = generate_wrapper(agent_config, analysis.local_path)
    except ValueError as e:
        _handle_error(e, "wrapper generation")
        raise typer.Exit(code=1)

    if not validate_wrapper(wrapper_code):
        console.print("[bold red]Error:[/bold red] Generated wrapper has syntax errors.")
        raise typer.Exit(code=1)

    # Save agent.json
    agent_path = save_agent_json(agent_config, output_dir)

    # Save wrapper.py
    wrapper_path = os.path.join(output_dir, "wrapper.py")
    with open(wrapper_path, "w") as f:
        f.write(wrapper_code)

    # Copy repo source into output_dir/repo/
    repo_dest = os.path.join(output_dir, "repo")
    if os.path.exists(repo_dest):
        shutil.rmtree(repo_dest)
    shutil.copytree(analysis.local_path, repo_dest, dirs_exist_ok=True)

    # Save requirements.txt
    reqs_path = os.path.join(output_dir, "requirements.txt")
    wrapper_deps = ["fastapi>=0.100.0", "uvicorn>=0.23.0"]
    all_deps = analysis.dependencies + wrapper_deps
    with open(reqs_path, "w") as f:
        f.write("\n".join(all_deps) + "\n")

    # Print summary
    console.print()
    console.print(Panel.fit(
        f"[bold green]Done![/bold green] Output saved to [cyan]{output_dir}/[/cyan]\n\n"
        f"  agent.json   - Agent configuration\n"
        f"  wrapper.py   - FastAPI server\n"
        f"  requirements.txt - All dependencies\n\n"
        f"[bold]To test locally:[/bold]\n"
        f"  cd {output_dir}\n"
        f"  pip install -r requirements.txt\n"
        f"  python wrapper.py",
        title="AgentEazy",
    ))

    # Print a ready-to-paste curl example
    agent_name_sanitized = sanitize_agent_name(analysis.repo_name)
    _print_curl_example(analysis, "http://localhost:8000", agent_name_sanitized)


@app.command()
def deploy(
    repo_url: str = typer.Argument(..., help="GitHub repo URL, user/repo shorthand, or local path"),
    local: bool = typer.Option(False, "--local", help="Deploy locally instead of to Modal"),
    self_host: bool = typer.Option(False, "--self-host", help="Skip gateway upload — host the agent yourself and register its URL"),
    host_url: str = typer.Option(None, "--host-url", help="Your agent's public URL (used with --self-host)"),
    port: int = typer.Option(8000, "--port", "-p", help="Port for the local server (only with --local)"),
    registry: Optional[str] = typer.Option(None, "--registry", help="Registry URL to auto-register after deploy"),
    legacy: bool = typer.Option(False, "--legacy", help="Use legacy per-agent Modal app instead of gateway"),
    price: Optional[int] = typer.Option(None, "--price", help="Credits per call (adds pricing to agent.json)"),
    entry: Optional[str] = typer.Option(None, "--entry", help="Override entry point: 'file.py:func' or 'file.py:Class.method'"),
    name: Optional[str] = typer.Option(None, "--name", help="Override agent name (default: repo name)"),
):
    """Analyze, wrap, and deploy an agent. Uploads to gateway volume by default."""
    from agenteazy.config import get_gateway_url, get_registry_url, DEFAULT_REGISTRY_URL, DEFAULT_GATEWAY_URL

    console.print(f"\n[bold blue]Deploying[/bold blue] {repo_url}...\n")

    # Step 1: Analyze
    console.print("[dim]Step 1/4: Analyzing repo...[/dim]")
    try:
        analysis = analyze_repo(repo_url)
    except Exception as e:
        _handle_error(e, "analysis")
        raise typer.Exit(code=1)

    if analysis.errors:
        for err in analysis.errors:
            console.print(f"[yellow]Warning:[/yellow] {err}")

    _print_fit_warnings(analysis)

    # Apply --entry override if provided
    if entry:
        try:
            override = _parse_entry_override(entry, analysis.local_path)
            analysis.suggested_entry = override
            entry_display = f"{override.file} -> {override.class_name + '.' if override.class_name else ''}{override.name}({', '.join(override.args)})"
            console.print(f"[bold yellow]Using specified entry:[/bold yellow] {entry_display}")
        except typer.BadParameter as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            raise typer.Exit(code=1)
    elif analysis.suggested_entry:
        se = analysis.suggested_entry
        entry_display = f"{se.file} -> {se.class_name + '.' if se.class_name else ''}{se.name}({', '.join(se.args)})"
        console.print(f"[bold yellow]Auto-detected entry:[/bold yellow] {entry_display}")

    if not analysis.suggested_entry:
        console.print(
            "[bold red]Error:[/bold red] No suitable entry point found.\n"
            "[dim]  Ensure your repo has Python files with top-level function definitions.[/dim]"
        )
        raise typer.Exit(code=1)

    # Resolve agent name: --name flag overrides repo_name
    agent_name = name if name else analysis.repo_name

    # Step 2: Generate agent.json + wrapper
    output_dir = os.path.join(".", "agenteazy-output", agent_name)
    os.makedirs(output_dir, exist_ok=True)

    console.print("[dim]Step 2/4: Generating agent.json and wrapper...[/dim]")
    agent_config = generate_agent_json(analysis, output_dir=output_dir)

    # Inject pricing if --price flag was provided
    if price and price > 0:
        agent_config["pricing"] = {"model": "per_call", "credits_per_call": price}

    try:
        wrapper_code = generate_wrapper(agent_config, analysis.local_path)
    except ValueError as e:
        _handle_error(e, "wrapper generation")
        raise typer.Exit(code=1)

    if not validate_wrapper(wrapper_code):
        console.print("[bold red]Error:[/bold red] Generated wrapper has syntax errors.")
        raise typer.Exit(code=1)

    save_agent_json(agent_config, output_dir)

    wrapper_path = os.path.join(output_dir, "wrapper.py")
    with open(wrapper_path, "w") as f:
        f.write(wrapper_code)

    # Copy repo source into output_dir/repo/
    repo_dest = os.path.join(output_dir, "repo")
    if os.path.exists(repo_dest):
        shutil.rmtree(repo_dest)
    shutil.copytree(analysis.local_path, repo_dest, dirs_exist_ok=True)

    reqs_path = os.path.join(output_dir, "requirements.txt")
    wrapper_deps = ["fastapi>=0.100.0", "uvicorn>=0.23.0"]
    all_deps = analysis.dependencies + wrapper_deps
    with open(reqs_path, "w") as f:
        f.write("\n".join(all_deps) + "\n")

    if self_host:
        # Self-host mode: skip Modal upload entirely
        console.print(f"\n[bold green]Agent wrapped![/bold green] Output: {output_dir}/\n")

        registry_url = registry or get_registry_url() or DEFAULT_REGISTRY_URL
        if host_url:
            # Register with the provided URL
            if not registry_url:
                from agenteazy.config import DEFAULT_REGISTRY_URL
                registry_url = DEFAULT_REGISTRY_URL
            agent_config["name"] = agent_name
            _register_with_registry(registry_url, agent_config, host_url.rstrip("/"), analysis)
            console.print(f"[bold green]Registered![/bold green] Your agent is live at: {host_url}")
        else:
            # Print self-host instructions
            console.print("[bold]To make your agent live:[/bold]\n")
            console.print(f"  1. Run it:")
            console.print(f"     cd {output_dir}")
            console.print(f"     pip install -r requirements.txt")
            console.print(f"     python wrapper.py")
            console.print(f"")
            console.print(f"  2. Make it publicly accessible (ngrok, Fly.io, Railway, Render, etc.)")
            console.print(f"")
            console.print(f"  3. Register it:")
            console.print(f"     agenteazy deploy {repo_url} --self-host --host-url https://your-public-url.com")
            console.print(f"")

            # Print curl example for self-host
            _print_curl_example(analysis, "https://your-public-url.com", sanitize_agent_name(agent_name), prefix="  4. ")

            registry_url_display = registry_url or "https://your-registry-url"
            console.print(f"  Or register manually:")
            console.print(f'     curl -X POST {registry_url_display}/registry/register \\')
            console.print(f'       -H "Content-Type: application/json" \\')
            console.print(f'       -d \'{{"name": "{agent_config["name"]}", "url": "https://your-url.com", "language": "python", "verbs": ["ASK", "DO"]}}\'')
        return

    if local:
        # Local deployment path
        console.print("[dim]Step 3/4: Installing dependencies (fastapi, uvicorn)...[/dim]")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "fastapi", "uvicorn"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as e:
            console.print(f"[bold red]Error installing deps:[/bold red] {e}")
            raise typer.Exit(code=1)

        console.print("[dim]Step 4/4: Starting local server...[/dim]")
        try:
            deploy_local(output_dir, port=port)
        except FileNotFoundError as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            raise typer.Exit(code=1)
        except KeyboardInterrupt:
            pass
    elif legacy:
        # Legacy: one Modal app per agent
        console.print("[dim]Step 3/4: Deploying to Modal (legacy per-agent app)...[/dim]")
        try:
            url = deploy_to_modal(output_dir, agent_name)
        except Exception as e:
            _handle_error(e, "Modal deploy")
            raise typer.Exit(code=1)

        record_deploy(
            name=agent_config["name"],
            version=agent_config["version"],
            url=url,
            modal_app_name=agent_name,
        )

        console.print()
        console.print(Panel.fit(
            f"[bold green]Deployed![/bold green] Agent is live at:\n\n"
            f"  [cyan]{url}[/cyan]\n\n"
            f"Version: {agent_config['version']}\n\n"
            f"Endpoints:\n"
            f"  GET  {url}/\n"
            f"  GET  {url}/health\n"
            f"  POST {url}/ask\n"
            f"  POST {url}/do\n"
            f"  GET  {url}/.well-known/agent.json",
            title="AgentEazy - Modal Deploy (Legacy)",
        ))

        if registry:
            console.print(f"\n[dim]Registering with registry at {registry}...[/dim]")
            agent_config["name"] = agent_name
            _register_with_registry(registry, agent_config, url, analysis)
    else:
        # Gateway mode: upload to shared volume
        from agenteazy.config import DEFAULT_GATEWAY_URL
        gateway_url = get_gateway_url() or DEFAULT_GATEWAY_URL

        console.print("[dim]Step 3/4: Uploading to gateway volume...[/dim]")
        try:
            url = upload_to_volume(output_dir, agent_name, gateway_url)
        except Exception as e:
            error_msg = str(e).lower()
            if "auth" in error_msg or "modal" in error_msg or "credential" in error_msg or "token" in error_msg:
                console.print(f"\n[yellow]Gateway upload requires platform credentials.[/yellow]")
                console.print(f"[yellow]Your agent is wrapped and ready — you can self-host it:[/yellow]\n")
                console.print(f"  cd {output_dir}")
                console.print(f"  pip install -r requirements.txt")
                console.print(f"  python wrapper.py")
                console.print(f"\n  Then register with: agenteazy deploy {repo_url} --self-host --host-url https://your-url.com\n")
                console.print(f"[dim]Or run locally with: agenteazy deploy {repo_url} --local[/dim]")
                return
            else:
                _handle_error(e, "volume upload")
                raise typer.Exit(code=1)

        agent_name_sanitized = sanitize_agent_name(agent_name)
        gw = gateway_url.rstrip("/")

        record_deploy(
            name=agent_config["name"],
            version=agent_config["version"],
            url=url,
            modal_app_name=agent_name_sanitized,
        )

        console.print()
        console.print(Panel.fit(
            f"[bold green]Deployed![/bold green] Agent uploaded to gateway:\n\n"
            f"  [cyan]{url}[/cyan]\n\n"
            f"Version: {agent_config['version']}\n\n"
            f"Endpoints:\n"
            f"  GET  {gw}/agent/{agent_name_sanitized}\n"
            f"  POST {gw}/agent/{agent_name_sanitized}/ask\n"
            f"  POST {gw}/agent/{agent_name_sanitized}/do\n\n"
            f"Gateway: {gw}/agents",
            title="AgentEazy - Gateway Deploy",
        ))

        # Print a ready-to-paste curl example
        _print_curl_example(analysis, gw, agent_name_sanitized)

        # Auto-register: use --registry flag, or fall back to configured registry
        registry_url = registry or get_registry_url() or DEFAULT_REGISTRY_URL
        if registry_url:
            console.print(f"\n[dim]Registering with registry at {registry_url}...[/dim]")
            agent_config["name"] = agent_name
            _register_with_registry(registry_url, agent_config, f"{gw}/agent/{agent_name_sanitized}", analysis)
        else:
            console.print("\n[dim]No registry URL configured — skipping registration.[/dim]")
            console.print("[dim]  Set one with: agenteazy registry deploy[/dim]")


@app.command()
def register(
    name: str = typer.Argument(..., help="Agent name"),
    url: str = typer.Argument(..., help="Agent's public URL"),
    description: str = typer.Option("", "--description", "-d", help="Agent description"),
    price: int = typer.Option(0, "--price", help="Credits per call (0 = free)"),
):
    """Register an externally hosted agent in the AgentEazy registry."""
    from agenteazy.config import get_registry_url, get_api_key, DEFAULT_REGISTRY_URL

    registry_url = get_registry_url() or DEFAULT_REGISTRY_URL
    api_key = get_api_key()

    data = {
        "name": name,
        "description": description,
        "url": url.rstrip("/"),
        "language": "python",
        "verbs": ["ASK", "DO"],
    }
    if api_key:
        data["owner_api_key"] = api_key
    if price > 0:
        data["pricing"] = {"model": "per_call", "credits_per_call": price}

    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{registry_url.rstrip('/')}/registry/register",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        console.print(f"[bold green]Registered![/bold green] Agent '{name}' is now discoverable at {registry_url}")
        console.print(f"  Call it: curl -X POST {url}/ -d '{{\"verb\":\"DO\",\"payload\":{{\"data\":{{}}}}}}' -H 'Content-Type: application/json'")
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        console.print(f"[bold red]Registration failed:[/bold red] {e.code} {body}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command()
def test(
    url: str = typer.Option("http://localhost:8000", "--url", "-u", help="Base URL of running agent"),
):
    """Test all endpoints of a running agent."""
    console.print(f"\n[bold blue]Testing agent at[/bold blue] {url}\n")
    try:
        results = test_agent(url)
    except Exception as e:
        _handle_error(e, "testing")
        console.print("[dim]  Is the agent running? Try: agenteazy deploy <repo> --local[/dim]")
        raise typer.Exit(code=1)

    all_passed = all(r["passed"] for r in results.values())
    if all_passed:
        console.print("[bold green]All endpoints passed![/bold green]\n")
    else:
        failed = [name for name, r in results.items() if not r["passed"]]
        console.print(f"[bold red]Failed endpoints:[/bold red] {', '.join(failed)}\n")
        raise typer.Exit(code=1)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    registry: Optional[str] = typer.Option(None, "--registry", help="Registry server URL"),
):
    """Search for agents in the registry."""
    from agenteazy.config import get_registry_url, DEFAULT_REGISTRY_URL

    if not registry:
        registry = get_registry_url() or DEFAULT_REGISTRY_URL
    url = f"{registry.rstrip('/')}/registry/search?q={urllib.request.quote(query)}"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        agents = json.loads(resp.read())
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] Could not reach registry at {registry}")
        console.print(f"[dim]  Is the registry running? Start it with: agenteazy registry start[/dim]")
        if _verbose:
            console.print(f"[dim]  Detail: {e}[/dim]")
        raise typer.Exit(code=1)

    if not agents:
        console.print(f"\n[yellow]No agents found matching[/yellow] '{query}'\n")
        return

    table = Table(title=f"Search results for '{query}'")
    table.add_column("Name", style="bold cyan")
    table.add_column("Description")
    table.add_column("URL", style="dim")
    table.add_column("Language")
    table.add_column("Verbs", style="green")
    table.add_column("Tags", style="magenta")

    for a in agents:
        table.add_row(
            a.get("name", ""),
            a.get("description", ""),
            a.get("url", ""),
            a.get("language", ""),
            ", ".join(a.get("verbs", [])),
            ", ".join(a.get("tags", [])),
        )

    console.print()
    console.print(table)
    console.print()


@app.command(name="list")
def list_agents(
    registry: Optional[str] = typer.Option(None, "--registry", help="Registry server URL"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max agents to show"),
    offset: int = typer.Option(0, "--offset", help="Offset for pagination"),
):
    """List all agents in the registry."""
    from agenteazy.config import get_registry_url, DEFAULT_REGISTRY_URL

    if not registry:
        registry = get_registry_url() or DEFAULT_REGISTRY_URL
    url = f"{registry.rstrip('/')}/registry/all?limit={limit}&offset={offset}"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        agents = json.loads(resp.read())
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] Could not reach registry at {registry}")
        console.print(f"[dim]  Is the registry running? Start it with: agenteazy registry start[/dim]")
        if _verbose:
            console.print(f"[dim]  Detail: {e}[/dim]")
        raise typer.Exit(code=1)

    if not agents:
        console.print("\n[yellow]No agents registered yet.[/yellow]\n")
        return

    table = Table(title=f"Registered Agents ({len(agents)})")
    table.add_column("Name", style="bold cyan")
    table.add_column("Description")
    table.add_column("URL", style="dim")
    table.add_column("Language")
    table.add_column("Verbs", style="green")
    table.add_column("Tags", style="magenta")
    table.add_column("Status", style="bold")

    for a in agents:
        status = a.get("status", "unknown")
        status_style = "green" if status == "active" else "red"
        table.add_row(
            a.get("name", ""),
            a.get("description", ""),
            a.get("url", ""),
            a.get("language", ""),
            ", ".join(a.get("verbs", [])),
            ", ".join(a.get("tags", [])),
            f"[{status_style}]{status}[/{status_style}]",
        )

    console.print()
    console.print(table)
    console.print()


# ── Modal management commands ────────────────────────────────────────

@app.command()
def status():
    """Show Modal auth status and all deployed agents."""
    console.print()

    # Auth check
    authenticated = check_modal_auth()
    if authenticated:
        console.print("[bold green]Modal auth:[/bold green] authenticated")
    else:
        console.print("[bold red]Modal auth:[/bold red] not authenticated")
        console.print("[dim]Run 'modal setup' to authenticate.[/dim]")
        console.print()
        raise typer.Exit(code=1)

    # List deployed agents
    console.print()
    try:
        agents = list_deployed_agents()
    except RuntimeError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    if not agents:
        console.print("[yellow]No deployed agents found.[/yellow]\n")
        return

    table = Table(title=f"Deployed Modal Agents ({len(agents)})")
    table.add_column("Name", style="bold cyan")
    table.add_column("App ID", style="dim")
    table.add_column("State", style="bold")

    for a in agents:
        state = a.get("state", "unknown")
        state_style = "green" if state.lower() in ("deployed", "running") else "yellow"
        table.add_row(
            a.get("name", ""),
            a.get("app_id", ""),
            f"[{state_style}]{state}[/{state_style}]",
        )

    console.print(table)
    console.print()


@app.command()
def stop(
    name: str = typer.Argument(..., help="Name of the Modal app to stop"),
):
    """Stop a deployed Modal agent."""
    console.print(f"\n[bold blue]Stopping[/bold blue] '{name}'...\n")

    if stop_agent(name):
        console.print(f"[bold green]Stopped[/bold green] '{name}' successfully.\n")
    else:
        console.print(f"[bold red]Error:[/bold red] Failed to stop '{name}'. Check the app name and try again.\n")
        raise typer.Exit(code=1)


@app.command()
def logs(
    name: str = typer.Argument(..., help="Name of the Modal app to get logs for"),
):
    """Show recent logs for a deployed Modal agent."""
    console.print(f"\n[bold blue]Logs for[/bold blue] '{name}':\n")

    try:
        log_output = get_agent_logs(name)
        console.print(log_output)
    except RuntimeError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)


# ── Batch and cleanup commands ────────────────────────────────────────

@app.command(name="batch-deploy")
def batch_deploy_cmd(
    repos_file: str = typer.Argument(..., help="Path to a text file with one GitHub URL per line"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Analyze only, don't wrap or deploy"),
    wrap_only: bool = typer.Option(False, "--wrap-only", help="Wrap all repos but don't deploy to Modal"),
    price: int = typer.Option(0, "--price", help="Default credits per call for all agents (0 = free)"),
    output_dir: str = typer.Option("./agenteazy-output", "--output-dir", help="Base output directory"),
    max_failures: int = typer.Option(10, "--max-failures", help="Stop after N consecutive failures"),
    skip_existing: bool = typer.Option(False, "--skip-existing", help="Skip repos that already have an output dir"),
    entry_file: Optional[str] = typer.Option(None, "--entry-file", help="JSON file mapping repo names to entry points"),
):
    """Batch deploy agents from a list of GitHub repos with graceful failure handling."""
    from agenteazy.batch import (
        batch_process, parse_repos_file, load_entry_overrides,
        save_batch_report, print_batch_summary,
    )

    if not os.path.isfile(repos_file):
        console.print(f"[bold red]Error:[/bold red] File not found: {repos_file}")
        raise typer.Exit(code=1)

    repos = parse_repos_file(repos_file)
    if not repos:
        console.print("[yellow]No repos found in file.[/yellow]")
        raise typer.Exit(code=1)

    # Determine mode
    if dry_run:
        mode = "dry-run"
    elif wrap_only:
        mode = "wrap-only"
    else:
        mode = "full"

    # Load entry overrides
    entry_overrides = {}
    if entry_file:
        if not os.path.isfile(entry_file):
            console.print(f"[bold red]Error:[/bold red] Entry file not found: {entry_file}")
            raise typer.Exit(code=1)
        entry_overrides = load_entry_overrides(entry_file)

    console.print(f"\n[bold blue]Batch Deploy[/bold blue] — {len(repos)} repos, mode: {mode}\n")

    report = batch_process(
        repos=repos,
        mode=mode,
        price=price,
        output_base=output_dir,
        max_consecutive_failures=max_failures,
        skip_existing=skip_existing,
        entry_overrides=entry_overrides,
    )

    report_path = save_batch_report(report, output_dir, mode)
    print_batch_summary(report, output_dir, report_path)


@app.command(name="batch-analyze")
def batch_analyze_cmd(
    repos_file: str = typer.Argument(..., help="Path to a text file with one GitHub URL per line"),
    output_dir: str = typer.Option("./agenteazy-output", "--output-dir", help="Base output directory"),
):
    """Analyze multiple repos without wrapping. Shows a summary table."""
    from agenteazy.batch import parse_repos_file, batch_analyze

    if not os.path.isfile(repos_file):
        console.print(f"[bold red]Error:[/bold red] File not found: {repos_file}")
        raise typer.Exit(code=1)

    repos = parse_repos_file(repos_file)
    if not repos:
        console.print("[yellow]No repos found in file.[/yellow]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold blue]Batch Analyze[/bold blue] — {len(repos)} repos\n")
    batch_analyze(repos, output_base=output_dir)


@app.command()
def cleanup(
    all_apps: bool = typer.Option(False, "--all", help="Remove all Modal apps without prompting"),
):
    """List deployed Modal apps and optionally remove them."""
    console.print()

    if not check_modal_auth():
        console.print("[bold red]Modal auth:[/bold red] not authenticated")
        console.print("[dim]Run 'modal setup' to authenticate.[/dim]\n")
        raise typer.Exit(code=1)

    try:
        agents = list_deployed_agents()
    except RuntimeError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    if not agents:
        console.print("[yellow]No deployed Modal apps found.[/yellow]\n")
        return

    table = Table(title=f"Deployed Modal Apps ({len(agents)})")
    table.add_column("#", style="dim")
    table.add_column("Name", style="bold cyan")
    table.add_column("App ID", style="dim")
    table.add_column("State")

    for i, a in enumerate(agents, 1):
        table.add_row(str(i), a["name"], a.get("app_id", ""), a.get("state", "unknown"))

    console.print(table)
    console.print()

    if all_apps:
        console.print("[bold red]Removing all Modal apps...[/bold red]\n")
        for a in agents:
            name = a["name"]
            if stop_agent(name):
                console.print(f"  [green]Stopped[/green] {name}")
            else:
                console.print(f"  [red]Failed to stop[/red] {name}")
        console.print()
    else:
        console.print("[dim]Use --all to remove all apps, or use 'agenteazy stop <name>' individually.[/dim]\n")


# ── Registry subcommands ─────────────────────────────────────────────

@registry_app.command("start")
def registry_start(
    port: int = typer.Option(8001, "--port", "-p", help="Port for the registry server"),
):
    """Start the agent registry server locally."""
    console.print(f"\n[bold blue]Starting registry server[/bold blue] on port {port}...\n")
    registry_path = os.path.join(os.path.dirname(__file__), "registry.py")
    try:
        subprocess.run(
            [sys.executable, registry_path],
            env={**os.environ, "REGISTRY_PORT": str(port)},
        )
    except KeyboardInterrupt:
        console.print("\n[dim]Registry server stopped.[/dim]")


@registry_app.command("deploy")
def registry_deploy():
    """Deploy the registry to Modal as a public web endpoint with persistent storage."""
    from agenteazy.registry_deployer import deploy_registry
    from agenteazy.config import set_registry_url

    console.print("\n[bold blue]Deploying registry to Modal...[/bold blue]\n")

    try:
        url = deploy_registry()
    except Exception as e:
        _handle_error(e, "registry deploy")
        raise typer.Exit(code=1)

    # Save the URL so other commands can use it
    set_registry_url(url)

    console.print()
    console.print(Panel.fit(
        f"[bold green]Registry deployed![/bold green]\n\n"
        f"  URL: [cyan]{url}[/cyan]\n\n"
        f"Saved to ~/.agenteazy/config.json\n\n"
        f"Use it with:\n"
        f"  agenteazy deploy <repo> --registry {url}",
        title="AgentEazy Registry",
    ))


# ── Gateway subcommands ───────────────────────────────────────────────

@gateway_app.command("deploy")
def gateway_deploy():
    """Deploy the single gateway to Modal. Run this once before deploying agents."""
    from agenteazy.gateway_deployer import deploy_gateway
    from agenteazy.config import set_gateway_url

    console.print("\n[bold blue]Deploying gateway to Modal...[/bold blue]\n")

    try:
        url = deploy_gateway()
    except Exception as e:
        _handle_error(e, "gateway deploy")
        raise typer.Exit(code=1)

    set_gateway_url(url)

    console.print()
    console.print(Panel.fit(
        f"[bold green]Gateway deployed![/bold green]\n\n"
        f"  URL: [cyan]{url}[/cyan]\n\n"
        f"Saved to ~/.agenteazy/config.json\n\n"
        f"Endpoints:\n"
        f"  GET  {url}/health\n"
        f"  GET  {url}/agents\n"
        f"  GET  {url}/agent/{{name}}\n"
        f"  POST {url}/agent/{{name}}/ask\n"
        f"  POST {url}/agent/{{name}}/do\n\n"
        f"Now deploy agents with:\n"
        f"  agenteazy deploy <repo>",
        title="AgentEazy Gateway",
    ))


@gateway_app.command("status")
def gateway_status():
    """Show the current gateway URL and health."""
    from agenteazy.config import get_gateway_url, DEFAULT_GATEWAY_URL

    gateway_url = get_gateway_url() or DEFAULT_GATEWAY_URL

    console.print(f"\n[bold]Gateway URL:[/bold] {gateway_url}")

    # Try health check
    try:
        url = f"{gateway_url.rstrip('/')}/health"
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
        console.print(f"[bold green]Health:[/bold green] {data.get('status', 'ok')}")
    except Exception as e:
        console.print(f"[bold red]Health check failed:[/bold red] {e}")

    # Try listing agents
    try:
        url = f"{gateway_url.rstrip('/')}/agents"
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
        agents = data.get("agents", [])
        count = data.get("count", len(agents))
        console.print(f"[bold]Agents:[/bold] {count}")
        for a in agents:
            console.print(f"  - {a['name']} v{a.get('version', '?')}: {a.get('description', '')}")
    except Exception as e:
        console.print(f"[yellow]Could not list agents:[/yellow] {e}")

    console.print()


# ── Tollbooth CLI commands ────────────────────────────────────────────

@app.command()
def signup(
    github_username: str = typer.Argument(..., help="Your GitHub username"),
    email: str = typer.Option(..., "--email", "-e", help="Your email address"),
):
    """Sign up for an AgentEazy account and get an API key."""
    from agenteazy.config import get_registry_url, set_api_key, DEFAULT_REGISTRY_URL

    registry_url = get_registry_url() or DEFAULT_REGISTRY_URL
    url = f"{registry_url.rstrip('/')}/tollbooth/signup"
    payload = json.dumps({"github_username": github_username, "email": email}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 409:
            console.print("[yellow]Account already exists for this GitHub username.[/yellow]")
            return
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)
    except (urllib.error.URLError, OSError):
        console.print("[bold red]Registry unavailable. Is it running?[/bold red]")
        raise typer.Exit(code=1)

    api_key = data["api_key"]
    set_api_key(api_key)
    console.print(f"[bold green]Welcome![/bold green] Your API key: [cyan]{api_key}[/cyan] (saved to config). You have [bold]50[/bold] starter credits.")


@app.command()
def balance():
    """Check your credit balance."""
    from agenteazy.config import get_registry_url, get_api_key, DEFAULT_REGISTRY_URL

    api_key = get_api_key()
    if not api_key:
        console.print("[yellow]Not signed up yet. Run: agenteazy signup <github_username>[/yellow]")
        return

    registry_url = get_registry_url() or DEFAULT_REGISTRY_URL
    url = f"{registry_url.rstrip('/')}/tollbooth/balance/{api_key}"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            console.print("[bold red]Invalid API key.[/bold red]")
            return
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)
    except (urllib.error.URLError, OSError):
        console.print("[bold red]Registry unavailable. Is it running?[/bold red]")
        raise typer.Exit(code=1)

    table = Table(title=f"Balance for {data.get('github_username', 'unknown')}")
    table.add_column("Field", style="bold cyan")
    table.add_column("Value", justify="right")
    table.add_row("Credits", str(data["credits"]))
    table.add_row("Total Earned", str(data["total_earned"]))
    table.add_row("Total Spent", str(data["total_spent"]))
    console.print()
    console.print(table)
    console.print()


@app.command()
def transactions():
    """Show recent transactions."""
    from agenteazy.config import get_registry_url, get_api_key, DEFAULT_REGISTRY_URL

    api_key = get_api_key()
    if not api_key:
        console.print("[yellow]Not signed up yet. Run: agenteazy signup <github_username>[/yellow]")
        return

    registry_url = get_registry_url() or DEFAULT_REGISTRY_URL
    url = f"{registry_url.rstrip('/')}/tollbooth/transactions/{api_key}"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            console.print("[bold red]Invalid API key.[/bold red]")
            return
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)
    except (urllib.error.URLError, OSError):
        console.print("[bold red]Registry unavailable. Is it running?[/bold red]")
        raise typer.Exit(code=1)

    if not data:
        console.print("\n[yellow]No transactions yet.[/yellow]\n")
        return

    table = Table(title="Recent Transactions")
    table.add_column("Type", style="bold cyan")
    table.add_column("Agent", style="dim")
    table.add_column("Credits", justify="right")
    table.add_column("Timestamp", style="dim")

    for tx in data:
        table.add_row(
            tx.get("type", ""),
            tx.get("agent_name", "") or "-",
            str(tx.get("credits", 0)),
            tx.get("timestamp", ""),
        )

    console.print()
    console.print(table)
    console.print()


@app.command(name="mcp-server")
def mcp_server_cmd(
    registry: str = typer.Option(None, "--registry", help="Registry URL"),
    gateway: str = typer.Option(None, "--gateway", help="Gateway URL"),
):
    """Start an MCP server that exposes AgentEazy agents as tools.

    Use this with Claude Desktop, Cursor, or any MCP-compatible client.

    Claude Desktop config:
        {
            "mcpServers": {
                "agenteazy": {
                    "command": "agenteazy",
                    "args": ["mcp-server"]
                }
            }
        }
    """
    import asyncio

    try:
        from agenteazy.integrations.mcp_server import run_server
    except ImportError:
        console.print("[bold red]MCP SDK not installed.[/bold red]")
        console.print("Install with: [cyan]pip install agenteazy[mcp][/cyan]")
        raise typer.Exit(code=1)

    # Don't print anything to stdout — MCP uses stdio for communication
    # Log to stderr only
    import logging
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    asyncio.run(run_server(
        registry_url=registry,
        gateway_url=gateway,
    ))


@app.command()
def doctor():
    """Check your AgentEazy setup and diagnose common issues."""
    from agenteazy.config import (
        get_api_key, get_registry_url, get_gateway_url,
        DEFAULT_REGISTRY_URL, DEFAULT_GATEWAY_URL,
    )

    console.print("\n[bold]AgentEazy Doctor[/bold]\n")
    all_ok = True

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 9):
        console.print(f"  [green]✓[/green] Python {py_ver}")
    else:
        console.print(f"  [red]✗[/red] Python {py_ver} — need 3.9+")
        all_ok = False

    # 2. Git available
    if shutil.which("git"):
        console.print(f"  [green]✓[/green] Git installed")
    else:
        console.print(f"  [red]✗[/red] Git not found — needed to clone repos")
        all_ok = False

    # 3. API key configured
    api_key = get_api_key()
    if api_key:
        console.print(f"  [green]✓[/green] API key configured ({api_key[:10]}...)")
    else:
        console.print(f"  [yellow]![/yellow] No API key — run: agenteazy signup <username> --email <email>")
        all_ok = False

    # 4. Registry reachable
    registry_url = get_registry_url() or DEFAULT_REGISTRY_URL
    try:
        resp = urllib.request.urlopen(f"{registry_url.rstrip('/')}/registry/stats", timeout=5)
        data = json.loads(resp.read())
        agent_count = data.get("total_agents", 0)
        console.print(f"  [green]✓[/green] Registry reachable ({agent_count} agents)")
    except Exception:
        console.print(f"  [red]✗[/red] Registry unreachable at {registry_url}")
        all_ok = False

    # 5. Gateway reachable
    gateway_url = get_gateway_url() or DEFAULT_GATEWAY_URL
    try:
        urllib.request.urlopen(f"{gateway_url.rstrip('/')}/health", timeout=5)
        console.print(f"  [green]✓[/green] Gateway reachable")
    except Exception:
        console.print(f"  [red]✗[/red] Gateway unreachable at {gateway_url}")
        all_ok = False

    # 6. Modal installed + authenticated (optional)
    modal_installed = shutil.which("modal") is not None
    if modal_installed:
        try:
            result = subprocess.run(["modal", "profile", "current"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                console.print(f"  [green]✓[/green] Modal CLI installed and authenticated")
            else:
                console.print(f"  [yellow]![/yellow] Modal CLI installed but not authenticated — run: modal setup")
                console.print(f"    [dim](Not required — you can use --self-host instead)[/dim]")
        except Exception:
            console.print(f"  [yellow]![/yellow] Modal CLI installed but auth check failed")
    else:
        console.print(f"  [dim]-[/dim] Modal CLI not installed (optional — use --self-host to deploy without Modal)")

    # 7. Check for optional integrations
    integrations = []
    try:
        import langchain_core  # noqa: F401
        integrations.append("LangChain")
    except ImportError:
        pass
    try:
        import crewai  # noqa: F401
        integrations.append("CrewAI")
    except ImportError:
        pass
    try:
        import mcp  # noqa: F401
        integrations.append("MCP")
    except ImportError:
        pass

    if integrations:
        console.print(f"  [green]✓[/green] Integrations: {', '.join(integrations)}")
    else:
        console.print(f"  [dim]-[/dim] No optional integrations (pip install agenteazy[langchain|crewai|mcp])")

    # Summary
    console.print()
    if all_ok:
        console.print("  [bold green]All checks passed![/bold green] Ready to deploy.\n")
    else:
        console.print("  [bold yellow]Some issues found.[/bold yellow] Fix the items marked ✗ above.\n")


if __name__ == "__main__":
    app()
