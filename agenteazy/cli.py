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

from agenteazy.analyzer import analyze_repo
from agenteazy.deployer import deploy_local, test_agent
from agenteazy.modal_deployer import (
    check_modal_auth,
    deploy_to_modal,
    get_agent_logs,
    list_deployed_agents,
    sanitize_agent_name,
    stop_agent,
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
    payload = {
        "name": agent_config.get("name", analysis.repo_name),
        "description": agent_config.get("description", ""),
        "url": deploy_url,
        "language": analysis.language,
        "verbs": agent_config.get("verbs", []),
        "entry_function": agent_config.get("entry_function", ""),
        "entry_file": agent_config.get("entry_file", ""),
        "tags": agent_config.get("tags", []),
    }
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
def wrap(repo_url: str = typer.Argument(..., help="GitHub repo URL or user/repo shorthand")):
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


@app.command()
def deploy(
    repo_url: str = typer.Argument(..., help="GitHub repo URL, user/repo shorthand, or local path"),
    local: bool = typer.Option(False, "--local", help="Deploy locally instead of to Modal"),
    port: int = typer.Option(8000, "--port", "-p", help="Port for the local server (only with --local)"),
    registry: Optional[str] = typer.Option(None, "--registry", help="Registry URL to auto-register after deploy"),
):
    """Analyze, wrap, and deploy an agent. Deploys to Modal by default, or locally with --local."""

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

    if not analysis.suggested_entry:
        console.print(
            "[bold red]Error:[/bold red] No suitable entry point found.\n"
            "[dim]  Ensure your repo has Python files with top-level function definitions.[/dim]"
        )
        raise typer.Exit(code=1)

    # Step 2: Generate agent.json + wrapper
    output_dir = os.path.join(".", "agenteazy-output", analysis.repo_name)
    os.makedirs(output_dir, exist_ok=True)

    console.print("[dim]Step 2/4: Generating agent.json and wrapper...[/dim]")
    agent_config = generate_agent_json(analysis, output_dir=output_dir)
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
    else:
        # Modal deployment path
        console.print("[dim]Step 3/4: Deploying to Modal...[/dim]")
        try:
            url = deploy_to_modal(output_dir, analysis.repo_name)
        except Exception as e:
            _handle_error(e, "Modal deploy")
            raise typer.Exit(code=1)

        # Record deploy in history
        record_deploy(
            name=agent_config["name"],
            version=agent_config["version"],
            url=url,
            modal_app_name=analysis.repo_name,
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
            title="AgentEazy - Modal Deploy",
        ))

        # Auto-register with registry if URL provided
        if registry:
            console.print(f"\n[dim]Registering with registry at {registry}...[/dim]")
            _register_with_registry(registry, agent_config, url, analysis)


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
    registry: str = typer.Option("http://localhost:8001", "--registry", help="Registry server URL"),
):
    """Search for agents in the registry."""
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
    registry: str = typer.Option("http://localhost:8001", "--registry", help="Registry server URL"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max agents to show"),
    offset: int = typer.Option(0, "--offset", help="Offset for pagination"),
):
    """List all agents in the registry."""
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
def batch_deploy(
    repos_dir: str = typer.Argument(..., help="Directory containing repo subdirectories"),
    local: bool = typer.Option(False, "--local", help="Deploy locally instead of to Modal"),
    registry: Optional[str] = typer.Option(None, "--registry", help="Registry URL to auto-register"),
):
    """Wrap and deploy all repos in a directory sequentially."""
    repos_dir = os.path.abspath(repos_dir)
    if not os.path.isdir(repos_dir):
        console.print(f"[bold red]Error:[/bold red] '{repos_dir}' is not a directory.")
        raise typer.Exit(code=1)

    subdirs = sorted([
        d for d in os.listdir(repos_dir)
        if os.path.isdir(os.path.join(repos_dir, d)) and not d.startswith(".")
    ])

    if not subdirs:
        console.print(f"[yellow]No subdirectories found in[/yellow] {repos_dir}")
        raise typer.Exit(code=1)

    console.print(f"\n[bold blue]Batch deploy:[/bold blue] {len(subdirs)} repos in {repos_dir}\n")

    results = []
    for repo_name in subdirs:
        repo_path = os.path.join(repos_dir, repo_name)
        console.print(f"\n[bold]{'─' * 50}[/bold]")
        console.print(f"[bold cyan]Processing:[/bold cyan] {repo_name}")

        try:
            analysis = analyze_repo(repo_path)
        except Exception as e:
            results.append({"name": repo_name, "status": "error", "detail": str(e)})
            console.print(f"  [red]Analysis failed:[/red] {e}")
            continue

        if not analysis.suggested_entry:
            results.append({"name": repo_name, "status": "skipped", "detail": "No entry point found"})
            console.print(f"  [yellow]Skipped:[/yellow] no entry point found")
            continue

        output_dir = os.path.join(".", "agenteazy-output", analysis.repo_name)
        os.makedirs(output_dir, exist_ok=True)

        agent_config = generate_agent_json(analysis, output_dir=output_dir)
        wrapper_code = generate_wrapper(agent_config, analysis.local_path)

        if not validate_wrapper(wrapper_code):
            results.append({"name": repo_name, "status": "error", "detail": "Wrapper syntax error"})
            console.print(f"  [red]Error:[/red] generated wrapper has syntax errors")
            continue

        save_agent_json(agent_config, output_dir)
        with open(os.path.join(output_dir, "wrapper.py"), "w") as f:
            f.write(wrapper_code)

        repo_dest = os.path.join(output_dir, "repo")
        if os.path.exists(repo_dest):
            shutil.rmtree(repo_dest)
        shutil.copytree(analysis.local_path, repo_dest, dirs_exist_ok=True)

        reqs_path = os.path.join(output_dir, "requirements.txt")
        wrapper_deps = ["fastapi>=0.100.0", "uvicorn>=0.23.0"]
        all_deps = analysis.dependencies + wrapper_deps
        with open(reqs_path, "w") as f:
            f.write("\n".join(all_deps) + "\n")

        if local:
            results.append({
                "name": repo_name,
                "status": "wrapped",
                "detail": f"Output: {output_dir}",
                "version": agent_config["version"],
            })
            console.print(f"  [green]Wrapped[/green] → {output_dir}")
        else:
            try:
                url = deploy_to_modal(output_dir, analysis.repo_name)
                record_deploy(
                    name=agent_config["name"],
                    version=agent_config["version"],
                    url=url,
                    modal_app_name=analysis.repo_name,
                )
                results.append({
                    "name": repo_name,
                    "status": "deployed",
                    "detail": url,
                    "version": agent_config["version"],
                })
                console.print(f"  [green]Deployed[/green] → {url}")

                if registry:
                    _register_with_registry(registry, agent_config, url, analysis)
            except Exception as e:
                results.append({"name": repo_name, "status": "error", "detail": str(e)})
                console.print(f"  [red]Deploy failed:[/red] {e}")

    # Print summary table
    console.print(f"\n[bold]{'─' * 50}[/bold]")
    table = Table(title=f"Batch Deploy Summary ({len(results)} repos)")
    table.add_column("Name", style="bold cyan")
    table.add_column("Status")
    table.add_column("Version")
    table.add_column("Detail", style="dim")

    for r in results:
        status = r["status"]
        if status == "deployed":
            status_display = "[green]deployed[/green]"
        elif status == "wrapped":
            status_display = "[blue]wrapped[/blue]"
        elif status == "skipped":
            status_display = "[yellow]skipped[/yellow]"
        else:
            status_display = "[red]error[/red]"
        table.add_row(r["name"], status_display, r.get("version", "-"), r.get("detail", ""))

    console.print(table)
    console.print()


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


if __name__ == "__main__":
    app()
